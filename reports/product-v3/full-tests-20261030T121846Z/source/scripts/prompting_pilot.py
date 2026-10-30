"""Frozen zero-shot/two-shot pilot with a cost gate and mandatory verification."""
import argparse
import asyncio
from datetime import datetime,timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from time import perf_counter
import httpx
from repository_live_ab import ROOT,read,save,digest,check_hashes
from verify_saved_super_candidate import JournalCampaign
from agentkernel.config import load_env_file
from agentkernel.repository.learning import evaluation_metrics
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.repair.patch_parser import parse_repair,validation_details
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier

DATA=ROOT/'datasets/learning-pilot/20261011T051345Z'
MODEL='Qwen/Qwen3-30B-A3B-Instruct-2507'
BASE='https://api.tokenfactory.nebius.com/v1'


async def catalog():
    async with httpx.AsyncClient(timeout=30) as client:
        response=await client.get(BASE+'/models',params={'verbose':'true'},headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
        response.raise_for_status()
        return next(r for r in response.json()['data'] if r['id']==MODEL)


async def prepare():
    load_env_file(ROOT/'.env')
    for n,h in read(DATA/'sha256.json').items():
        if digest(DATA/n)!=h: raise ValueError('Frozen dataset changed')
    out=ROOT/'reports/prompting-pilot'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    model=await catalog();save(out/'model-pricing.json',model)
    train=[json.loads(line) for line in (DATA/'train.jsonl').read_text().splitlines()]
    manifest=read(ROOT/'datasets/verified-repairs/20261011T050956Z/manifest.json')
    ids=[r['id'] for r in manifest['examples'] if r['split']=='train']
    training=dict(zip(ids,train,strict=True))
    tests=[json.loads(line) for line in (DATA/'test.jsonl').read_text().splitlines()]
    # Selection is frozen before either model run. No test reference file is read.
    selection={'rwlock_mode':['race_002','race_003'],'wake_all':['deadlock_004','job_queue']}
    jobs=[]
    for arm in ('zero_shot','few_shot'):
        for test in tests:
            messages=[test['messages'][0]]
            if arm=='few_shot':
                for name in selection[test['id']]: messages.extend(training[name]['messages'][1:])
            messages.append(test['messages'][1])
            assert messages[0]==test['messages'][0] and messages[-1]==test['messages'][1]
            payload={'model':MODEL,'messages':messages,'temperature':0,'max_tokens':2048,'stream':False,
                     'response_format':{'type':'json_object'}}
            name=arm+'-'+test['id'];save(out/(name+'-payload.json'),payload)
            jobs.append({'id':name,'arm':arm,'fixture':test['id'],'task':test['task'],
                'source_sha256':test['source_sha256'],'payload_sha256':digest(out/(name+'-payload.json')),
                'training_ids':selection[test['id']] if arm=='few_shot' else [],
                'message_content_utf8_bytes':sum(len(m['content'].encode()) for m in messages)})
    # Deliberately conservative: reserve the entire advertised context per call,
    # plus output cap, rather than pretend bytes are tokens or need a paid tokenizer.
    price=model['pricing'];context=model['context_length']
    bound=Decimal(str(price['prompt']))*context+Decimal(str(price['completion']))*2048+Decimal(str(price.get('request','0')))
    if bound*4>Decimal('10'): raise ValueError('Inference bound exceeds pilot budget')
    save(out/'plan.json',{'jobs':jobs,'model':MODEL,'max_model_calls':4,'attempts_per_job':1,'max_output_tokens':2048,
        'temperature':0,'model_retries':0,'correction_calls':0,'mandatory_verifier':True,'training':False,
        'image':'agentkernel-clang:20261003122908','max_pilot_spend_usd':10,
        'inference_bound_usd':str(bound*4),'per_call_bound_usd':str(bound),'input_reservation_tokens_per_call':context,
        'sandbox_bound_usd':None,'cost_gate':'BLOCKED_UNTIL_SANDBOX_RATE_OR_NO_CHARGE_ACCESS_CONFIRMED',
        'price_basis':'Live per-token catalog rates; whole advertised context charged per call plus full output cap. No model retries.',
        'example_selection':'Two training-only cases per fixture, selected before results. Shared-state examples for rwlock; lock/barrier liveness examples for wake_all. No direct condition-variable training example exists.',
        'reference_isolation':'Reads only frozen test inference messages and task configs, never held-out reference patches or candidate sources.',
        'controller_sha256':digest(Path(__file__))})
    protected={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','datasets','scripts')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json',protected)
    print(json.dumps({'plan':str(out/'plan.json'),'inference_bound_usd':str(bound*4),'jobs':4,'sandbox_bound_usd':None}),flush=True)


async def execute(plan_path,billing):
    if billing not in ('free_beta','prepaid_no_extra_charges'):
        raise ValueError('Sandbox dollar bound is not established; no paid evaluation permitted')
    out=plan_path.resolve(strict=True).parent;plan=read(plan_path)
    check_hashes(read(out/'preserved-sha256.json'))
    if digest(Path(__file__))!=plan['controller_sha256']:raise ValueError('Controller changed after freeze')
    for job in plan['jobs']:
        if digest(out/(job['id']+'-payload.json'))!=job['payload_sha256']:raise ValueError('Payload changed')
        for n,h in job['source_sha256'].items():
            if digest(Path(job['task']['workspace'])/n)!=h:raise ValueError('Holdout source changed')
    load_env_file(ROOT/'.env');live=await catalog();frozen=read(out/'model-pricing.json')
    if live['pricing']!=frozen['pricing'] or live['context_length']!=frozen['context_length']:raise ValueError('Price/context changed; re-establish bound')
    save(out/'started.json',{'utc':datetime.now(timezone.utc).isoformat(),'sandbox_billing_confirmation':billing,
        'max_total_incremental_usd':plan['inference_bound_usd'],'no_training':True})
    staging=out/'staging';staging.mkdir()
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']=plan['image']
    rows=[]
    try:
        async with asyncio.timeout(2400):
            async with httpx.AsyncClient(timeout=120) as client:
                for job in plan['jobs']:
                    folder=out/job['id'];folder.mkdir();started=perf_counter()
                    row={'id':job['id'],'arm':job['arm'],'outcome':'unknown','false_fix':False,'tokens':None,
                         'inference_ms':None,'verification_ms':None,'end_to_end_ms':None,'model_calls':1}
                    rows.append(row)
                    payload=read(out/(job['id']+'-payload.json'))
                    save(folder/'call-started.json',{'payload_sha256':job['payload_sha256']})
                    print('One model call: '+job['id'],flush=True)
                    tick=perf_counter()
                    response=await client.post(BASE+'/chat/completions',json=payload,headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
                    row['inference_ms']=(perf_counter()-tick)*1000
                    save(folder/'http-status.json',{'status':response.status_code})
                    response.raise_for_status();data=response.json();save(folder/'response.json',data)
                    usage=data.get('usage',{});inp=usage.get('prompt_tokens');output=usage.get('completion_tokens')
                    if type(inp)!=int or type(output)!=int:raise ValueError('Missing actual token usage; stop')
                    row.update(input_tokens=inp,output_tokens=output,tokens=inp+output)
                    if inp>plan['input_reservation_tokens_per_call'] or output>2048:raise ValueError('Usage exceeded reservation')
                    row['inference_cost_usd']=float(Decimal(inp)*Decimal(live['pricing']['prompt'])+Decimal(output)*Decimal(live['pricing']['completion']))
                    task=ConcurrencyTask.model_validate(job['task'])
                    original={n:(task.workspace/n).read_bytes().decode() for n in task.source_files}
                    try:
                        if data['choices'][0]['finish_reason']!='stop':raise ValueError('Incomplete output')
                        proposal=parse_repair(data['choices'][0]['message']['content'],original)
                    except (ValueError,TypeError) as exc:
                        save(folder/'invalid-output.json',{'type':type(exc).__name__})
                        row.update(outcome='rejected',invalid_output=True)
                    else:
                        (folder/'candidate.patch').write_text(proposal.patch,encoding='utf-8')
                        async with NebiusSandboxBackend(temporary_parent=staging) as box:
                            await box.upload_project(task.workspace,task.source_files+task.support_files)
                            applied=await box.apply_patch(proposal.patch,task.source_files)
                            save(folder/'patch-application.json',applied.model_dump())
                            if not applied.success:row.update(outcome='rejected',invalid_patch=True)
                            else:
                                for n in task.support_files:
                                    if (await box.read_file(n)).encode()!=(task.workspace/n).read_bytes():raise ValueError('Protected file changed')
                                result=await ConcurrencyVerifier(campaigns=JournalCampaign(folder)).verify_workspace(task,box)
                                save(folder/'verification.json',result.model_dump(mode='json'))
                                row.update(outcome='unknown' if result.infrastructure_failures else ('verified' if result.passed else 'rejected'),
                                    false_fix=result.false_fix,verification_ms=result.duration_ms,stress_passed=result.passed_runs,
                                    semantic_passed=result.semantic_passed,tsan_passed=result.sanitizer_passed)
                    row['end_to_end_ms']=(perf_counter()-started)*1000
                    save(folder/'metrics.json',row)
    finally:
        save(out/'results.json',{'jobs':rows,'arms':{arm:evaluation_metrics([r for r in rows if r['arm']==arm])
            for arm in ('zero_shot','few_shot')},'planned_jobs':4,'completed_jobs':sum(r['outcome']!='unknown' for r in rows)})
        check_hashes(read(out/'preserved-sha256.json'))
        save(out/'integrity.json',{'unchanged':True})


if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--execute',type=Path)
    p.add_argument('--confirmed-sandbox-billing',choices=['free_beta','prepaid_no_extra_charges'])
    a=p.parse_args();asyncio.run(prepare() if a.prepare else execute(a.execute,a.confirmed_sandbox_billing))
