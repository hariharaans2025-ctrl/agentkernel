"""Independent, immutable API semantic guards; no guard source is model context."""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/adaptive-v3/product-v3'
OUT=ROOT/'datasets/adaptive-v3/api-guards-v1'
HEAD='#include "state.h"\n#include <stdio.h>\n#include <string.h>\nState s;\n'
TAIL='if(!ok){puts("API_FAIL");return 1;}puts("SEMANTIC_PASS");return 0;}\n'


def program(case):
    family=case['family'];kind=case['variant']-1
    prefix=HEAD;body='int main(void){memset(&s,0,sizeof s);int ok=1;'
    if family=='ledger':
        body+='pthread_mutex_init(&s.mutex,0);'
        body+=[
            's.credits=19;ok &= snapshot(&s)==19;update(&s,0);ok &= s.credits==22 && snapshot(&s)==22;update(&s,1);ok &= s.credits==25 && snapshot(&s)==25;',
            's.buckets[0]=2;s.buckets[1]=3;ok &= snapshot(&s)==5;update(&s,0);ok &= s.buckets[0]==3 && s.buckets[1]==3 && snapshot(&s)==6;update(&s,1);ok &= s.buckets[0]==3 && s.buckets[1]==4 && snapshot(&s)==7;',
            's.produced=9;s.consumed=2;ok &= snapshot(&s)==5;update(&s,0);ok &= s.produced==11 && s.consumed==3 && snapshot(&s)==5;update(&s,1);ok &= s.produced==13 && s.consumed==4 && snapshot(&s)==5;'][kind]
    elif family=='snapshot':
        body+='pthread_mutex_init(&s.mutex,0);publish(&s,17);'
        body+=[
            'ok &= s.tag==17 && s.checksum==(17^0x65) && check_snapshot(&s);s.checksum^=1;ok &= !check_snapshot(&s);s.checksum^=1;publish(&s,23);ok &= s.tag==23 && s.checksum==(23^0x65) && check_snapshot(&s);',
            'ok &= s.lo==17 && s.hi==24 && check_snapshot(&s);s.hi++;ok &= !check_snapshot(&s);s.hi--;publish(&s,23);ok &= s.lo==23 && s.hi==30 && check_snapshot(&s);',
            'ok &= s.epoch==17 && s.payload==187 && s.valid==1 && check_snapshot(&s);s.payload++;ok &= !check_snapshot(&s);s.payload--;publish(&s,23);ok &= s.epoch==23 && s.payload==253 && s.valid==1 && check_snapshot(&s);'][kind]
    elif family=='capacity':
        body+='pthread_mutex_init(&s.mutex,0);'
        body+=[
            's.available=3;ok &= inspect(&s)==0;for(int i=0;i<3;i++){ok &= acquire(&s)==1;ok &= s.available==2-i && s.claimed==i+1;}ok &= inspect(&s)==3;ok &= acquire(&s)==0;ok &= inspect(&s)==3 && s.available==0 && s.claimed==3;',
            's.balance=6;ok &= inspect(&s)==0;ok &= acquire(&s,0)==0;ok &= acquire(&s,-1)==0;ok &= acquire(&s,7)==0;ok &= s.balance==6 && s.withdrawn==0;for(int i=0;i<3;i++){ok &= acquire(&s,2)==1;ok &= s.balance==4-i*2 && s.withdrawn==(i+1)*2;}ok &= inspect(&s)==6;ok &= acquire(&s,2)==0;ok &= inspect(&s)==6 && s.balance==0;',
            's.available=3;ok &= inspect(&s)==0 && s.cancelled==1;for(int i=0;i<3;i++){ok &= acquire(&s)==1;ok &= s.available==2-i && s.reserved==i+1;}ok &= inspect(&s)==3 && s.cancelled==2;ok &= acquire(&s)==0;ok &= inspect(&s)==3 && s.cancelled==3 && s.available==0;'][kind]
    elif family=='rendezvous':
        helper=['rendezvous(&s);','exchange_gate(&s,1);','checkpoint(&s);'][kind]
        prefix+='void* companion(void*x){'+helper+'return 0;}\nvoid partner_call(int publish_mode){pthread_t t;atomic_store(&s.arrivals,0);pthread_create(&t,0,companion,0);if(publish_mode)publish(&s);else observe(&s);pthread_join(t,0);}\n'
        body+='pthread_mutex_init(&s.mutex,0);pthread_barrier_init(&s.gate,0,2);atomic_init(&s.arrivals,0);'
        body+=[
            's.value=19;partner_call(0);ok &= s.seen==19 && atomic_load(&s.arrivals)==2;s.value=7;partner_call(0);ok &= s.seen==7 && atomic_load(&s.arrivals)==2;s.value=0;partner_call(1);ok &= s.value==27 && atomic_load(&s.arrivals)==2;',
            's.slot[0]=7;s.slot[1]=12;partner_call(0);ok &= s.seen==19 && atomic_load(&s.arrivals)==2;s.slot[0]=2;s.slot[1]=5;partner_call(0);ok &= s.seen==7 && atomic_load(&s.arrivals)==2;s.slot[0]=s.slot[1]=0;partner_call(1);ok &= s.slot[0]==4 && s.slot[1]==9 && atomic_load(&s.arrivals)==2;',
            's.value=19;partner_call(0);ok &= s.seen==19 && s.visits==1 && atomic_load(&s.arrivals)==2;s.value=7;partner_call(0);ok &= s.seen==7 && s.visits==2 && atomic_load(&s.arrivals)==2;s.value=s.visits=0;partner_call(1);ok &= s.value==31 && s.visits==1 && atomic_load(&s.arrivals)==2;'][kind]
    elif family=='lock_order':
        prefix+='void* companion(void*x){ready(&s);return 0;}\nvoid partner_call(int reverse_mode){pthread_t t;atomic_store(&s.arrivals,0);pthread_create(&t,0,companion,0);if(reverse_mode)reverse(&s);else forward(&s);pthread_join(t,0);}\n'
        body+='pthread_mutex_init(&s.left,0);pthread_mutex_init(&s.right,0);pthread_mutex_init(&s.third,0);pthread_barrier_init(&s.gate,0,2);atomic_init(&s.arrivals,0);'
        body+=[
            'partner_call(0);ok &= s.a==3 && s.b==7 && atomic_load(&s.arrivals)==2;partner_call(1);ok &= s.a==8 && s.b==18 && atomic_load(&s.arrivals)==2;',
            's.a=s.b=20;partner_call(0);ok &= s.a==16 && s.b==24 && atomic_load(&s.arrivals)==2;partner_call(1);ok &= s.a==18 && s.b==22 && atomic_load(&s.arrivals)==2;',
            'partner_call(0);ok &= s.a==1 && s.b==2 && s.c==3 && atomic_load(&s.arrivals)==2;partner_call(1);ok &= s.a==5 && s.b==7 && s.c==9 && atomic_load(&s.arrivals)==2;'][kind]
    elif family=='predicate':
        body+='pthread_mutex_init(&s.mutex,0);pthread_cond_init(&s.changed,0);sem_init(&s.waiting,0,0);atomic_init(&s.awakened,0);s.value=17;'
        body+=[
            's.ready=1;ok &= await_value(&s)==17 && s.ready==0;complete(&s);ok &= s.value==42 && s.ready==1;ok &= await_value(&s)==42 && s.ready==0;',
            's.done=1;ok &= await_value(&s)==17 && s.done==0;complete(&s);ok &= s.value==73 && s.done==1;ok &= await_value(&s)==73 && s.done==0;',
            's.generation=2;ok &= await_value(&s)==17 && s.generation==3;complete(&s);ok &= s.value==88 && s.generation==2;ok &= await_value(&s)==88 && s.generation==3;'][kind]
    elif family=='audit':
        body+='pthread_mutex_init(&s.mutex,0);atomic_init(&s.audits,7);ok &= count_audits(&s)==7;commit(&s);ok &= count_audits(&s)==8;'
        body+=[
            'ok &= s.value==1;commit(&s);ok &= s.value==2 && count_audits(&s)==9;',
            'ok &= s.count==1 && s.sum==6;commit(&s);ok &= s.count==2 && s.sum==12 && count_audits(&s)==9;',
            'ok &= s.committed==1 && s.bytes==13;commit(&s);ok &= s.committed==2 && s.bytes==26 && count_audits(&s)==9;'][kind]
    elif family=='aggregate':
        body+='pthread_mutex_init(&s.mutex,0);ok &= consistent(&s);record(&s,0);'
        body+=[
            'ok &= s.count==1 && s.sum==5 && consistent(&s);record(&s,1);ok &= s.count==2 && s.sum==10 && consistent(&s);s.sum++;ok &= !consistent(&s);',
            'ok &= s.total==1 && s.accepted==0 && s.rejected==1 && consistent(&s);record(&s,1);ok &= s.total==2 && s.accepted==1 && s.rejected==1 && consistent(&s);s.total++;ok &= !consistent(&s);',
            'ok &= s.total==1 && s.parity[0]==1 && s.parity[1]==0 && consistent(&s);record(&s,1);ok &= s.total==2 && s.parity[0]==1 && s.parity[1]==1 && consistent(&s);s.total++;ok &= !consistent(&s);'][kind]
    else:raise ValueError('Unknown API family')
    return prefix+body+TAIL


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare():
    OUT.mkdir(parents=True,exist_ok=False);manifest=json.loads((DATA/'manifest.json').read_text());rows=[]
    for case in manifest['cases']:
        folder=OUT/case['id'];folder.mkdir();path=folder/'api_oracle.c';path.write_text(program(case),encoding='utf-8',newline='')
        task=json.loads((DATA/case['task']).read_text())
        rows.append({'id':case['id'],'split':case['split'],'family':case['family'],'file':case['id']+'/api_oracle.c',
            'sha256':digest(path),'source_sha256':case['source_sha256'],'runtime_header_sha256':case['support_sha256']['state.h'],
            'semantic_check':{'name':'Every exported API must preserve arbitrary input reads, single-call state changes and helper participation.',
                'build_command':['gcc','-pthread','-g','-O1',*task['source_files'],'api_oracle.c','-o','api_checks'],
                'run_command':['./api_checks'],'expected_stdout':'SEMANTIC_PASS','required':True}})
    (OUT/'manifest.json').write_text(json.dumps({'schema_version':1,'base_dataset':str(DATA.relative_to(ROOT)),
        'dataset_manifest_sha256':digest(DATA/'manifest.json'),'cases':rows,'model_context':False,
        'policy':'Append api_oracle.c to protected support_files and append the required semantic_check. Never expose oracle sources to repair models.'},indent=2),encoding='utf-8')
    print('API_GUARD_OVERLAY',OUT,flush=True)


async def calibrate(mutations=False):
    load_env_file(ROOT/'.env');os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    out=ROOT/'reports/adaptive-v3'/(('api-guards-mutations-' if mutations else 'api-guards-calibration-')+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True,exist_ok=False);guards=json.loads((OUT/'manifest.json').read_text());manifest=json.loads((DATA/'manifest.json').read_text());cases={c['id']:c for c in manifest['cases']};slots=asyncio.Semaphore(3)
    async def one(guard):
        async with slots:
            name=guard['id'];case=cases[name];folder=out/name;folder.mkdir();workspace=folder/'reference';workspace.mkdir()
            task=json.loads((DATA/case['task']).read_text())
            for filename in task['source_files']:
                path=DATA/'references'/name/filename
                if digest(path)!=case['reference_sha256'][filename]:raise ValueError('Reference changed')
                text=path.read_text(encoding='utf-8')
                mutation_file={'ledger':'reader.c','snapshot':'snapshot.c','capacity':'inspect.c','rendezvous':'observe.c',
                    'lock_order':'reverse.c','predicate':'await.c','audit':'read.c','aggregate':'read.c'}[case['family']]
                if mutations and filename==mutation_file:
                    match=re.search(r'\b(?P<rtype>void|int|long)\s+(?P<decl>\w+\([^)]*\))\s*\{',text)
                    if not match:raise ValueError('Mutation signature was not recognized')
                    value=1 if case['family'] in {'snapshot','aggregate'} else 0
                    body='sched_yield();'*text.count('sched_yield(')
                    body+=('return;' if match['rtype']=='void' else 'return '+str(value)+';')
                    candidate='#include "state.h"\n'+match['rtype']+' '+match['decl']+'{'+body+'}\n'
                    if candidate.count('sched_yield(')!=text.count('sched_yield('):raise ValueError('Mutation hook mismatch')
                    text=candidate
                (workspace/filename).write_text(text,encoding='utf-8',newline='')
            header=DATA/'tasks'/name/'state.h'
            if digest(header)!=guard['runtime_header_sha256']:raise ValueError('Runtime header changed')
            (workspace/'state.h').write_bytes(header.read_bytes());api=OUT/guard['file']
            if digest(api)!=guard['sha256']:raise ValueError('Guard changed')
            (workspace/'api_oracle.c').write_bytes(api.read_bytes())
            model=ConcurrencyTask.model_validate({**task,'workspace':workspace,'support_files':['state.h','api_oracle.c'],
                'build_command':guard['semantic_check']['build_command'],'run_command':['./api_checks'],'binary_path':'api_checks'})
            async with NebiusSandboxBackend(temporary_parent=folder) as box:
                await box.upload_project(workspace,model.source_files+model.support_files)
                build=await CCompiler().compile(model,box)
                (folder/'build.json').write_text(json.dumps(build.model_dump(mode='json'),indent=2))
                if not build.success:raise ValueError(name+': API guard build failed')
                result=await box.run_command(['./api_checks'],timeout=4)
                (folder/'execution.json').write_text(json.dumps(result.model_dump(mode='json'),indent=2))
                if result.metadata.get('error'):raise ValueError(name+': API guard infrastructure failure')
                if mutations:
                    if result.exit_code==0 and not result.timed_out:raise ValueError(name+': constant or no-op API accepted')
                elif result.exit_code!=0 or result.timed_out or 'SEMANTIC_PASS' not in result.stdout:raise ValueError(name+': reference failed API guard')
            print('API_MUTATION_REJECTED' if mutations else 'API_VERIFIED',name,flush=True)
            return {'case':name,'reference_api_verified':not mutations,'mutation_rejected':mutations,
                'mutation_scheduling_hooks_preserved':True if mutations else None,
                'guard_sha256':guard['sha256'],'reference_sha256':case['reference_sha256'],'model_calls':0}
    results=await asyncio.gather(*(one(g) for g in guards['cases']))
    (out/'ready.json').write_text(json.dumps({'cases':results,'complete':True,'model_calls':0,'guard_manifest_sha256':digest(OUT/'manifest.json')},indent=2))
    print('API_GUARDS_READY',out,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--calibrate',action='store_true');p.add_argument('--mutations',action='store_true');args=p.parse_args()
    if args.calibrate or args.mutations:asyncio.run(calibrate(args.mutations))
    else:prepare()
