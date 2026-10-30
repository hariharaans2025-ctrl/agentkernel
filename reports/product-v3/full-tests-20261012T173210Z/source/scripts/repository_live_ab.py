"""Step 4: two bounded Super calls using immutable Step 3 message sets."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

from agentkernel.config import load_env_file
from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType, RiskLevel, TaskDifficulty
from agentkernel.core.models import RoutingDecision, TaskRequest
from agentkernel.repository.onboarding import Budgets
from agentkernel.repository.metrics import TokenBudget, summarize
from agentkernel.providers.nebius_token_factory import NebiusTokenFactoryProvider, BOUNDARY
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.repair.patch_parser import parse_repair, validation_details
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from optimization_experiment import RecordingCampaign

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'nvidia/nemotron-3-super-120b-a12b'
CONTEXT = ROOT / 'reports/repository-context/20261007T120315Z/context-result.json'
ONBOARD = ROOT / 'reports/repository-onboarding/20261007T110957Z/plan/plan.json'
BASELINE = ROOT / 'reports/repository-diagnostics/20261007T114433Z/queue-campaign.json'

def read(path): return json.loads(path.read_text(encoding='utf-8'))
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, data):
    with path.open('x', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)

def check_hashes(manifest):
    for name, value in manifest.items():
        if digest(ROOT / name) != value: raise ValueError('Preserved evidence changed: ' + name)

def prepare():
    context, onboarding = read(CONTEXT), read(ONBOARD)
    check_hashes(read(CONTEXT.parent / 'preserved-sha256.json'))
    out = ROOT / 'reports/repository-live-ab' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    protected = {p.relative_to(ROOT).as_posix(): digest(p)
                 for folder in ('src', 'examples', 'benchmarks', 'reports')
                 for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out / 'preserved-sha256.json', protected)
    limits = Budgets(**onboarding['contract']['budgets']).model_copy(update={'max_model_calls': 2})
    plans = []
    for arm in ('full', 'selected_grouped'):
        messages = context['measurements'][arm]['messages']
        if [m['role'] for m in messages] != ['system','user'] or not messages[0]['content'].startswith(BOUNDARY+'\n'):
            raise ValueError('Unsupported saved message structure')
        if context['measurements'][arm]['input_tokens'] > limits.max_input_tokens_per_call:
            raise ValueError('Saved prompt exceeds input budget')
        payload = {'model':MODEL,'stream':False,'temperature':0,'max_tokens':2048,'messages':messages,
                   'response_format':{'type':'json_object'},'chat_template_kwargs':{'enable_thinking':False}}
        save(out / (arm + '-payload.json'), payload)
        plans.append({'arm':arm,'payload_sha256':digest(out/(arm+'-payload.json')),
                      'public_tokenizer_input_tokens':context['measurements'][arm]['input_tokens']})
    save(out / 'plan.json', {'version':1,'arms':plans,'limits':limits.model_dump(),
        'model':MODEL,'output_cap':2048,'retry_count':0,'execution_backend':'nebius',
        'image':'agentkernel-clang:20261003122908','verification_method':'experimental_batch_size_10',
        'verification_config':onboarding['contract']['verification'],
        'input_reservation':6000,'reservation_note':'Reserve full 6000-token input ceiling, not an exact provider prediction. Stop on unknown usage or overrun; provider equivalence is unconfirmed before this experiment.',
        'sources':onboarding['files'],'context_sha256':digest(CONTEXT),'onboarding_sha256':digest(ONBOARD),
        'baseline_sha256':digest(BASELINE),'controller_sha256':digest(Path(__file__)),
        'batch_runner_sha256':digest(ROOT/'scripts/optimization_experiment.py'),
        'policy':'One attempt per arm. No correction, substitution, adaptive routing or escalation. No replay if execution was started.'})
    print(out / 'plan.json', flush=True)

def write_report(out, records, ledger, preserved, stop_reason):
    save(out/'results.json', {'records':records,'summary':summarize(records),
        'reserved_calls':ledger.calls,'known_tokens':ledger.spent,
        'usage_incomplete':ledger.unknown or ledger.pending is not None,
        'preserved_files_unchanged':preserved,'stop_reason':stop_reason})
    lines = ['# Step 4: full versus compact context', '',
             'One synthetic job-queue example, one Super attempt per arm. Fixed order: full then selected/grouped.',
             f'Calls reserved: {ledger.calls}/2. Known tokens: {ledger.spent}. Stop reason: {stop_reason}.',
             f'Protected source and evidence unchanged: {preserved}.', '',
             '| Arm | Outcome | Input tokens | Output tokens | Provider wall seconds | Verification seconds | End-to-end seconds |',
             '|---|---|---:|---:|---:|---:|---:|']
    def seconds(v): return f'{v/1000:.3f}' if v is not None else 'unknown'
    for r in records:
        lines.append(f"| {r['arm']} | {r['outcome']} | {r.get('input_tokens')} | {r.get('output_tokens')} | {seconds(r.get('inference_ms'))} | {seconds(r.get('verification_ms'))} | {seconds(r.get('end_to_end_ms'))} |")
    lines += ['', 'Provider wall latency includes the model-catalog check. Verification includes build, original tests, stress, semantics and TSan. End-to-end includes workspace setup and cleanup.',
              'Actual input/output tokens are provider-reported. Unavailable costs remain null. Incomplete jobs are unknown, not failures.',
              'One pair cannot establish statistical superiority or general repair-quality preservation. No Nano/Ultra routing experiment was performed.',
              'The full verification contract is unchanged: original tests, 100 stress runs, semantic oracle, 3 required TSan runs. Invalid/unapplied proposals are not verified.',
              'Experimental batching was used identically in both arms; production defaults are unchanged. Candidate files are saved as artifacts, not applied to the example project.',
              'A token reservation is checked before calls. Unknown usage or reservation overruns stop subsequent calls; the ceiling is not proof of exact provider tokenization before a response.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

async def execute(plan_path):
    plan_path = plan_path.resolve(strict=True)
    out, plan = plan_path.parent, read(plan_path)
    if plan['controller_sha256'] != digest(Path(__file__)) or plan['batch_runner_sha256'] != digest(ROOT/'scripts/optimization_experiment.py'):
        raise ValueError('Experiment implementation changed since plan')
    check_hashes(read(out/'preserved-sha256.json'))
    for path, key in [(CONTEXT,'context_sha256'),(ONBOARD,'onboarding_sha256'),(BASELINE,'baseline_sha256')]:
        if digest(path) != plan[key]: raise ValueError('Input evidence changed')
    for arm in plan['arms']:
        if digest(out/(arm['arm']+'-payload.json')) != arm['payload_sha256']: raise ValueError('Payload changed')
    # Exclusive start marker blocks replay after interruptions, even if no results exist.
    save(out/'started.json',{'time':datetime.now(timezone.utc).isoformat()})
    staging = out/'staging'
    staging.mkdir()
    load_env_file(ROOT/'.env')
    provider = NebiusTokenFactoryProvider(max_retries=0)
    if provider.models[InferenceTier.SUPER] != MODEL: raise ValueError('Configured Super model differs from plan')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = plan['image']
    task = ConcurrencyTask.model_validate(read(ONBOARD)['task'])
    baseline = CampaignResult.model_validate(read(BASELINE))
    ledger = TokenBudget(Budgets(**plan['limits']))
    records, stop_reason = [], 'completed'
    current = None
    started = perf_counter()
    try:
        async with asyncio.timeout(plan['limits']['max_wall_seconds']):
            availability = await provider.check_models()
            save(out/'model-availability.json',availability.model_dump())
            if availability.error or not availability.models.get('SUPER'): raise ValueError('Super unavailable')
            async with NebiusSandboxBackend(temporary_parent=staging) as box:
                await box.upload_project(task.workspace, task.source_files+task.support_files)
                build = await CCompiler().compile(task,box)
                save(out/'preflight-build.json',build.model_dump())
                if not build.success: raise ValueError('Sandbox build preflight failed')
            for arm_plan in plan['arms']:
                arm = arm_plan['arm']
                arm_out = out/arm
                arm_out.mkdir()
                arm_started = perf_counter()
                current = {'arm':arm,'outcome':'unknown','model_calls':0,'tokens':None,'cost_usd':None,
                           'input_tokens':None,'output_tokens':None,'inference_ms':None,'verification_ms':None,
                           'end_to_end_ms':None,'public_tokenizer_input_tokens':arm_plan['public_tokenizer_input_tokens']}
                records.append(current)
                payload = read(out/(arm+'-payload.json'))
                request = TaskRequest(task_id='job-queue-'+arm,task_type='concurrency_repair',prompt=payload['messages'][1]['content'],
                    metadata={'system_prompt':payload['messages'][0]['content'][len(BOUNDARY+'\n'):],
                              'phase':'repair','structured_output':True,'max_output_tokens':2048})
                routing = RoutingDecision(task_id=request.task_id,difficulty=TaskDifficulty.HARD,risk=RiskLevel.HIGH,confidence=1,
                    selected_tier=InferenceTier.SUPER,selected_provider=ProviderType.NEBIUS,
                    requires_external_knowledge=False,reason='Fixed experimental Super arm; no adaptive escalation')
                ledger.reserve(plan['input_reservation'],plan['output_cap'])
                current['model_calls'] = 1
                save(arm_out/'call-started.json',{'time':datetime.now(timezone.utc).isoformat(),'payload_sha256':arm_plan['payload_sha256']})
                print('Calling Super once: '+arm,flush=True)
                response = await provider.generate(request,routing)
                save(arm_out/'inference.json',response.model_dump(mode='json'))
                inp, output = response.metadata.get('actual_input_tokens'), response.metadata.get('actual_output_tokens')
                current.update(input_tokens=inp,output_tokens=output,tokens=(inp+output if inp is not None and output is not None else None),
                               inference_ms=response.latency_ms,cost_usd=response.estimated_cost_usd,
                               provider_minus_public_tokens=(inp-arm_plan['public_tokenizer_input_tokens'] if inp is not None else None))
                ledger.settle(inp,output)
                if ledger.unknown: raise ValueError('Unknown usage; stop further calls')
                if response.status != ExecutionStatus.SUCCESS:
                    current['outcome'] = 'rejected'
                    current['rejection_stage'] = 'inference_output'
                else:
                    sources = {name:(task.workspace/name).read_bytes().decode('utf-8') for name in task.source_files}
                    try:
                        proposal = parse_repair(response.output_text,sources)
                    except ValueError as exc:
                        current.update(outcome='rejected',rejection_stage='edit_contract')
                        save(arm_out/'validation-errors.json',validation_details(exc))
                    else:
                        save(arm_out/'proposal.json',proposal.model_dump())
                        (arm_out/'candidate.patch').write_text(proposal.patch,encoding='utf-8')
                        async with NebiusSandboxBackend(temporary_parent=staging) as box:
                            await box.upload_project(task.workspace, task.source_files+task.support_files)
                            applied = await box.apply_patch(proposal.patch,task.source_files)
                            save(arm_out/'patch-application.json',applied.model_dump())
                            if not applied.success:
                                current.update(outcome='rejected',rejection_stage='patch_application')
                            else:
                                candidate = {name:await box.read_file(name) for name in task.source_files}
                                save(arm_out/'candidate-sources.json',candidate)
                                for name in task.support_files:
                                    if (await box.read_file(name)).encode() != (task.workspace/name).read_bytes():
                                        raise ValueError('Protected support file changed')
                                print('Full verification: '+arm,flush=True)
                                verification = await ConcurrencyVerifier(campaigns=RecordingCampaign(arm_out,True)).verify_workspace(task,box,baseline)
                                save(arm_out/'verification.json',verification.model_dump(mode='json'))
                                current.update(verification_ms=verification.duration_ms,
                                    outcome='unknown' if verification.infrastructure_failures else ('verified' if verification.passed else 'rejected'),
                                    false_fix=verification.false_fix,semantic_regression=verification.semantic_regression,
                                    semantic_passed=verification.semantic_passed,tsan_passed=verification.sanitizer_passed,
                                    stress_passed=verification.passed_runs,stress_total=verification.total_runs,
                                    deadlocks=verification.deadlock_count,races=verification.race_count)
                                if verification.infrastructure_failures: raise ValueError('Verification infrastructure failure')
                current['end_to_end_ms'] = (perf_counter()-arm_started)*1000
                save(arm_out/'metrics.json',current)
                print(arm+': '+current['outcome']+'; tokens='+str(current['tokens']),flush=True)
    except Exception as exc:
        stop_reason = type(exc).__name__
        save(out/'stopped.json',{'type':stop_reason,'reason':'Stopped without retry; inspect saved inference/verification evidence. Unfinished arm remains unknown.'})
        raise
    finally:
        preserved = True
        try: check_hashes(read(out/'preserved-sha256.json'))
        except ValueError: preserved = False
        save(out/'integrity.json',{'unchanged':preserved,'overall_wall_ms':(perf_counter()-started)*1000})
        write_report(out,records,ledger,preserved,stop_reason)
        if not preserved: raise ValueError('Protected evidence changed')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--execute',type=Path)
    args = parser.parse_args()
    if args.prepare and not args.execute: prepare()
    elif args.execute and not args.prepare: asyncio.run(execute(args.execute))
    else: parser.error('Choose --prepare OR --execute PLAN')
