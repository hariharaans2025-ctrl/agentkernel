"""Calibrate frozen synthetic tasks and private reference repairs remotely only."""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter
from agentkernel.config import load_env_file
from agentkernel.repository.learning import require_verified
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.concurrency.instrumentation.sanitizer import instrumented_task, SanitizerConfig
from verify_saved_super_candidate import JournalCampaign

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/adaptive-v3/product-v1'


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)


def verify_hashes(folder,expected):
    for filename,digest in expected.items():
        if hashlib.sha256((folder/filename).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen source changed: '+filename)


async def calibrate(case,out,slots):
    async with slots:
        started=perf_counter();name=case['id'];folder=out/name;folder.mkdir()
        directory=DATA/'tasks'/name
        task=ConcurrencyTask.model_validate({**json.loads((directory/'task.json').read_text()),'workspace':directory})
        verify_hashes(directory,{**case['source_sha256'],**case['support_sha256']})
        verify_hashes(DATA/'references'/name,case['reference_sha256'])
        campaign=JournalCampaign(folder)
        print('CALIBRATING',name,case['split'],flush=True)
        async with NebiusSandboxBackend(temporary_parent=folder) as box:
            await box.upload_project(directory,task.source_files+task.support_files)
            build=await CCompiler().compile(task,box);save(folder/'original-build.json',build.model_dump(mode='json'))
            if not build.success:raise ValueError(name+': original does not compile')
            negative=await campaign.run(task,box,runs=3);save(folder/'original-stress.json',negative.model_dump(mode='json'))
            if negative.infrastructure_failures:raise ValueError(name+': original infrastructure unavailable')
            tsan_task=instrumented_task(task);tsan_task.build_command[0]='clang'
            tsan_build=await CCompiler().compile(tsan_task,box,SanitizerConfig().flags)
            save(folder/'original-tsan-build.json',tsan_build.model_dump(mode='json'))
            if not tsan_build.success:raise ValueError(name+': negative TSan build unavailable')
            tsan=await campaign.run(tsan_task,box,runs=3);save(folder/'original-tsan.json',tsan.model_dump(mode='json'))
            if tsan.infrastructure_failures:raise ValueError(name+': negative TSan infrastructure unavailable')
            if case['negative_control']=='race':
                broken=any(r.sanitizer_detected for r in tsan.runs)
            else:broken=negative.failed_runs==3 and tsan.failed_runs==3
            if not broken:raise ValueError(name+': broken control was not detected')
        reference=folder/'reference';reference.mkdir()
        for filename in task.source_files:(reference/filename).write_bytes((DATA/'references'/name/filename).read_bytes())
        for filename in task.support_files:(reference/filename).write_bytes((directory/filename).read_bytes())
        ref_task=task.model_copy(update={'workspace':reference})
        async with NebiusSandboxBackend(temporary_parent=folder) as box:
            await box.upload_project(reference,task.source_files+task.support_files)
            verified=await ConcurrencyVerifier(campaigns=campaign).verify_workspace(ref_task,box)
            save(folder/'reference-verification.json',verified.model_dump(mode='json'))
            require_verified(verified.model_dump(mode='json'),task.verification_config.model_dump())
        verify_hashes(directory,{**case['source_sha256'],**case['support_sha256']})
        result={'case':name,'split':case['split'],'family':case['family'],'broken_rejected':True,'reference_verified':True,
            'stress_passed':verified.passed_runs,'stress_total':verified.total_runs,'tsan_passed':verified.sanitizer_passed,
            'semantic_passed':verified.semantic_passed,'original_tests_passed':verified.evidence['original_tests']['passed'],
            'baseline_failed_runs':negative.failed_runs,'baseline_tsan_failed_runs':tsan.failed_runs,
            'reference_source_sha256':case['reference_sha256'],'source_sha256':case['source_sha256'],'support_sha256':case['support_sha256'],
            'model_calls':0,'elapsed_seconds':perf_counter()-started}
        save(folder/'calibration.json',result)
        print('VERIFIED',name,round(result['elapsed_seconds'],1),flush=True)
        return result


async def main(args):
    load_env_file(ROOT/'.env');os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    out=ROOT/'reports/adaptive-v3'/('product-calibration-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True,exist_ok=False);manifest=json.loads((DATA/'manifest.json').read_text())
    chosen=[c for c in manifest['cases'] if not args.ids or c['id'] in args.ids]
    save(out/'plan.json',{'manifest_sha256':hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest(),
        'dataset':str(DATA.relative_to(ROOT)),'cases':[c['id'] for c in chosen],'model_calls':0,'policy':'No local C execution; no retries; protected references excluded from runtime context.'})
    slots=asyncio.Semaphore(args.parallel)
    async def guarded(case):
        try:return await calibrate(case,out,slots)
        except Exception as e:
            result={'case':case['id'],'split':case['split'],'reference_verified':False,'broken_rejected':False,
                'error_type':type(e).__name__,'error':str(e),'model_calls':0}
            save(out/(case['id']+'-failure.json'),result)
            print('FAILED',case['id'],type(e).__name__,str(e),flush=True)
            return result
    records=await asyncio.gather(*(guarded(c) for c in chosen))
    ready={'cases':records,'model_calls':0,'origin':'Manual verifier calibration, not model repair results',
        'test_targets_in_training':False,'complete':all(r['reference_verified'] for r in records)}
    save(out/'ready.json',ready)
    print('CALIBRATION_REPORT',out,flush=True)
    if not ready['complete']:raise SystemExit(2)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--parallel',type=int,default=3);p.add_argument('--ids',nargs='*');p.add_argument('--data',type=Path,default=DATA)
    args=p.parse_args();DATA=args.data.resolve();asyncio.run(main(args))
