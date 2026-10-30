"""Expand synthetic validation coverage without model calls or benchmark edits."""
import asyncio
from datetime import datetime, timezone
import os

from repository_live_ab import ROOT, read, save, digest
from verify_saved_super_candidate import JournalCampaign
from agentkernel.config import load_env_file
from agentkernel.repository.diagnostics import diagnose
from agentkernel.concurrency.models import ConcurrencyTask, VerificationConfig, SemanticCheck
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.instrumentation.sanitizer import SanitizerConfig, instrumented_task
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier


async def main():
    out=ROOT/'reports/additional-concurrency-controls'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    print('Evidence: '+str(out),flush=True)
    protected={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','scripts')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json',protected)
    save(out/'plan.json',{'model_calls':0,'tokens':0,'cases':['lost_signal','missing_sync','account_inversion'],
        'faulty_diagnostic_runs_per_case':3,'faulty_missing_sync_tsan_runs':3,
        'positive_control_stress_runs':100,'positive_control_tsan_runs':3,
        'image':'agentkernel-clang:20261003122908','origin':'Manually authored synthetic controls, not model repairs',
        'policy':'No automatic workload retries; all native execution in Nebius Sandbox.'})
    staging=out/'staging'; staging.mkdir()
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    records=[]
    try:
        async with asyncio.timeout(1800):
            for name in ('lost_signal','missing_sync','account_inversion'):
                case=out/name; case.mkdir()
                negative=case/'faulty'; negative.mkdir()
                positive=case/'repaired'; positive.mkdir()
                task=ConcurrencyTask(task_id=name,workspace=ROOT/'examples/concurrency-validation',source_files=[name+'.c'],
                    build_command=['gcc','-pthread','-g','-O1',name+'.c','-o','app'],binary_path='app',
                    run_command=['./app'],max_runtime_seconds=2,stress_runs=3,
                    verification_config=VerificationConfig(stress_runs=100,required_original_tests=True,
                        original_test_commands=[['./app']],sanitizer_enabled=True,sanitizer_required=True,
                        sanitizer_runs=3,sanitizer_compiler='clang'))
                save(case/'faulty-task.json',task.model_dump(mode='json'))
                print('Checking faulty control: '+name,flush=True)
                async with NebiusSandboxBackend(temporary_parent=staging) as box:
                    await box.upload_project(task.workspace,task.source_files)
                    build=await CCompiler().compile(task,box)
                    save(negative/'build.json',build.model_dump())
                    if not build.success: raise RuntimeError('Faulty control build failed')
                    recorder=JournalCampaign(negative)
                    baseline=await recorder.run(task,box,runs=3)
                    diagnoses=[diagnose(r.model_dump()) for r in baseline.runs]
                    save(negative/'diagnoses.json',diagnoses)
                    if baseline.infrastructure_failures: raise RuntimeError('Baseline infrastructure failure')
                    if name=='lost_signal' and any(d['kind']!='timeout_unexplained' for d in diagnoses):
                        raise RuntimeError('Lost-signal control did not reproduce expected timeout')
                    if name=='account_inversion' and any(d['kind']!='deadlock_supported_by_wait_cycle' for d in diagnoses):
                        raise RuntimeError('Account wait-cycle evidence missing')
                    if name=='missing_sync':
                        tsan=instrumented_task(task)
                        tsan_build=await CCompiler().compile(tsan,box,SanitizerConfig(enabled=True,required=True).flags)
                        save(negative/'tsan-build.json',tsan_build.model_dump())
                        if not tsan_build.success: raise RuntimeError('Negative TSan build failed')
                        race=await recorder.run(tsan,box,runs=3)
                        if race.counts.get('RACE_DETECTED')!=3: raise RuntimeError('Negative TSan gate failed')
                    fixed=task.model_copy(deep=True)
                    fixed.build_command=['gcc','-pthread','-g','-O1','-DREPAIRED',name+'.c','-o','app']
                    fixed.verification_config.semantic_checks=[SemanticCheck(name='Required workload invariant',
                        build_command=['gcc','-pthread','-g','-O1','-DREPAIRED',name+'.c','-o','semantic'],run_command=['./semantic'])]
                    save(case/'repaired-task.json',fixed.model_dump(mode='json'))
                    print('Full positive-control verification: '+name,flush=True)
                    result=await ConcurrencyVerifier(campaigns=JournalCampaign(positive)).verify_workspace(fixed,box,baseline)
                    save(positive/'verification.json',result.model_dump(mode='json'))
                    records.append({'case':name,'faulty_diagnoses':[d['kind'] for d in diagnoses],
                        'verified':result.passed,'stress_passed':result.passed_runs,'stress_total':result.total_runs,
                        'semantic_passed':result.semantic_passed,'tsan_passed':result.sanitizer_passed,
                        'original_tests_passed':result.evidence['original_tests']['passed'],
                        'verification_ms':result.duration_ms,'infrastructure_failures':result.infrastructure_failures})
                    if not result.passed: raise RuntimeError('Positive control failed verification')
    finally:
        changed=[name for name,value in protected.items() if digest(ROOT/name)!=value]
        save(out/'integrity.json',{'unchanged':not changed,'protected_files':len(protected),'changed':changed})
        save(out/'results.json',{'model_calls':0,'tokens':0,'records':records,'all_cases_completed':len(records)==3})
        lines=['# Expanded concurrency validation','',
            'Manually authored synthetic controls, not model-generated repairs. Zero model calls or tokens.',
            'Three diagnostic runs per faulty variant; three additional TSan runs for missing synchronization.', '',
            '| Case | Faulty diagnostic | Fixed stress | Fixed semantics | Fixed TSan | Verified |',
            '|---|---|---|---|---|---|']
        for r in records:
            lines.append(f"| {r['case']} | {', '.join(r['faulty_diagnoses'])} | {r['stress_passed']}/{r['stress_total']} | {r['semantic_passed']} | {r['tsan_passed']} | {r['verified']} |")
        lines += ['',f'Completed positive-control cases: {len(records)}/3. Protected files unchanged: {not changed}.',
            'Semantic and original-test executions repeat the workload; they do not provide independent behavioral coverage.',
            'Lost-signal diagnosis deliberately remains timeout_unexplained in the generic detector: a known synthetic root cause is not equivalent to runtime proof.',
            'These controls broaden verifier coverage. They do not demonstrate improved model repair quality or real-application readiness. Frozen benchmark outcomes and production policies remain unchanged.']
        (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(out/'REPORT.md',flush=True)
        if changed: raise RuntimeError('Protected evidence changed')


if __name__=='__main__': asyncio.run(main())
