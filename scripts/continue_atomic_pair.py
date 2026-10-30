"""One compiler-feedback correction of incomplete model variants; frozen prior evidence."""
import asyncio
from datetime import datetime,timezone
from decimal import Decimal
import json
import os
from statistics import median
from time import perf_counter
import httpx
from atomic_pair_experiment import ROOT,read,save,digest,check_hashes,catalog,MODEL,BASE,load_env_file
from atomic_pair_experiment import NebiusSandboxBackend,ConcurrencyTask,VerificationConfig,SemanticCheck,ConcurrencyVerifier,JournalCampaign,require_verified

PRIOR=ROOT/'reports/atomic-pair-experiment/20261011T115849Z'


async def main():
    check_hashes(read(PRIOR/'preserved-sha256.json'))
    out=ROOT/'reports/atomic-pair-continuation'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False);print('Evidence: '+str(out),flush=True)
    protected={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','datasets','scripts','tests')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json',protected)
    load_env_file(ROOT/'.env');os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    staging=out/'staging';staging.mkdir();feedback={};results={};timings=[];usage_record={}
    names=['mutex','exchange','store'];started=perf_counter()
    try:
        async with NebiusSandboxBackend(temporary_parent=staging) as box:
            for mode,name in enumerate(names[1:],1):
                folder=out/name;folder.mkdir()
                await box.upload_project(PRIOR/name,['pair.c','pair.h','harness.c'])
                built=await box.run_command(['gcc','-std=c11','-pthread','-O1',f'-DMODE={mode}','harness.c','pair.c','-o','app'],timeout=30)
                save(folder/'initial-compile.json',built.model_dump())
                if built.exit_code==0:raise ValueError('Unexpected successful incomplete variant')
                feedback[name]={'command':built.command,'exit_code':built.exit_code,'stderr':built.stderr}
            payload=read(PRIOR/'payload.json')
            previous_response=read(PRIOR/'response.json')['choices'][0]['message']['content']
            payload['messages'] += [{'role':'assistant','content':previous_response},{'role':'user','content':
                'Both variants failed actual compilation/linking. This is your only correction call. Return COMPLETE source for BOTH variants in exchange_source and store_source. Each string MUST implement BOTH set_pair AND get_pair. The reader is missing, not supplied by the harness. Decode both signed 32-bit values from exactly one acquire atomic load of pair_bits. Retain the requested publication operation and all previous restrictions. Do not only describe the missing function. Actual compiler diagnostics: '+json.dumps(feedback)}]
            save(out/'payload.json',payload);live=await catalog();save(out/'model-pricing.json',live)
            rate=live['pricing'];bound=Decimal(str(rate['prompt']))*live['context_length']+Decimal(str(rate['completion']))*4096+Decimal(str(rate.get('request','0')))
            if bound>Decimal('0.03'):raise ValueError('Correction cost exceeds $0.03')
            save(out/'plan.json',{'max_correction_calls':1,'output_cap':4096,'bound_usd':str(bound),'prior':str(PRIOR),
                'unchanged_verification':'100 stress + original tests + semantics + 3 TSan per variant',
                'timing':'Same frozen harness, same 10-round interleaved timing plan; mutex verification reused from original evidence.',
                'source_changes':'Model correction only for atomic variants; no assistant edits to model C source.'})
            save(out/'call-started.json',{'max_calls':1})
            tick=perf_counter()
            async with httpx.AsyncClient(timeout=120) as client:
                response=await client.post(BASE+'/chat/completions',json=payload,headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
                response.raise_for_status();data=response.json();save(out/'response.json',data)
            inp=data['usage']['prompt_tokens'];completion=data['usage']['completion_tokens']
            usage_record={'calls':1,'input_tokens':inp,'output_tokens':completion,'tokens':inp+completion,'inference_ms':(perf_counter()-tick)*1000,
                'cost_usd':float(Decimal(inp)*Decimal(str(rate['prompt']))+Decimal(completion)*Decimal(str(rate['completion'])))}
            if inp>live['context_length'] or completion>4096 or data['choices'][0]['finish_reason']!='stop':raise ValueError('Invalid token/output completion')
            sources=json.loads(data['choices'][0]['message']['content'])
            if set(sources)!={'exchange_source','store_source'}:raise ValueError('Wrong response schema')
            (out/'mutex').mkdir()
            for mode,name in enumerate(names):
                folder=out/name
                for n in ('pair.h','harness.c'):(folder/n).write_bytes((PRIOR/name/n).read_bytes())
                source=(PRIOR/'mutex/pair.c').read_text() if mode==0 else sources[name+'_source']
                if not isinstance(source,str) or len(source)>50000:raise ValueError('Invalid source')
                (folder/'pair.c').write_text(source,encoding='utf-8',newline='\n')
                await box.upload_project(folder,['pair.c','pair.h','harness.c'])
                build=['gcc','-std=c11','-pthread','-O1','-g',f'-DMODE={mode}','harness.c','pair.c','-o','app']
                task=ConcurrencyTask(task_id='atomic_'+name,workspace=folder,source_files=['pair.c'],support_files=['pair.h','harness.c'],build_command=build,
                    run_command=['./app'],stress_runs=3,max_runtime_seconds=2,
                    verification_config=VerificationConfig(stress_runs=100,required_original_tests=True,original_test_commands=[['./app']],
                        sanitizer_enabled=True,sanitizer_required=True,sanitizer_runs=3,sanitizer_compiler='clang',
                        semantic_checks=[SemanticCheck(name='Paired-value and completion invariants',build_command=build[:-1]+['semantic'],run_command=['./semantic'])]))
                save(folder/'task.json',task.model_dump(mode='json'))
                if mode==0:
                    v=read(PRIOR/'mutex/verification.json');require_verified(v,task.verification_config.model_dump())
                    results[name]={'verified':True,'verification_evidence':str(PRIOR/'mutex/verification.json')}
                else:
                    print('Verify corrected '+name,flush=True)
                    v=await ConcurrencyVerifier(campaigns=JournalCampaign(folder)).verify_workspace(task,box)
                    save(folder/'verification.json',v.model_dump(mode='json'));require_verified(v.model_dump(mode='json'),task.verification_config.model_dump())
                    results[name]={'verified':True,'verification_ms':v.duration_ms}
                for n in ('pair.c','pair.h','harness.c'):
                    if (await box.read_file(n)).encode()!=(folder/n).read_bytes():raise ValueError('Source changed')
                fast=await box.run_command(['gcc','-std=c11','-pthread','-O3',f'-DMODE={mode}','harness.c','pair.c','-o','bench_'+name],timeout=30)
                save(folder/'performance-build.json',fast.model_dump())
                if fast.exit_code!=0 or fast.timed_out:raise ValueError('Performance build failed')
            for name in names:
                warm=await box.run_command(['./bench_'+name,'bench'],timeout=10);save(out/name/'warmup.json',warm.model_dump())
                if warm.exit_code!=0 or warm.timed_out:raise ValueError('Warmup failed')
            for i in range(10):
                for name in names[i%3:]+names[:i%3]:
                    run=await box.run_command(['./bench_'+name,'bench'],timeout=10);save(out/name/f'timing-{i+1}.json',run.model_dump())
                    if run.exit_code!=0 or run.timed_out:raise ValueError('Timing failed')
                    values=json.loads(run.stdout);values.update(variant=name,round=i+1);timings.append(values)
                print('Timing round '+str(i+1)+'/10',flush=True)
            for name in names:
                rows=[r for r in timings if r['variant']==name]
                results[name]['samples']=len(rows)
                results[name]['lock_free']=all(r['lock_free']==1 for r in rows) if name!='mutex' else None
                results[name]['timing_summary']={k:{'median':median(r[k] for r in rows),'min':min(r[k] for r in rows),'max':max(r[k] for r in rows)}
                    for k in ('single_ns_per_op','writer_ns_per_op','reader_ns_per_op','concurrent_wall_ns_per_op')}
    finally:
        save(out/'results.json',{'correction_model':usage_record,'variants':results,'timings':timings,'duration_ms':(perf_counter()-started)*1000})
        check_hashes(protected);save(out/'integrity.json',{'unchanged':True})


if __name__=='__main__':asyncio.run(main())
