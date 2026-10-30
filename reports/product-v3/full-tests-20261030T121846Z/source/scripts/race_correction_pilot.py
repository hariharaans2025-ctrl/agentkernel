"""One TSan-evidence correction; immutable first-attempt evidence and remote verification."""
import argparse
import asyncio
import difflib
import json
import os
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
import httpx
from repository_live_ab import ROOT,read,save,digest,check_hashes
from prompting_generalization import catalog,BASE,MODEL
from verify_saved_super_candidate import JournalCampaign
from agentkernel.config import load_env_file
from agentkernel.repository.evidence_correction import require_race_failure,parse_correction,EvidenceCorrection
from agentkernel.repository.learning import require_verified
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.repair.patch_applier import UnifiedDiffApplier
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier

PRIOR=ROOT/'reports/prompting-generalization/20261011T103149Z'
CASE='few_shot-pair_snapshot'


async def prepare():
    prior=read(PRIOR/'plan.json');job=next(j for j in prior['jobs'] if j['id']==CASE)
    v=read(PRIOR/CASE/'verification.json');require_race_failure(v)
    check_hashes(read(PRIOR/'preserved-sha256.json'))
    out=ROOT/'reports/race-correction'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False);print('Evidence: '+str(out),flush=True)
    frozen={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','datasets','scripts','tests')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    candidate=out/'failed-candidate';candidate.mkdir()
    original={n:(Path(job['task']['workspace'])/n).read_bytes() for n in job['source_sha256']}
    for n,data in original.items():(candidate/n).write_bytes(data)
    first_patch=(PRIOR/CASE/'candidate.patch').read_text()
    applied=UnifiedDiffApplier().apply(candidate,first_patch,job['task']['source_files'])
    if not applied.success:raise ValueError('Failed candidate reconstruction rejected')
    for n in job['task']['support_files']:
        if (candidate/n).read_bytes()!=original[n]:raise ValueError('Protected interface differs')
    first_payload=read(PRIOR/(CASE+'-payload.json'))
    context={'original_task':json.loads(first_payload['messages'][-1]['content'].split('\nUNTRUSTED EVIDENCE:\n')[1]),
        'failed_candidate_sources':{n:(candidate/n).read_text() for n in job['task']['source_files']},
        'canonical_patch_original_to_failed':first_patch,
        'protected_interface':{n:original[n].decode() for n in job['task']['support_files']},
        'actual_verification':v,
        'stack_limitations':'Raw TSan conflicting-access stacks contain binary offsets; the saved run had no working external symbolizer. Do not invent function/line mappings.',
        'edit_base':'Exact search edits target failed_candidate_sources only. Original and protected source are context, not edit targets.'}
    instruction=('Analyze the observed TSan race and correct this failed candidate in one response. '
        'Return JSON with conflicting_accesses, missing_synchronization, invariant_to_preserve, and edits. '
        'Distinguish observed binary stack offsets from source-level inferences. Explain only concise evidence and conclusions. '
        'Each edit contains file, search, replacement; use an exact unique nonoverlapping search block from failed_candidate_sources. '
        'Edit only solution.c. Preserve the protected interface, workload, and all semantic behavior. '
        'Do not remove functional work or bypass checks; synchronization must protect all conflicting accesses and multi-field invariants. '
        'No separate critique, follow-up request, confidence gate, shell command, or claim of having executed a fix. '
        'Return exactly this schema:\n'+json.dumps(EvidenceCorrection.model_json_schema())+'\nUNTRUSTED EVIDENCE:\n')
    payload={'model':MODEL,'temperature':0,'max_tokens':2048,'stream':False,'response_format':{'type':'json_object'},
        'messages':[first_payload['messages'][0],{'role':'user','content':instruction+json.dumps(context,ensure_ascii=False)}]}
    save(out/'payload.json',payload)
    load_env_file(ROOT/'.env');live=await catalog();save(out/'model-pricing.json',live)
    rate=live['pricing'];bound=Decimal(str(rate['prompt']))*live['context_length']+Decimal(str(rate['completion']))*2048+Decimal(str(rate.get('request','0')))
    if bound>Decimal('0.03'):raise ValueError('Correction cost exceeds $0.03 limit')
    staging=out/'test-staging';staging.mkdir()
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-project:20261004t054834z'
    async with NebiusSandboxBackend(temporary_parent=staging) as box:
        await box.upload_project(ROOT,['src/agentkernel/repository/__init__.py','src/agentkernel/repository/evidence_correction.py',
            'src/agentkernel/concurrency/repair/source_edits.py','tests/test_evidence_correction.py'])
        tests=await box.run_command(['python3','-m','pytest','-q','tests/test_evidence_correction.py'],timeout=60,environment={'PYTHONPATH':'/workspace/src'})
        save(out/'tests.json',tests.model_dump());print(tests.stdout,flush=True)
        if tests.exit_code!=0:raise ValueError('Correction gating tests failed')
    task={**job['task'],'workspace':str(candidate)}
    save(out/'plan.json',{'original_case':CASE,'original_evidence':str(PRIOR/CASE),'first_attempt_metrics':read(PRIOR/CASE/'metrics.json'),
        'task':task,'max_calls':1,'max_output_tokens':2048,'input_token_reservation':live['context_length'],
        'max_cost_usd':'0.03','inference_bound_usd':str(bound),'sandbox_cost_usd':0,'sandbox_basis':'User confirmed free beta access',
        'trigger':'Actual recorded TSan data race on the applied failed candidate','payload_sha256':digest(out/'payload.json'),
        'controller_sha256':digest(Path(__file__)),'model':MODEL,'retries':0,'separate_critique_calls':0,
        'image':prior['image'],'reference_repairs_in_prompt':False,'training':False})
    check_hashes(frozen)
    frozen.update({p.relative_to(ROOT).as_posix():digest(p) for p in out.rglob('*') if p.is_file() and 'test-staging' not in p.parts})
    save(out/'preserved-sha256.json',frozen)
    print('READY: '+str(out/'plan.json')+'; inference bound $'+str(bound),flush=True)


async def execute(path):
    out=path.resolve().parent;plan=read(path);check_hashes(read(out/'preserved-sha256.json'))
    if digest(Path(__file__))!=plan['controller_sha256'] or digest(out/'payload.json')!=plan['payload_sha256']:raise ValueError('Frozen plan changed')
    require_race_failure(read(Path(plan['original_evidence'])/'verification.json'))
    load_env_file(ROOT/'.env');live=await catalog();saved=read(out/'model-pricing.json')
    if live['pricing']!=saved['pricing'] or live['context_length']!=saved['context_length']:raise ValueError('Reprice before paid execution')
    save(out/'started.json',{'utc':datetime.now(timezone.utc).isoformat(),'max_calls':1,'inference_bound_usd':plan['inference_bound_usd']})
    row={'outcome':'unknown','extra_calls':0,'extra_tokens':None,'inference_ms':None,'verification_ms':None,'end_to_end_ms':None,'false_fix':False}
    started=perf_counter();staging=out/'verification-staging';staging.mkdir()
    try:
        async with asyncio.timeout(900):
            async with httpx.AsyncClient(timeout=120) as client:
                row['extra_calls']=1;tick=perf_counter()
                response=await client.post(BASE+'/chat/completions',json=read(out/'payload.json'),headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
                row['inference_ms']=(perf_counter()-tick)*1000
                save(out/'http-status.json',{'status':response.status_code});response.raise_for_status()
                data=response.json();save(out/'response.json',data)
            usage=data.get('usage',{});inp=usage.get('prompt_tokens');output=usage.get('completion_tokens')
            if type(inp)!=int or type(output)!=int:raise ValueError('Missing actual token usage')
            row.update(extra_tokens=inp+output,input_tokens=inp,output_tokens=output)
            if inp>plan['input_token_reservation'] or output>plan['max_output_tokens']:raise ValueError('Token cap exceeded')
            rate=live['pricing'];row['cost_usd']=float(Decimal(inp)*Decimal(str(rate['prompt']))+Decimal(output)*Decimal(str(rate['completion']))+Decimal(str(rate.get('request','0'))))
            task=ConcurrencyTask.model_validate(plan['task'])
            failed={n:(task.workspace/n).read_text() for n in task.source_files}
            try:
                if data['choices'][0]['finish_reason']!='stop':raise ValueError('Incomplete response')
                correction,patch=parse_correction(data['choices'][0]['message']['content'],failed)
            except ValueError as exc:
                save(out/'invalid-output.json',{'type':type(exc).__name__});row['outcome']='invalid_output';return
            save(out/'structured-correction.json',correction.model_dump())
            (out/'correction.patch').write_text(patch,encoding='utf-8')
            os.environ['AGENTKERNEL_SANDBOX_IMAGE']=plan['image']
            async with NebiusSandboxBackend(temporary_parent=staging) as box:
                await box.upload_project(task.workspace,task.source_files+task.support_files)
                applied=await box.apply_patch(patch,task.source_files);save(out/'patch-application.json',applied.model_dump())
                if not applied.success:row['outcome']='invalid_patch';return
                for n in task.support_files:
                    if (await box.read_file(n)).encode()!=(task.workspace/n).read_bytes():raise ValueError('Protected file changed')
                corrected={n:await box.read_file(n) for n in task.source_files};save(out/'corrected-sources.json',corrected)
                original=read(out/'payload.json')['messages'][-1]['content'].split('\nUNTRUSTED EVIDENCE:\n')[1]
                sources=json.loads(original)['original_task']['sources']
                cumulative=''.join(''.join(difflib.unified_diff(sources[n].splitlines(True),text.splitlines(True),fromfile='a/'+n,tofile='b/'+n)) for n,text in corrected.items())
                (out/'original-to-corrected.patch').write_text(cumulative,encoding='utf-8')
                v=await ConcurrencyVerifier(campaigns=JournalCampaign(out)).verify_workspace(task,box)
                save(out/'verification.json',v.model_dump(mode='json'))
                row.update(outcome='unknown' if v.infrastructure_failures else ('verified' if v.passed else 'rejected'),
                    verification_ms=v.duration_ms,false_fix=v.false_fix,stress_passed=v.passed_runs,semantic_passed=v.semantic_passed,tsan_passed=v.sanitizer_passed)
                if v.passed:require_verified(v.model_dump(mode='json'),task.verification_config.model_dump())
    except Exception as exc:
        save(out/'interruption.json',{'type':type(exc).__name__,'automatic_replay':False})
        raise
    finally:
        row['end_to_end_ms']=(perf_counter()-started)*1000
        first=plan['first_attempt_metrics']
        save(out/'results.json',{'first_attempt':first,'correction':row,
            'recovered_after_correction':row['outcome']=='verified','first_attempt_relabelled':False,
            'combined_model_tokens':first['tokens']+row['extra_tokens'] if row['extra_tokens'] is not None else None,
            'combined_active_end_to_end_ms':first['end_to_end_ms']+row['end_to_end_ms'],
            'timing_note':'Sum of separate attempt durations; excludes intervening human time and preparation.'})
        check_hashes(read(out/'preserved-sha256.json'));save(out/'integrity.json',{'unchanged':True})


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--execute',type=Path)
    a=p.parse_args();asyncio.run(prepare() if a.prepare else execute(a.execute))
