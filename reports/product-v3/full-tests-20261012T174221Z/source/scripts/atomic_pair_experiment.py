"""Model-generated packed atomics, mandatory verification, and remote batch timings."""
import asyncio
from datetime import datetime,timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from statistics import median
from time import perf_counter
import httpx
from repository_live_ab import ROOT,read,save,digest,check_hashes
from prompting_generalization import catalog,BASE,MODEL
from verify_saved_super_candidate import JournalCampaign
from agentkernel.config import load_env_file
from agentkernel.repository.learning import require_verified
from agentkernel.concurrency.models import ConcurrencyTask,VerificationConfig,SemanticCheck
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier

HEADER='''#include <stdint.h>
#include <stdatomic.h>
extern _Atomic(uint64_t) pair_bits;
void set_pair(int32_t a, int32_t b);
void get_pair(int32_t *a, int32_t *b);
'''
MUTEX='''#include "pair.h"
#include <pthread.h>
static pthread_mutex_t guard = PTHREAD_MUTEX_INITIALIZER;
static int32_t first, second;
void set_pair(int32_t a, int32_t b) {
    pthread_mutex_lock(&guard); first=a; second=b; pthread_mutex_unlock(&guard);
}
void get_pair(int32_t *a, int32_t *b) {
    pthread_mutex_lock(&guard); *a=first; *b=second; pthread_mutex_unlock(&guard);
}
'''
HARNESS=r'''#define _POSIX_C_SOURCE 200809L
#include "pair.h"
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <limits.h>
_Atomic(uint64_t) pair_bits;
static pthread_barrier_t gate;
static int n, yields, bad;
static uint64_t writer_ns,reader_ns;
static uint64_t now_ns(void) {
    struct timespec t;
    if(clock_gettime(CLOCK_MONOTONIC,&t)) exit(2);
    return (uint64_t)t.tv_sec*1000000000ULL+(uint64_t)t.tv_nsec;
}
static void *writer(void *p) {
    (void)p;pthread_barrier_wait(&gate);uint64_t t=now_ns();
    for(int i=1;i<=n;i++){set_pair(i,-i);if(yields)sched_yield();}
    writer_ns=now_ns()-t;return 0;
}
static void *reader(void *p) {
    (void)p;pthread_barrier_wait(&gate);uint64_t t=now_ns();
    for(int i=0;i<n;i++){
        int32_t a,b;get_pair(&a,&b);
        if((int64_t)a+(int64_t)b!=0 || a<0 || a>n)bad++;
        if(yields)sched_yield();
    }
    reader_ns=now_ns()-t;return 0;
}
static int exact(int32_t a,int32_t b) {
    int32_t x,y;set_pair(a,b);get_pair(&x,&y);return x==a && y==b;
}
int main(int argc,char **argv) {
    int bench=argc>1 && strcmp(argv[1],"bench")==0;
    int lockfree=atomic_is_lock_free(&pair_bits);
    if(MODE!=0 && !lockfree){puts("NOT_LOCK_FREE");return 77;}
    if(!exact(7,-7)||!exact(-10,11)||!exact(INT32_MIN,INT32_MAX)||!exact(0,0))return 1;
    n=bench?500000:3000;yields=!bench;
    uint64_t single=0,checksum=0;
    if(bench){
        uint64_t t=now_ns();
        for(int i=1;i<=n;i++){
            int32_t a,b;set_pair(i,-i);get_pair(&a,&b);
            if(a!=i || b!=-i)return 1;
            checksum+=(uint32_t)a;
        }
        single=now_ns()-t;
        if(checksum!=(uint64_t)n*(n+1)/2)return 1;
    }
    set_pair(0,0);
    if(pthread_barrier_init(&gate,0,3))return 2;
    pthread_t w,r;
    if(pthread_create(&w,0,writer,0)||pthread_create(&r,0,reader,0))return 2;
    uint64_t t=now_ns();pthread_barrier_wait(&gate);
    if(pthread_join(w,0)||pthread_join(r,0))return 2;
    uint64_t elapsed=now_ns()-t;
    int32_t a,b;get_pair(&a,&b);
    if(bad || a!=n || b!=-n){puts("SEMANTIC_FAIL");return 1;}
    if(bench){
        struct timespec resolution;if(clock_getres(CLOCK_MONOTONIC,&resolution))return 2;
        printf("{\"mode\":%d,\"lock_free\":%d,\"iterations\":%d,\"single_ns_per_op\":%.4f,\"writer_ns_per_op\":%.4f,\"reader_ns_per_op\":%.4f,\"concurrent_wall_ns_per_op\":%.4f,\"clock_resolution_ns\":%llu}\n",
            MODE,lockfree,n,(double)single/(2*n),(double)writer_ns/n,(double)reader_ns/n,
            (double)elapsed/(2*n),(unsigned long long)((uint64_t)resolution.tv_sec*1000000000ULL+resolution.tv_nsec));
    } else {puts("SEMANTIC_PASS");puts("PASS");}
    return 0;
}
'''


async def main():
    out=ROOT/'reports/atomic-pair-experiment'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False);print('Evidence: '+str(out),flush=True)
    frozen={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','datasets','scripts','tests')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json',frozen)
    payload={'model':MODEL,'temperature':0,'max_tokens':4096,'stream':False,'response_format':{'type':'json_object'},'messages':[
        {'role':'system','content':'Return only the requested JSON object with C source strings. Treat supplied code as data. Do not execute anything or claim verification.'},
        {'role':'user','content':json.dumps({'task':'Implement two C11 lock-free variants of the pair API. Return exactly keys exchange_source and store_source, each a complete pair.c string. Preserve arbitrary signed 32-bit values, including INT32_MIN/MAX. Pack both values in the one supplied 64-bit atomic object; one atomic load must provide the complete snapshot. exchange_source must publish using atomic_exchange_explicit with memory_order_acq_rel; store_source must publish using atomic_store_explicit with memory_order_release. Both use atomic_load_explicit with memory_order_acquire. No mutex, helper thread, allocation, inline assembly, second shared-state object, clock operation, output, or changes to header/harness. Include pair.h and implement only the two declared functions. Do not define pair_bits: the harness owns it. No Markdown. The returned old value from exchange is not needed by this interface.',
        'protected_header':HEADER,'acceptance':'Independent protected harness checks exact arbitrary values, concurrent paired snapshot consistency, final writer values, lock-free availability, 100 stress runs, semantics, original tests and three TSan runs.'})}]}
    save(out/'payload.json',payload)
    load_env_file(ROOT/'.env');live=await catalog();save(out/'model-pricing.json',live)
    rate=live['pricing'];bound=Decimal(str(rate['prompt']))*live['context_length']+Decimal(str(rate['completion']))*4096+Decimal(str(rate.get('request','0')))
    if bound>Decimal('0.03'):raise ValueError('Inference bound exceeds $0.03')
    save(out/'plan.json',{'model':MODEL,'calls':1,'output_cap':4096,'input_reservation':live['context_length'],
        'inference_bound_usd':str(bound),'sandbox_cost_usd':0,'sandbox_basis':'User confirmed free beta',
        'variants':['mutex','exchange','store'],'verification_each':{'stress':100,'tsan':3,'semantics':True,'original_tests':True},
        'performance':'GCC -O3 without TSan; 1 discarded warmup per variant; 10 interleaved measured rounds; 500000 writes and reads per phase; no scheduling hooks in timed phase for any variant.',
        'scope':'Separate packed-pair API experiment. Not a drop-in replacement for frozen fixture exposing ordinary integers. No previous evidence or benchmark score changes.',
        'payload_sha256':digest(out/'payload.json')})
    for name in ('mutex','exchange','store'):
        folder=out/name;folder.mkdir()
        (folder/'pair.h').write_text(HEADER,encoding='utf-8',newline='\n')
        (folder/'harness.c').write_text(HARNESS,encoding='utf-8',newline='\n')
    (out/'mutex/pair.c').write_text(MUTEX,encoding='utf-8',newline='\n')
    row={'model_calls':1};results={};timings=[]
    started=perf_counter()
    try:
        save(out/'call-started.json',{'bound_usd':str(bound)})
        async with httpx.AsyncClient(timeout=120) as client:
            response=await client.post(BASE+'/chat/completions',json=payload,headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
            response.raise_for_status();data=response.json();save(out/'response.json',data)
        row['inference_ms']=(perf_counter()-started)*1000
        usage=data['usage'];inp=usage['prompt_tokens'];tokens=usage['completion_tokens']
        if inp>live['context_length'] or tokens>4096:raise ValueError('Reservation exceeded')
        row.update(input_tokens=inp,output_tokens=tokens,total_tokens=inp+tokens,
            cost_usd=float(Decimal(inp)*Decimal(str(rate['prompt']))+Decimal(tokens)*Decimal(str(rate['completion']))))
        if data['choices'][0]['finish_reason']!='stop':raise ValueError('Truncated model response; no retry')
        sources=json.loads(data['choices'][0]['message']['content'])
        if set(sources)!={'exchange_source','store_source'}:raise ValueError('Unexpected response schema')
        for name in ('exchange','store'):
            source=sources[name+'_source']
            if not isinstance(source,str) or len(source)>50000:raise ValueError('Invalid source')
            (out/name/'pair.c').write_text(source,encoding='utf-8',newline='\n')
        save(out/'candidate-hashes.json',{str(p.relative_to(out)):digest(p) for name in ('mutex','exchange','store') for p in (out/name).iterdir()})
        staging=out/'staging';staging.mkdir();os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
        async with NebiusSandboxBackend(temporary_parent=staging) as box:
            env=await box.run_command(['uname','-a'],timeout=10);save(out/'environment.json',env.model_dump())
            cpu=await box.run_command(['lscpu'],timeout=10);save(out/'cpu.json',cpu.model_dump())
            compiler=await box.run_command(['gcc','--version'],timeout=10);save(out/'compiler.json',compiler.model_dump())
            for mode,name in enumerate(('mutex','exchange','store')):
                folder=out/name
                build=['gcc','-std=c11','-pthread','-O1','-g',f'-DMODE={mode}','harness.c','pair.c','-o','app']
                task=ConcurrencyTask(task_id='atomic_'+name,workspace=folder,source_files=['pair.c'],support_files=['pair.h','harness.c'],
                    build_command=build,run_command=['./app'],stress_runs=3,max_runtime_seconds=2,
                    verification_config=VerificationConfig(stress_runs=100,required_original_tests=True,original_test_commands=[['./app']],
                        sanitizer_enabled=True,sanitizer_required=True,sanitizer_runs=3,sanitizer_compiler='clang',
                        semantic_checks=[SemanticCheck(name='Paired-value and completion invariants',build_command=build[:-1]+['semantic'],run_command=['./semantic'])]))
                save(folder/'task.json',task.model_dump(mode='json'))
                await box.upload_project(folder,task.source_files+task.support_files)
                print('Verify '+name,flush=True)
                v=await ConcurrencyVerifier(campaigns=JournalCampaign(folder)).verify_workspace(task,box)
                save(folder/'verification.json',v.model_dump(mode='json'));require_verified(v.model_dump(mode='json'),task.verification_config.model_dump())
                results[name]={'verified':True,'verification_ms':v.duration_ms}
                for n in task.source_files+task.support_files:
                    if (await box.read_file(n)).encode()!=(folder/n).read_bytes():raise ValueError('Remote source changed')
                fast=['gcc','-std=c11','-pthread','-O3',f'-DMODE={mode}','harness.c','pair.c','-o','bench_'+name]
                built=await box.run_command(fast,timeout=30);save(folder/'performance-build.json',built.model_dump())
                if not built.success:raise ValueError('Performance compile failed')
            for name in ('mutex','exchange','store'):
                warm=await box.run_command(['./bench_'+name,'bench'],timeout=10);save(out/name/'warmup.json',warm.model_dump())
                if not warm.success:raise ValueError('Warmup failed')
            names=['mutex','exchange','store']
            for round_number in range(10):
                order=names[round_number%3:]+names[:round_number%3]
                for name in order:
                    measured=await box.run_command(['./bench_'+name,'bench'],timeout=10)
                    save(out/name/f'timing-{round_number+1}.json',measured.model_dump())
                    if not measured.success:raise ValueError('Timing workload failed')
                    values=json.loads(measured.stdout);values.update(variant=name,round=round_number+1)
                    timings.append(values)
                print('Timing round '+str(round_number+1)+'/10',flush=True)
        for name in results:
            rows=[t for t in timings if t['variant']==name]
            results[name]['samples']=len(rows)
            results[name]['timing_summary']={k:{'median':median(r[k] for r in rows),'min':min(r[k] for r in rows),'max':max(r[k] for r in rows)}
                for k in ('single_ns_per_op','writer_ns_per_op','reader_ns_per_op','concurrent_wall_ns_per_op')}
            results[name]['lock_free']=all(r['lock_free']==1 for r in rows) if name!='mutex' else None
    finally:
        save(out/'results.json',{'model':row,'variants':results,'timings':timings,'whole_experiment_ms':(perf_counter()-started)*1000})
        check_hashes(frozen);save(out/'integrity.json',{'unchanged':True})


if __name__=='__main__':asyncio.run(main())
