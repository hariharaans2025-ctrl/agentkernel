"""Versioned, bounded specialist -> Super -> Ultra repair route with mandatory verification."""
import asyncio
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import sys
from time import perf_counter

import httpx
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.instrumentation.sanitizer import instrumented_task,SanitizerConfig
from agentkernel.concurrency.repair.patch_parser import parse_repair
from agentkernel.concurrency.repair.prompts import SYSTEM_PROMPT,repair_prompt
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.repository.learning import require_verified
from .specialist import messages,to_proposal,active_root,tagged_messages,tagged_to_proposal

ADAPTIVE_ID='agentkernel/adaptive-v2'
SUPER='nvidia/nemotron-3-super-120b-a12b'
ULTRA='nvidia/nemotron-3-ultra-550b-a55b'
OUTPUT_CAP=2048


def quote(model):
    pricing=model['pricing'];context=model['context_length']
    if type(context)!=int or context<=OUTPUT_CAP:raise ValueError('Unknown context limit')
    rates=[Decimal(str(pricing[k])) for k in ('prompt','completion')]+[Decimal(str(pricing.get('request','0')))]
    if any(not v.is_finite() or v<0 for v in rates):raise ValueError('Invalid live pricing')
    return float(rates[0]*min(context-OUTPUT_CAP,48000)+rates[1]*OUTPUT_CAP+rates[2])


def route_quote(models):
    available={m['id']:m for m in models}
    identifiers=[os.environ.get('AGENTKERNEL_NEMOTRON_SUPER_MODEL',SUPER),os.environ.get('AGENTKERNEL_NEMOTRON_ULTRA_MODEL',ULTRA)]
    if any(mid not in available for mid in identifiers):raise ValueError('Configured adaptive fallback model is unavailable')
    selected=[available[mid] for mid in identifiers]
    return sum(quote(m) for m in selected)


def may_escalate(outcome):
    return outcome in ('invalid_output','rejected')


async def local_generate(root,messages_,*,base=False,model_root=None):
    root=Path(root)
    python=root/'.training-venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.is_file():raise RuntimeError('Local training runtime is unavailable')
    argv=[str(python),str(root/'scripts/local_specialist_infer.py')]
    if model_root is not None:argv+=['--model-root',str(model_root)]
    if base:argv.append('--base')
    environment={k:v for k,v in os.environ.items() if not re.search(r'(KEY|TOKEN|SECRET|PASSWORD)',k,re.I)}
    process=await asyncio.create_subprocess_exec(*argv,cwd=root,env=environment,
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        out,err=await asyncio.wait_for(process.communicate(json.dumps({'messages':messages_,'max_tokens':OUTPUT_CAP}).encode()),timeout=180)
    except TimeoutError:
        process.kill();await process.wait();raise RuntimeError('Local generation deadline exceeded') from None
    if process.returncode or len(out)>1000000:raise RuntimeError('Local model generation failed; inspect the training runtime')
    value=json.loads(out)
    if type(value.get('input_tokens'))!=int or type(value.get('output_tokens'))!=int:raise ValueError('Local usage unavailable')
    return value


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2,ensure_ascii=False)


class AdaptiveRepair:
    def __init__(self,root,models,campaign_factory,*,on_progress=None,model_root=None):
        self.root=Path(root);self.models=models;self.campaign_factory=campaign_factory;self.progress=on_progress or (lambda data:None)
        self.model_root=Path(model_root) if model_root is not None else active_root(root)

    def examples(self,sources):
        path=self.root/'datasets/verified-repairs/20261011T050956Z'
        manifest=json.loads((path/'manifest.json').read_text())
        ids=[e['id'] for e in manifest['examples'] if e['split']=='train']
        rows=[json.loads(s) for s in (path/'train.jsonl').read_text().splitlines()]
        joined='\n'.join(sources.values());ranked=[]
        for identity,row in zip(ids,rows,strict=True):
            text=row['messages'][1]['content']
            score=sum(3 for marker in ('pthread_barrier_wait','pthread_cond_wait','pthread_rwlock','sched_yield','pthread_mutex') if marker in joined and marker in text)
            ranked.append((score,identity,row))
        ranked.sort(key=lambda item:(-item[0],item[1]))
        return ranked[:1]

    async def run(self,task,folder,*,max_cost_usd,mode='adaptive',max_calls=3,max_total_tokens=150144,max_input_tokens=48000):
        if mode not in ('base','fine_tuned','adaptive'):raise ValueError('Unknown adaptive evaluation mode')
        if type(max_cost_usd) not in (int,float) or not math.isfinite(max_cost_usd) or not 0<=max_cost_usd<=.25:
            raise ValueError('An explicit bounded charge is required')
        if mode=='adaptive' and route_quote(self.models)>max_cost_usd:raise ValueError('Adaptive route exceeds approved charge')
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
        save(folder/'started.json',{'mode':mode,'max_calls':max_calls,'max_cost_usd':max_cost_usd,'automatic_replay':False})
        source={n:(task.workspace/n).read_text(encoding='utf-8') for n in task.source_files}
        headers={n:(task.workspace/n).read_text(encoding='utf-8') for n in task.support_files if n.endswith('.h')}
        description=task.metadata.get('fixture_description','Repair the observed concurrency failure while preserving every invariant.')
        requirements=[s.name for s in task.verification_config.semantic_checks]
        metadata=json.loads((self.model_root/'training.json').read_text())
        start_metadata=json.loads((self.model_root/'started.json').read_text())
        dataset=Path(start_metadata['dataset'])
        if not dataset.is_absolute():dataset=self.root/dataset
        training_example=json.loads((dataset/'train.jsonl').read_text().splitlines()[0])
        local_messages=messages(source,description,headers,requirements,training_example['messages'][0]['content'])
        if metadata.get('output_format')=='tagged_source':local_messages=tagged_messages(source,description,headers,requirements)
        started=perf_counter();rows=[]
        result={'mode':mode,'status':'unknown','attempts':rows,'tokens':0,'cost_usd':0,'reserved_usd':0,
            'model_calls':0,'remote_model_calls':0,'base_model':metadata['base_model'],'adapter_sha256':metadata['adapter_sha256']}
        baseline=None
        try:
            self.progress({'stage':'Remote baseline and source validation'})
            base_folder=folder/'baseline';base_folder.mkdir()
            async with NebiusSandboxBackend() as box:
                await box.upload_project(task.workspace,task.source_files+task.support_files)
                build=await CCompiler().compile(task,box);save(base_folder/'build.json',build.model_dump(mode='json'))
                if not build.success:raise ValueError('Baseline build unavailable; no model call started')
                campaign=self.campaign_factory(base_folder)
                baseline=await campaign.run(task,box,runs=3)
                observed=baseline.failed_runs>0
                if not observed and task.verification_config.sanitizer_required:
                    instrumented=instrumented_task(task)
                    instrumented_build=await CCompiler().compile(instrumented,box,SanitizerConfig().flags)
                    if not instrumented_build.success:raise ValueError('Required baseline TSan build unavailable')
                    races=await campaign.run(instrumented,box,runs=3)
                    if races.infrastructure_failures:raise ValueError('Baseline TSan infrastructure unavailable')
                    observed=races.failed_runs>0
                if not observed:
                    result['status']='baseline_clean';return result
            stages=['base' if mode=='base' else 'fine_tuned']
            if mode=='adaptive':stages+=['super','ultra']
            for stage in stages[:max_calls]:
                used=sum(r['tokens'] if r.get('tokens') is not None else 10240 for r in rows)
                if used+OUTPUT_CAP>=max_total_tokens:
                    result['status']='budget_exhausted';break
                attempt_folder=folder/stage;attempt_folder.mkdir()
                row={'stage':stage,'outcome':'unknown','model_calls':0,'tokens':0,'cost_usd':0,'reserved_usd':0,'false_fix':False}
                rows.append(row)
                self.progress({'stage':stage+' inference','attempts':rows})
                tick=perf_counter()
                try:
                    if stage in ('base','fine_tuned'):
                        input_bound=sum(len(m['content'].encode()) for m in local_messages)+100
                        if input_bound>min(max_input_tokens,8192-OUTPUT_CAP) or used+input_bound+OUTPUT_CAP>max_total_tokens:
                            raise RuntimeError('Specialist input budget exceeded; no call started')
                        save(attempt_folder/'messages.json',local_messages)
                        row.update(model_calls=1,tokens=None);result['model_calls']+=1
                        response=await local_generate(self.root,local_messages,base=stage=='base',model_root=self.model_root)
                        save(attempt_folder/'response.json',response)
                        if response['input_tokens']>max_input_tokens:raise RuntimeError('Local input exceeded the reviewed contract')
                        row.update(input_tokens=response['input_tokens'],output_tokens=response['output_tokens'],
                            tokens=response['input_tokens']+response['output_tokens'],model=response['model'],
                            adapter_sha256=response.get('adapter_sha256'),response=response['text'])
                        if response['finish_reason']!='stop':raise ValueError('Output cap reached')
                        converter=tagged_to_proposal if metadata.get('output_format')=='tagged_source' else to_proposal
                        proposal,canonical=converter(response['text'],source)
                        row['canonical_response']=canonical
                    else:
                        identifier=os.environ.get('AGENTKERNEL_NEMOTRON_'+stage.upper()+'_MODEL',SUPER if stage=='super' else ULTRA)
                        model=next(m for m in self.models if m['id']==identifier)
                        bound=quote(model)
                        if result['reserved_usd']+bound>max_cost_usd:raise ValueError('Remaining route reservation is insufficient')
                        context={'task':description,'sources':source,'headers':headers,'editable_files':list(source),
                            'requirements':requirements,'build_command':task.build_command,'verification':task.verification_config.model_dump(),
                            'baseline':baseline.compact(),'previous_attempts':[{'stage':r['stage'],'outcome':r['outcome'],
                                'response':r.get('response'),'verification':r.get('verification'),'error':r.get('error')} for r in rows[:-1]]}
                        examples=self.examples(source);prompt=repair_prompt(context)+'\nPreserve the exact count and original semantics of every sched_yield call. Do not remove scheduling hooks or replace them with another API. JSON-encode source strings exactly once.'
                        chat=[{'role':'system','content':SYSTEM_PROMPT}]
                        for _,_,example in examples:chat+=example['messages'][1:]
                        chat.append({'role':'user','content':prompt})
                        if sum(len(m['content'].encode()) for m in chat)+100>min(max_input_tokens,48000,model['context_length']-OUTPUT_CAP):
                            chat=[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':prompt}];examples=[]
                        input_bound=sum(len(m['content'].encode()) for m in chat)+100
                        if input_bound>min(max_input_tokens,48000,model['context_length']-OUTPUT_CAP) or used+input_bound+OUTPUT_CAP>max_total_tokens:
                            raise RuntimeError('Source/evidence context exceeds reviewed token budget; no call started')
                        payload={'model':model['id'],'messages':chat,'max_tokens':OUTPUT_CAP,'temperature':0,
                            'response_format':{'type':'json_object'}}
                        if stage=='super':payload['chat_template_kwargs']={'enable_thinking':False}
                        save(attempt_folder/'payload.json',payload);save(attempt_folder/'pricing.json',model)
                        row.update(model=model['id'],reserved_usd=bound,training_examples=[identity for _,identity,_ in examples])
                        result['reserved_usd']+=bound;result['remote_model_calls']+=1;result['model_calls']+=1
                        row.update(model_calls=1,tokens=None)
                        self.progress({'reserved_usd':result['reserved_usd'],'remote_model_calls':result['remote_model_calls'],'attempts':rows})
                        async with httpx.AsyncClient(timeout=120) as client:
                            response=await client.post('https://api.tokenfactory.nebius.com/v1/chat/completions',json=payload,
                                headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
                        save(attempt_folder/'http-status.json',{'status':response.status_code});response.raise_for_status()
                        data=response.json();save(attempt_folder/'response.json',data)
                        usage=data.get('usage',{});inp,out=usage.get('prompt_tokens'),usage.get('completion_tokens')
                        if type(inp)!=int or type(out)!=int or inp<0 or not 0<=out<=OUTPUT_CAP:
                            raise RuntimeError('Unknown or out-of-contract paid usage; stop without escalation')
                        cost=float(Decimal(inp)*Decimal(str(model['pricing']['prompt']))+Decimal(out)*Decimal(str(model['pricing']['completion']))+Decimal(str(model['pricing'].get('request','0'))))
                        if cost>bound or inp>min(max_input_tokens,48000,model['context_length']-OUTPUT_CAP):raise RuntimeError('Provider usage exceeded reservation')
                        choice=data['choices'][0];row.update(tokens=inp+out,input_tokens=inp,output_tokens=out,
                            cost_usd=cost,response=choice['message']['content'])
                        if choice['finish_reason']!='stop':raise ValueError('Output cap reached')
                        proposal=parse_repair(row['response'],source)
                except (ValueError,TypeError,json.JSONDecodeError) as exc:
                    row.update(outcome='invalid_output',error=type(exc).__name__,inference_ms=(perf_counter()-tick)*1000)
                    save(attempt_folder/'result.json',row)
                    self.progress({'attempts':rows})
                    if stage in ('base','fine_tuned') and mode!='adaptive':break
                    # Local invalid output is an explicitly bounded v2 escalation trigger.
                    continue
                row['inference_ms']=(perf_counter()-tick)*1000
                row['patch']=proposal.patch;(attempt_folder/'candidate.patch').write_text(proposal.patch,encoding='utf-8')
                self.progress({'stage':stage+' verification: protected tests, 100 stress, semantics, 3 TSan','attempts':rows})
                async with NebiusSandboxBackend() as box:
                    await box.upload_project(task.workspace,task.source_files+task.support_files)
                    applied=await box.apply_patch(proposal.patch,task.source_files);save(attempt_folder/'patch-application.json',applied.model_dump(mode='json'))
                    if not applied.success:
                        row.update(outcome='invalid_output',error='Canonical patch rejected')
                    else:
                        for name in task.support_files:
                            if (await box.read_file(name)).encode()!=(task.workspace/name).read_bytes():raise RuntimeError('Protected file changed')
                        candidate={n:await box.read_file(n) for n in task.source_files}
                        save(attempt_folder/'candidate-sources.json',candidate)
                        verified=await ConcurrencyVerifier(campaigns=self.campaign_factory(attempt_folder)).verify_workspace(task,box,baseline)
                        save(attempt_folder/'verification.json',verified.model_dump(mode='json'))
                        hooks=all(candidate[n].count('sched_yield(')==source[n].count('sched_yield(') for n in source)
                        row.update(outcome='unknown' if verified.infrastructure_failures else ('verified' if verified.passed and hooks else 'rejected'),
                            verification={'build_passed':verified.build_passed,'original_tests_passed':verified.evidence.get('original_tests',{}).get('passed'),
                                'passed_runs':verified.passed_runs,'total_runs':verified.total_runs,'semantic_passed':verified.semantic_passed,
                                'tsan_passed':verified.sanitizer_passed,'scheduling_hooks_preserved':hooks},
                            verification_ms=verified.duration_ms,false_fix=verified.false_fix or not hooks)
                        if row['outcome']=='verified':require_verified(verified.model_dump(mode='json'),task.verification_config.model_dump())
                save(attempt_folder/'result.json',row)
                self.progress({'attempts':rows})
                if row['outcome']=='verified':result['status']='verified';break
                if not may_escalate(row['outcome']):break
                known=sum(r['tokens'] for r in rows if r.get('tokens') is not None)
                if known+min(48000,8192)+OUTPUT_CAP>max_total_tokens:break
            else:result['status']='rejected'
            if result['status']=='unknown' and rows and rows[-1]['outcome']!='unknown':result['status']='rejected'
        except Exception as exc:
            result['error']=type(exc).__name__+': route stopped without automatic replay.'
            result['status']='unknown'
            if rows:rows[-1]['error']=result['error']
        finally:
            result['tokens']=None if any(r.get('tokens') is None for r in rows) else sum(r['tokens'] for r in rows)
            unknown_paid=any(r.get('reserved_usd',0)>0 and r.get('tokens') is None for r in rows)
            result['cost_usd']=None if unknown_paid else sum(r.get('cost_usd',0) for r in rows)
            result['end_to_end_ms']=(perf_counter()-started)*1000
            result['false_fix']=any(r.get('false_fix') for r in rows)
            final=next((r for r in reversed(rows) if r.get('patch')),rows[-1] if rows else {})
            for key in ('patch','response','verification'):result[key]=final.get(key)
            result['inference_ms']=sum(r.get('inference_ms',0) for r in rows)
            result['verification_ms']=sum(r.get('verification_ms',0) for r in rows)
            save(folder/'result.json',result)
        return result
