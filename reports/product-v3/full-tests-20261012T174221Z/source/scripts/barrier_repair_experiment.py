"""One new diagnostic-assisted Super attempt; immutable evidence, no replay."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import perf_counter

from repository_live_ab import (ROOT, MODEL, CONTEXT, ONBOARD, BASELINE, read, save,
    digest, check_hashes, load_env_file, NebiusTokenFactoryProvider, BOUNDARY,
    InferenceTier, TaskRequest, RoutingDecision, TaskDifficulty, RiskLevel,
    ProviderType, ExecutionStatus, Budgets, TokenBudget, ConcurrencyTask,
    CampaignResult, NebiusSandboxBackend, CCompiler, parse_repair,
    validation_details, ConcurrencyVerifier, RecordingCampaign)

DIAG = ROOT/'reports/barrier-diagnostics/20261010T091800Z'
TOKENIZE = '''import hashlib, json
from pathlib import Path
from urllib.request import urlopen
from transformers import AutoTokenizer
spec=json.loads(Path('tokenizer-spec.json').read_text())
assets=Path('tokenizer'); assets.mkdir()
for name, expected in spec['asset_sha256'].items():
    url='https://huggingface.co/'+spec['repository']+'/resolve/'+spec['revision']+'/'+name
    with urlopen(url,timeout=30) as response: data=response.read(40000001)
    assert len(data)<=40000000 and hashlib.sha256(data).hexdigest()==expected
    (assets/name).write_bytes(data)
t=AutoTokenizer.from_pretrained(str(assets),local_files_only=True,trust_remote_code=False)
p=json.loads(Path('payload.json').read_text())
tokens=t.apply_chat_template(p['messages'],tokenize=True,add_generation_prompt=True,enable_thinking=False)
Path('token-count.json').write_text(json.dumps({'public_tokenizer_input_tokens':len(tokens),'tokenizer':spec}))
print('Input tokens:',len(tokens))
'''


async def prepare():
    check_hashes(read(DIAG/'preserved-sha256.json'))
    context = read(DIAG/'repair-context.json')
    previous = read(CONTEXT)
    assert {k:v for k,v in context.items() if k != 'static_barrier_diagnostics'} == previous['compact_context']
    assert context['static_barrier_diagnostics'] == read(DIAG/'diagnostic-results.json')['original']
    payload = read(ROOT/'reports/repository-live-ab/20261007T121122Z/selected_grouped-payload.json')
    prefix = payload['messages'][1]['content'].split('\nUNTRUSTED EVIDENCE:\n')[0]+'\nUNTRUSTED EVIDENCE:\n'
    payload['messages'][1]['content'] = prefix+json.dumps(context,ensure_ascii=False,separators=(',',':'))
    out = ROOT/'reports/barrier-repair-live'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    print('Evidence: '+str(out),flush=True)
    protected = {p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','scripts')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json',protected)
    save(out/'payload.json',payload)
    staging = out/'preparation-staging'; staging.mkdir()
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-project:20261004t054834z'
    async with NebiusSandboxBackend(temporary_parent=staging) as box:
        install = await box.run_command(['python3','-m','pip','install','transformers==4.57.1','jinja2==3.1.6'],timeout=110)
        save(out/'tokenizer-install.json',install.model_dump())
        if install.exit_code != 0 or install.timed_out: raise RuntimeError('Tokenizer install failed')
        await box._upload({'/workspace/payload.json':json.dumps(payload).encode(),
            '/workspace/tokenizer-spec.json':json.dumps(previous['tokenizer']).encode(),
            '/workspace/count_tokens.py':TOKENIZE.encode()})
        count = await box.run_command(['python3','count_tokens.py'],timeout=110)
        save(out/'tokenizer-execution.json',count.model_dump())
        print(count.stdout,flush=True)
        if count.exit_code != 0 or count.timed_out: raise RuntimeError('Token counting failed')
        measured = json.loads(await box.read_file('token-count.json'))
        save(out/'token-count.json',measured)
    if measured['public_tokenizer_input_tokens']>6000: raise ValueError('Input exceeds unchanged 6000-token ceiling')
    check_hashes(protected)
    save(out/'plan.json',{'model':MODEL,'max_model_calls':1,'max_input_tokens':6000,'max_output_tokens':2048,
        'max_total_tokens':8048,'max_wall_seconds':1800,'retries':0,'image':'agentkernel-clang:20261003122908',
        'payload_sha256':digest(out/'payload.json'),'controller_sha256':digest(Path(__file__)),
        'token_count_sha256':digest(out/'token-count.json'), 'public_tokenizer_input_tokens':measured['public_tokenizer_input_tokens'],
        'verification':read(ONBOARD)['contract']['verification'],
        'endpoint':'https://api.tokenfactory.nebius.com/v1/chat/completions',
        'scope':'Original synthetic queue source, original runtime evidence and new original-source static diagnostic only. No known-good repair, keys or environment dumps. No retries, corrections, substitutions or escalation.'})
    print('Ready: '+str(out/'plan.json'),flush=True)


async def execute(plan_path):
    out=plan_path.resolve(strict=True).parent
    plan=read(out/'plan.json')
    check_hashes(read(out/'preserved-sha256.json'))
    for path,key in [(out/'payload.json','payload_sha256'),(Path(__file__),'controller_sha256'),(out/'token-count.json','token_count_sha256')]:
        if digest(path)!=plan[key]: raise ValueError('Planned input changed')
    save(out/'started.json',{'utc':datetime.now(timezone.utc).isoformat()})
    load_env_file(ROOT/'.env')
    provider=NebiusTokenFactoryProvider(max_retries=0)
    if provider.models[InferenceTier.SUPER]!=MODEL: raise ValueError('Configured model changed')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']=plan['image']
    staging=out/'execution-staging'; staging.mkdir()
    task=ConcurrencyTask.model_validate(read(ONBOARD)['task'])
    ledger=TokenBudget(Budgets(max_model_calls=1,max_total_tokens=8048,max_input_tokens_per_call=6000,
                               max_output_tokens_per_call=2048,max_wall_seconds=1800))
    metrics={'outcome':'unknown','model_calls':0,'tokens':None,'cost_usd':None,'inference_ms':None,'verification_ms':None}
    started=perf_counter()
    try:
        async with asyncio.timeout(1800):
            availability=await provider.check_models()
            save(out/'model-availability.json',availability.model_dump())
            if availability.error or not availability.models.get('SUPER'): raise RuntimeError('Super unavailable')
            async with NebiusSandboxBackend(temporary_parent=staging) as box:
                await box.upload_project(task.workspace,task.source_files+task.support_files)
                build=await CCompiler().compile(task,box)
                save(out/'preflight-build.json',build.model_dump())
                if not build.success: raise RuntimeError('Sandbox build unavailable')
                payload=read(out/'payload.json')
                request=TaskRequest(task_id='job-queue-barrier-diagnostic',task_type='concurrency_repair',
                    prompt=payload['messages'][1]['content'],metadata={'system_prompt':payload['messages'][0]['content'][len(BOUNDARY+'\n'):],
                    'phase':'repair','structured_output':True,'max_output_tokens':2048})
                routing=RoutingDecision(task_id=request.task_id,difficulty=TaskDifficulty.HARD,risk=RiskLevel.HIGH,confidence=1,
                    selected_tier=InferenceTier.SUPER,selected_provider=ProviderType.NEBIUS,requires_external_knowledge=False,
                    reason='One fixed diagnostic-assisted Super experiment')
                ledger.reserve(6000,2048)
                save(out/'call-started.json',{'utc':datetime.now(timezone.utc).isoformat(),'payload_sha256':plan['payload_sha256']})
                metrics['model_calls']=1
                print('Calling Super once.',flush=True)
                response=await provider.generate(request,routing)
                save(out/'inference.json',response.model_dump(mode='json'))
                inp,output=response.metadata.get('actual_input_tokens'),response.metadata.get('actual_output_tokens')
                metrics.update(input_tokens=inp,output_tokens=output,tokens=inp+output if inp is not None and output is not None else None,
                    inference_ms=response.latency_ms,cost_usd=response.estimated_cost_usd,
                    provider_minus_public_tokens=inp-plan['public_tokenizer_input_tokens'] if inp is not None else None)
                ledger.settle(inp,output)
                if ledger.unknown: raise RuntimeError('Usage unknown; stop')
                if response.status != ExecutionStatus.SUCCESS:
                    metrics.update(outcome='rejected',rejection_stage='inference_output')
                    return
                try:
                    proposal=parse_repair(response.output_text,{name:(task.workspace/name).read_bytes().decode() for name in task.source_files})
                except ValueError as exc:
                    save(out/'validation-errors.json',validation_details(exc))
                    metrics.update(outcome='rejected',rejection_stage='edit_contract')
                    return
                save(out/'proposal.json',proposal.model_dump())
                (out/'candidate.patch').write_text(proposal.patch,encoding='utf-8')
                applied=await box.apply_patch(proposal.patch,task.source_files)
                save(out/'patch-application.json',applied.model_dump())
                if not applied.success:
                    metrics.update(outcome='rejected',rejection_stage='patch_application')
                    return
                save(out/'candidate-sources.json',{name:await box.read_file(name) for name in task.source_files})
                for name in task.support_files:
                    if (await box.read_file(name)).encode()!=(task.workspace/name).read_bytes(): raise RuntimeError('Protected support changed')
                print('Verifying candidate: 100 stress runs, original tests, semantics and 3 TSan runs.',flush=True)
                result=await ConcurrencyVerifier(campaigns=RecordingCampaign(out,True)).verify_workspace(task,box,CampaignResult.model_validate(read(BASELINE)))
                save(out/'verification.json',result.model_dump(mode='json'))
                metrics.update(outcome='unknown' if result.infrastructure_failures else ('verified' if result.passed else 'rejected'),
                    verification_ms=result.duration_ms,stress_passed=result.passed_runs,stress_total=result.total_runs,
                    semantic_passed=result.semantic_passed,tsan_passed=result.sanitizer_passed,false_fix=result.false_fix,
                    semantic_regression=result.semantic_regression,infrastructure_failures=result.infrastructure_failures)
    finally:
        metrics['end_to_end_ms']=(perf_counter()-started)*1000
        metrics['usage_incomplete']=ledger.unknown or ledger.pending is not None
        save(out/'metrics.json',metrics)
        check_hashes(read(out/'preserved-sha256.json'))
        save(out/'integrity.json',{'unchanged':True,'protected_files':len(read(out/'preserved-sha256.json'))})
        (out/'REPORT.md').write_text('# Diagnostic-assisted Super experiment\n\n'+
            'One attempt on the original synthetic job queue. No retry, correction, substitution or escalation.\n\n'+
            '\n'.join(f'- {k}: {v}' for k,v in metrics.items())+'\n\n'+
            'Provider latency includes the catalog check. End-to-end includes sandbox preflight and cleanup, excludes one-time tokenizer preparation. Costs remain unknown when not reported.\n'+
            'All prior evidence and source files remain unchanged. One observation cannot establish statistical superiority or general repair quality.\n',encoding='utf-8')
        print(json.dumps(metrics),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true'); group.add_argument('--execute',type=Path)
    args=p.parse_args()
    asyncio.run(prepare() if args.prepare else execute(args.execute))
