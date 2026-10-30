"""Freeze policy and four new programs; calibrate references before model evaluation."""
import asyncio
import difflib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from repository_live_ab import ROOT, read, save, digest, check_hashes
from prompting_generalization import catalog, MODEL
from verify_saved_super_candidate import JournalCampaign
from agentkernel.config import load_env_file
from agentkernel.repository.learning import require_verified
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.concurrency.instrumentation.sanitizer import SanitizerConfig, instrumented_task

PRIOR=ROOT/'reports/prompting-pilot/20261011T052135Z'
TRAIN=ROOT/'datasets/learning-pilot/20261011T051345Z/train.jsonl'
COMMON='#include <pthread.h>\n#include <sched.h>\n'
CASES={
 'pair_snapshot': {
  'family':'shared_state',
  'header':'extern pthread_mutex_t guard;\nextern int left, right;\nvoid update_pair(int n);\nint snapshot_ok(void);\n',
  'source':'''#include "state.h"
void update_pair(int n) {
    pthread_mutex_lock(&guard);
    left = n;
    sched_yield();
    right = -n;
    pthread_mutex_unlock(&guard);
}
int snapshot_ok(void) {
    int a = left;
    sched_yield();
    int b = right;
    return a + b == 0;
}
''',
  'old':'''int snapshot_ok(void) {
    int a = left;
    sched_yield();
    int b = right;
    return a + b == 0;
}''',
  'new':'''int snapshot_ok(void) {
    pthread_mutex_lock(&guard);
    int a = left;
    sched_yield();
    int b = right;
    pthread_mutex_unlock(&guard);
    return a + b == 0;
}''',
  'oracle':'''#include "state.h"
#include <stdio.h>
pthread_mutex_t guard = PTHREAD_MUTEX_INITIALIZER;
int left, right;
static int bad;
static pthread_barrier_t start;
static void *writer(void *p) { (void)p; pthread_barrier_wait(&start); for(int i=1;i<=3000;i++) update_pair(i); return 0; }
static void *reader(void *p) { (void)p; pthread_barrier_wait(&start); for(int i=0;i<3000;i++) if(!snapshot_ok()) bad++; return 0; }
int main(void) {
    pthread_t a,b;
    left=1; right=0;
    if(snapshot_ok()) return 1;
    left=0;
    if(!snapshot_ok()) return 1;
    if(pthread_barrier_init(&start,0,2)) return 2;
    if(pthread_create(&a,0,writer,0)||pthread_create(&b,0,reader,0)) return 2;
    if(pthread_join(a,0)||pthread_join(b,0)) return 2;
    if(bad || left!=3000 || right!=-3000) {puts("SEMANTIC_FAIL");return 1;}
    puts("SEMANTIC_PASS");puts("PASS");return 0;
}
'''
 },
 'inventory_balance': {
  'family':'shared_state',
  'header':'extern pthread_mutex_t stock_guard, sales_guard;\nextern int stock;\nvoid restock(void);\nvoid sell(void);\n',
  'source':'''#include "state.h"
void restock(void) {
    pthread_mutex_lock(&stock_guard);
    int n = stock;
    sched_yield();
    stock = n + 1;
    pthread_mutex_unlock(&stock_guard);
}
void sell(void) {
    pthread_mutex_lock(&sales_guard);
    int n = stock;
    sched_yield();
    stock = n - 1;
    pthread_mutex_unlock(&sales_guard);
}
''',
  'old':'sales_guard', 'new':'stock_guard',
  'oracle':'''#include "state.h"
#include <stdio.h>
pthread_mutex_t stock_guard = PTHREAD_MUTEX_INITIALIZER, sales_guard = PTHREAD_MUTEX_INITIALIZER;
int stock=10000;
static pthread_barrier_t start;
static void *supply(void *p) {(void)p;pthread_barrier_wait(&start);for(int i=0;i<3000;i++) restock();return 0;}
static void *demand(void *p) {(void)p;pthread_barrier_wait(&start);for(int i=0;i<3000;i++) sell();return 0;}
int main(void) {
    pthread_t a,b;
    restock(); if(stock!=10001) return 1;
    sell(); if(stock!=10000) return 1;
    if(pthread_barrier_init(&start,0,2)) return 2;
    if(pthread_create(&a,0,supply,0)||pthread_create(&b,0,demand,0)) return 2;
    if(pthread_join(a,0)||pthread_join(b,0)) return 2;
    if(stock!=10000) {puts("SEMANTIC_FAIL");return 1;}
    puts("SEMANTIC_PASS");puts("PASS");return 0;
}
'''
 },
 'nested_credit': {
  'family':'liveness',
  'header':'extern pthread_mutex_t ledger;\nextern int accounts[2];\nvoid transfer(int from, int to);\n',
  'source':'''#include "state.h"
static void credit(int to) {
    pthread_mutex_lock(&ledger);
    accounts[to] += 1;
    pthread_mutex_unlock(&ledger);
}
void transfer(int from, int to) {
    pthread_mutex_lock(&ledger);
    accounts[from] -= 1;
    credit(to);
    pthread_mutex_unlock(&ledger);
}
''',
  'old':'''static void credit(int to) {
    pthread_mutex_lock(&ledger);
    accounts[to] += 1;
    pthread_mutex_unlock(&ledger);
}''',
  'new':'''static void credit(int to) {
    accounts[to] += 1;
}''',
  'oracle':'''#include "state.h"
#include <stdio.h>
pthread_mutex_t ledger = PTHREAD_MUTEX_INITIALIZER;
int accounts[2]={1000,1000};
static void *worker(void *p) {(void)p;for(int i=0;i<100;i++) transfer(0,1);return 0;}
int main(void) {
    pthread_t a,b;
    if(pthread_create(&a,0,worker,0)||pthread_create(&b,0,worker,0)) return 2;
    if(pthread_join(a,0)||pthread_join(b,0)) return 2;
    if(accounts[0]!=800 || accounts[1]!=1200) {puts("SEMANTIC_FAIL");return 1;}
    puts("SEMANTIC_PASS");puts("PASS");return 0;
}
'''
 },
 'empty_queue_return': {
  'family':'liveness',
  'header':'extern pthread_mutex_t queue_guard;\nextern int occupied, item;\nint take(int *out);\nvoid put(int n);\n',
  'source':'''#include "state.h"
int take(int *out) {
    pthread_mutex_lock(&queue_guard);
    if (!occupied) return 0;
    *out = item;
    occupied = 0;
    pthread_mutex_unlock(&queue_guard);
    return 1;
}
void put(int n) {
    pthread_mutex_lock(&queue_guard);
    item = n;
    occupied = 1;
    pthread_mutex_unlock(&queue_guard);
}
''',
  'old':'if (!occupied) return 0;',
  'new':'if (!occupied) { pthread_mutex_unlock(&queue_guard); return 0; }',
  'oracle':'''#include "state.h"
#include <stdio.h>
pthread_mutex_t queue_guard = PTHREAD_MUTEX_INITIALIZER;
int occupied, item;
static int first, second, value=-1, last;
static void *empty(void *p) {(void)p;first=take(&value);return 0;}
static void *fill(void *p) {(void)p;put(42);return 0;}
static void *consume(void *p) {(void)p;second=take(&value);last=take(&value);return 0;}
int main(void) {
    pthread_t t;
    if(pthread_create(&t,0,empty,0)||pthread_join(t,0)) return 2;
    if(pthread_create(&t,0,fill,0)||pthread_join(t,0)) return 2;
    if(pthread_create(&t,0,consume,0)||pthread_join(t,0)) return 2;
    if(first!=0 || second!=1 || value!=42 || last!=0 || occupied!=0) {puts("SEMANTIC_FAIL");return 1;}
    puts("SEMANTIC_PASS");puts("PASS");return 0;
}
'''
 }
}

async def main():
    out=ROOT/'reports/prompting-generalization'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    print('Evidence: '+str(out),flush=True)
    prior=read(PRIOR/'few_shot-rwlock_mode-payload.json')
    policy={'system':prior['messages'][0], 'user_prefix':prior['messages'][-1]['content'].split('\nUNTRUSTED EVIDENCE:\n')[0]+'\nUNTRUSTED EVIDENCE:\n',
        'selection':{'shared_state':['race_002','race_003'],'liveness':['deadlock_004','job_queue']},
        'selection_basis':'Fixed coarse family labels assigned before any model calls. Curator labels, not an evaluated automatic router.',
        'training_sha256':digest(TRAIN),'prior_payload_sha256':digest(PRIOR/'few_shot-rwlock_mode-payload.json'),
        'settings':{k:v for k,v in prior.items() if k!='messages'},
        'no_adaptation':'All eight exact payloads frozen before first evaluation call; no selection, prompt, cap, or verification changes after results.'}
    save(out/'frozen-policy.json',policy)
    protected={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','datasets','scripts')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'prior-sha256.json',protected)
    templates=read(PRIOR/'plan.json')['jobs'][0]['task']
    train=[json.loads(s) for s in TRAIN.read_text().splitlines()]
    ids=[x['id'] for x in read(ROOT/'datasets/verified-repairs/20261011T050956Z/manifest.json')['examples'] if x['split']=='train']
    training=dict(zip(ids,train,strict=True));jobs=[];tasks={}
    for name,case in CASES.items():
        base=out/'inputs'/name;base.mkdir(parents=True)
        for file,content in [('state.h',COMMON+case['header']),('solution.c',case['source']),('oracle.c',case['oracle'])]:
            (base/file).write_text(content,encoding='utf-8',newline='\n')
        task={**templates,'task_id':name,'workspace':str(base)}
        tasks[name]=ConcurrencyTask.model_validate(task)
        context={'original_task':'Repair the concurrency bug while preserving all protected workload invariants.',
            'editable_files':task['source_files'],'sources':{n:(base/n).read_text() for n in task['source_files']+task['support_files']},
            'verification_requirements':task['verification_config']}
        user={'role':'user','content':policy['user_prefix']+json.dumps(context,ensure_ascii=False)}
        for arm in ('zero_shot','few_shot'):
            examples=policy['selection'][case['family']] if arm=='few_shot' else []
            messages=[policy['system']]
            for example in examples:messages.extend(training[example]['messages'][1:])
            messages.append(user)
            payload={**policy['settings'],'messages':messages};jobid=arm+'-'+name
            save(out/(jobid+'-payload.json'),payload)
            jobs.append({'id':jobid,'arm':arm,'fixture':name,'family':case['family'],'task':task,
                'source_sha256':{n:digest(base/n) for n in context['sources']},'training_ids':examples,
                'payload_sha256':digest(out/(jobid+'-payload.json'))})
    # Alternate which arm goes first across fixtures to reduce fixed-order bias.
    jobs=sorted(jobs,key=lambda j:(list(CASES).index(j['fixture']),j['arm']!=('zero_shot' if list(CASES).index(j['fixture'])%2==0 else 'few_shot')))
    save(out/'payload-freeze.json',{'utc':datetime.now(timezone.utc).isoformat(),'jobs':jobs,'policy_sha256':digest(out/'frozen-policy.json')})
    load_env_file(ROOT/'.env');model=await catalog();save(out/'model-pricing.json',model)
    rate=model['pricing'];bound=8*(Decimal(str(rate['prompt']))*model['context_length']+Decimal(str(rate['completion']))*2048+Decimal(str(rate.get('request','0'))))
    if bound>Decimal('0.22'):raise ValueError('Cost exceeds announced cap; stop')
    save(out/'cost-gate.json',{'bounded_inference_usd':str(bound),'sandbox_usd':0,'sandbox_basis':'User confirmed free beta access','training':False,'max_calls':8})
    staging=out/'staging';staging.mkdir()
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    for name,case in CASES.items():
        task=tasks[name];cal=out/'calibration'/name;cal.mkdir(parents=True)
        negative=cal/'baseline';negative.mkdir();positive=cal/'reference';positive.mkdir()
        async with NebiusSandboxBackend(temporary_parent=staging) as box:
            await box.upload_project(task.workspace,task.source_files+task.support_files)
            b=await CCompiler().compile(task,box);save(negative/'build.json',b.model_dump())
            if not b.success:raise ValueError('Baseline compilation failed: '+name)
            baseline=await JournalCampaign(negative).run(task,box,runs=3)
            if case['family']=='liveness':
                if baseline.counts.get('TIMEOUT')!=3:raise ValueError('Liveness negative control failed')
            else:
                tsan=instrumented_task(task)
                b=await CCompiler().compile(tsan,box,SanitizerConfig(enabled=True,required=True).flags)
                save(negative/'tsan-build.json',b.model_dump())
                if not b.success:raise ValueError('TSan unavailable')
                raceout=negative/'tsan';raceout.mkdir()
                races=await JournalCampaign(raceout).run(tsan,box,runs=3)
                if races.counts.get('RACE_DETECTED')!=3:raise ValueError('Race negative control failed')
            source=case['source'];reference=source.replace(case['old'],case['new'])
            patch=''.join(difflib.unified_diff(source.splitlines(True),reference.splitlines(True),fromfile='a/solution.c',tofile='b/solution.c'))
            (positive/'reference.patch').write_text(patch,encoding='utf-8')
            applied=await box.apply_patch(patch,task.source_files)
            if not applied.success:raise ValueError('Reference patch rejected')
            for n in task.support_files:
                if (await box.read_file(n)).encode()!=(task.workspace/n).read_bytes():raise ValueError('Oracle changed')
            print('Reference calibration: '+name,flush=True)
            v=await ConcurrencyVerifier(campaigns=JournalCampaign(positive)).verify_workspace(task,box,baseline)
            save(positive/'verification.json',v.model_dump(mode='json'))
            require_verified(v.model_dump(mode='json'),task.verification_config.model_dump())
    check_hashes(protected)
    save(out/'plan.json',{'jobs':jobs,'model':MODEL,'max_model_calls':8,'attempts_per_job':1,'max_output_tokens':2048,
        'temperature':0,'model_retries':0,'correction_calls':0,'mandatory_verifier':True,'training':False,
        'image':'agentkernel-clang:20261003122908','max_pilot_spend_usd':10,'inference_bound_usd':str(bound),
        'input_reservation_tokens_per_call':model['context_length'],'sandbox_bound_usd':0,
        'controller_sha256':digest(ROOT/'scripts/prompting_generalization.py')})
    protected.update({p.relative_to(ROOT).as_posix():digest(p) for p in out.rglob('*') if p.is_file() and 'staging' not in p.parts})
    save(out/'preserved-sha256.json',protected)
    print('READY: '+str(out/'plan.json'),flush=True)

if __name__=='__main__':asyncio.run(main())
