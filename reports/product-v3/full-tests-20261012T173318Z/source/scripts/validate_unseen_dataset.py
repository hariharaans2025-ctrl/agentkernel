"""Freeze new holdout inputs and verify references without target-model exposure."""
import asyncio
from datetime import datetime,timezone
import difflib
import json
import os
from repository_live_ab import ROOT,read,save,digest
from verify_saved_super_candidate import JournalCampaign
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask,VerificationConfig,SemanticCheck
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.concurrency.instrumentation.sanitizer import SanitizerConfig,instrumented_task


async def main():
    out=ROOT/'reports/unseen-dataset-validation'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    print('Evidence: '+str(out),flush=True)
    staging=out/'staging';staging.mkdir()
    dataset=ROOT/'datasets/unseen-v1'
    before={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','datasets','reports','scripts')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json',before)
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-project:20261004t054834z'
    async with NebiusSandboxBackend(temporary_parent=staging) as box:
        await box.upload_project(ROOT,['src/agentkernel/repository/__init__.py','src/agentkernel/repository/learning.py','tests/test_learning.py'])
        tests=await box.run_command(['python3','-m','pytest','-q','tests/test_learning.py'],timeout=60,environment={'PYTHONPATH':'/workspace/src'})
        save(out/'tests.json',tests.model_dump());print(tests.stdout,flush=True)
        if tests.exit_code!=0: raise ValueError('Learning gates failed')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    records=[]
    try:
        for name,old,new in [('rwlock_mode','pthread_rwlock_rdlock','pthread_rwlock_wrlock'),
                             ('wake_all','pthread_cond_signal(&available)','pthread_cond_broadcast(&available)')]:
            case=out/name;case.mkdir();negative=case/'baseline';negative.mkdir();positive=case/'reference';positive.mkdir()
            build=['gcc','-pthread','-g','-O1','oracle.c','solution.c','-o','app']
            task=ConcurrencyTask(task_id=name,workspace=dataset/name,source_files=['solution.c'],support_files=['oracle.c','state.h'],
                build_command=build,run_command=['./app'],stress_runs=3,max_runtime_seconds=2,
                verification_config=VerificationConfig(stress_runs=100,required_original_tests=True,original_test_commands=[['./app']],
                    sanitizer_enabled=True,sanitizer_required=True,sanitizer_runs=3,sanitizer_compiler='clang',
                    semantic_checks=[SemanticCheck(name='Protected completion/value invariant',build_command=build[:-1]+['semantic'],run_command=['./semantic'])]))
            save(case/'task.json',task.model_dump(mode='json'))
            source=(task.workspace/'solution.c').read_text();assert source.count(old)==1
            reference=source.replace(old,new)
            patch=''.join(difflib.unified_diff(source.splitlines(True),reference.splitlines(True),fromfile='a/solution.c',tofile='b/solution.c'))
            (positive/'reference.patch').write_text(patch)
            async with NebiusSandboxBackend(temporary_parent=staging) as box:
                await box.upload_project(task.workspace,task.source_files+task.support_files)
                compiled=await CCompiler().compile(task,box);save(negative/'build.json',compiled.model_dump())
                if not compiled.success: raise ValueError('Baseline build failed')
                recorder=JournalCampaign(negative);baseline=await recorder.run(task,box,runs=3)
                if name=='wake_all' and baseline.counts.get('TIMEOUT')!=3: raise ValueError('Holdout fault not reproducible')
                if name=='rwlock_mode':
                    tsan=instrumented_task(task)
                    b=await CCompiler().compile(tsan,box,SanitizerConfig(enabled=True,required=True).flags)
                    save(negative/'tsan-build.json',b.model_dump())
                    if not b.success: raise ValueError('TSan unavailable')
                    races=await recorder.run(tsan,box,runs=3)
                    if races.counts.get('RACE_DETECTED')!=3: raise ValueError('Race negative control failed')
                applied=await box.apply_patch(patch,task.source_files);save(positive/'application.json',applied.model_dump())
                if not applied.success or await box.read_file('solution.c')!=reference: raise ValueError('Reference mismatch')
                for n in task.support_files:
                    if (await box.read_file(n)).encode()!=(task.workspace/n).read_bytes(): raise ValueError('Oracle changed')
                print('Verifying held-out reference: '+name,flush=True)
                v=await ConcurrencyVerifier(campaigns=JournalCampaign(positive)).verify_workspace(task,box,baseline)
                save(positive/'verification.json',v.model_dump(mode='json'))
                records.append({'id':name,'verified_reference':v.passed,'stress':v.passed_runs,'tsan':v.sanitizer_passed})
                if not v.passed: raise ValueError('Reference not verified')
        save(out/'ready.json',{'cases':records,'target_model_calls':0,'unseen_scope':'New programs not used in this project training or prior target-model calls; base-model pretraining exposure cannot be proven.',
            'references':'Reference answers remain outside train/validation and model prompts. Test set is never a training validation_file.',
            'mandatory_verifier':True})
    finally:
        changed=[n for n,h in before.items() if digest(ROOT/n)!=h]
        save(out/'integrity.json',{'unchanged':not changed,'changed':changed})
        if changed: raise ValueError('Protected evidence changed')
    print(out/'ready.json',flush=True)


if __name__=='__main__':asyncio.run(main())
