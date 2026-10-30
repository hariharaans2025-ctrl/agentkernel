"""Separately authorized model retry on the latest failed correction; no reference solutions."""
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


async def prepare_followup():
    previous=ROOT/'reports/race-correction/20261011T111419Z'
    previous_plan=read(previous/'plan.json')
    verification=read(previous/'verification.json')
    require_race_failure(verification)
    check_hashes(read(previous/'preserved-sha256.json'))
    out=ROOT/'reports/model-recovery-followup'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    print('Evidence: '+str(out),flush=True)
    old_payload=read(previous/'payload.json')
    prefix,old_context=old_payload['messages'][-1]['content'].split('\nUNTRUSTED EVIDENCE:\n')
    context=json.loads(old_context)
    latest=read(previous/'corrected-sources.json')
    candidate=out/'failed-candidate';candidate.mkdir()
    for name,source in latest.items():
        (candidate/name).write_text(source,encoding='utf-8',newline='\n')
    old_workspace=Path(previous_plan['task']['workspace'])
    for name in previous_plan['task']['support_files']:
        (candidate/name).write_bytes((old_workspace/name).read_bytes())
    context['failed_candidate_sources']=latest
    context['canonical_patch_original_to_failed']=(previous/'original-to-corrected.patch').read_text()
    context['actual_verification']=verification
    # No reference, manual repair, or successful counterpart is read into this context.
    prefix += ('\nBefore returning, check your proposed edits against every obligation in missing_synchronization. '
        'An explanation alone does not repair an access. Account for both sides of each conflicting pair, '
        'and ensure the edits implement the invariant for every reader and writer. '
        'Do not weaken already valid synchronization. Preserve original scheduling hooks and protected behavior. '
        'Use exact edits against the latest failed_candidate_sources supplied below, not the earlier original source.\n')
    payload={**old_payload,'messages':[old_payload['messages'][0],
        {'role':'user','content':prefix+'\nUNTRUSTED EVIDENCE:\n'+json.dumps(context,ensure_ascii=False)}]}
    save(out/'payload.json',payload)
    load_env_file(ROOT/'.env');live=await catalog();save(out/'model-pricing.json',live)
    rate=live['pricing'];bound=Decimal(str(rate['prompt']))*live['context_length']+Decimal(str(rate['completion']))*2048+Decimal(str(rate.get('request','0')))
    if bound>Decimal('0.03'):raise ValueError('Cost exceeds new one-call limit')
    plan={**previous_plan,'original_evidence':str(previous),'task':{**previous_plan['task'],'workspace':str(candidate)},
        'trigger':'Actual TSan races remaining after the failed prior correction',
        'payload_sha256':digest(out/'payload.json'),'controller_sha256':digest(Path(__file__)),
        'input_token_reservation':live['context_length'],'inference_bound_usd':str(bound),
        'previous_correction_metrics':read(previous/'results.json')['correction'],
        'authorization':'New user request for the model to fix and verify; one additional call with full mandatory verification.',
        'evaluation_scope':'Adapted recovery experiment on an already observed case, not fresh held-out evaluation.',
        'reference_and_manual_repairs_excluded':True}
    save(out/'plan.json',plan)
    frozen={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','datasets','scripts','tests')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    save(out/'preserved-sha256.json',frozen)
    print('READY: '+str(out/'plan.json')+'; bound $'+str(bound),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--execute',type=Path)
    a=p.parse_args();asyncio.run(prepare_followup() if a.prepare else execute(a.execute))


