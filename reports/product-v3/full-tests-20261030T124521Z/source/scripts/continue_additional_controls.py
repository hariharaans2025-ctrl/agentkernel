"""Preserve completed stress evidence and finish interrupted/unstarted controls."""
import asyncio
from datetime import datetime, timezone
import os
from repository_live_ab import ROOT,read,save,digest,check_hashes
from verify_saved_super_candidate import JournalCampaign
from agentkernel.config import load_env_file
from agentkernel.repository.diagnostics import diagnose
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier

PRIOR=ROOT/'reports/additional-concurrency-controls/20261010T094228Z'


class ReuseStress(JournalCampaign):
    def __init__(self,out,saved):
        super().__init__(out)
        self.saved=saved

    async def run(self,task,sandbox,*,runs=None):
        if self.number==0:
            if runs!=100 or self.saved.task_id!=task.task_id or len(self.saved.runs)!=100 or self.saved.counts!={'PASS':100}:
                raise ValueError('Completed stress evidence does not match')
            self.number=1
            save(self.out/'reused-stress.json',{'source':str((PRIOR/'missing_sync/repaired/campaign-1.json').relative_to(ROOT)),
                'sha256':digest(PRIOR/'missing_sync/repaired/campaign-1.json'),'runs':100,'new_executions':0})
            return self.saved
        return await super().run(task,sandbox,runs=runs)


async def main():
    check_hashes(read(PRIOR/'preserved-sha256.json'))
    out=ROOT/'reports/additional-controls-continuation'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    print('Continuation: '+str(out),flush=True)
    protected={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','scripts')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json',protected)
    save(out/'plan.json',{'model_calls':0,'tokens':0,'prior':str(PRIOR.relative_to(ROOT)),
        'missing_sync':'Reuse exact persisted 100 stress runs; fresh build/original test and semantic check after prior infrastructure interruption, followed by unstarted 3 TSan runs.',
        'account_inversion':'Entirely unstarted: 3 faulty diagnostics then full fixed-control verification.',
        'prior_interrupted_semantic_attempt':'UNKNOWN; not overwritten or counted as a pass'})
    staging=out/'staging'; staging.mkdir()
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    records=list(read(PRIOR/'results.json')['records'])
    try:
        for name in ('missing_sync','account_inversion'):
            case=out/name; case.mkdir()
            fixed=ConcurrencyTask.model_validate(read(PRIOR/'missing_sync/repaired-task.json'))
            if name=='account_inversion':
                data=fixed.model_dump(mode='json')
                data['task_id']=name
                data['source_files']=[name+'.c']
                data['build_command']=[arg.replace('missing_sync.c',name+'.c') for arg in data['build_command']]
                for check in data['verification_config']['semantic_checks']:
                    check['build_command']=[arg.replace('missing_sync.c',name+'.c') for arg in check['build_command']]
                fixed=ConcurrencyTask.model_validate(data)
            save(case/'task.json',fixed.model_dump(mode='json'))
            async with NebiusSandboxBackend(temporary_parent=staging) as box:
                await box.upload_project(fixed.workspace,fixed.source_files)
                if name=='account_inversion':
                    faulty=fixed.model_copy(deep=True)
                    faulty.build_command=[arg for arg in faulty.build_command if arg!='-DREPAIRED']
                    negative=case/'faulty'; negative.mkdir()
                    build=await CCompiler().compile(faulty,box)
                    save(negative/'build.json',build.model_dump())
                    if not build.success: raise RuntimeError('Faulty control build failed')
                    baseline=await JournalCampaign(negative).run(faulty,box,runs=3)
                    diagnoses=[diagnose(r.model_dump()) for r in baseline.runs]
                    save(negative/'diagnoses.json',diagnoses)
                    if any(d['kind']!='deadlock_supported_by_wait_cycle' for d in diagnoses): raise RuntimeError('Missing wait cycle')
                    campaigns=JournalCampaign(case)
                else:
                    baseline=CampaignResult.model_validate(read(PRIOR/'missing_sync/faulty/campaign-1.json'))
                    campaigns=ReuseStress(case,CampaignResult.model_validate(read(PRIOR/'missing_sync/repaired/campaign-1.json')))
                print('Completing '+name,flush=True)
                result=await ConcurrencyVerifier(campaigns=campaigns).verify_workspace(fixed,box,baseline)
                save(case/'verification.json',result.model_dump(mode='json'))
                records.append({'case':name,'verified':result.passed,'stress_passed':result.passed_runs,'stress_total':result.total_runs,
                    'semantic_passed':result.semantic_passed,'tsan_passed':result.sanitizer_passed,
                    'infrastructure_failures':result.infrastructure_failures,'stress_reused':name=='missing_sync'})
                if not result.passed: raise RuntimeError('Positive control verification failed')
    finally:
        changed=[name for name,value in protected.items() if digest(ROOT/name)!=value]
        save(out/'integrity.json',{'unchanged':not changed,'protected_files':len(protected),'changed':changed})
        save(out/'combined-view.json',{'prior':str(PRIOR.relative_to(ROOT)),'model_calls':0,'tokens':0,'records':records})
        lines=['# Expanded validation: combined view','',
            'Three manually authored synthetic positive controls. No model inference; these are not model repair successes.',
            'Source run: '+str(PRIOR.relative_to(ROOT))+'. Original evidence remains unchanged.',
            'The interrupted missing-sync semantic attempt remains UNKNOWN. Its 100 completed stress runs were reused unchanged; build/original-test/semantic checks ran afresh and 3 TSan checks ran for the first time.','',
            '| Case | Verified | Stress | Semantics | TSan |','|---|---|---|---|---|']
        for r in records:
            lines.append(f"| {r['case']} | {r['verified']} | {r['stress_passed']}/{r['stress_total']} | {r['semantic_passed']} | {r['tsan_passed']} |")
        lines += ['',f'Protected files unchanged: {not changed}.',
            'Original tests and semantic runs repeat the workload, not independent coverage. No general safety, model quality or statistical superiority claim follows.']
        (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(out/'REPORT.md',flush=True)
        if changed: raise RuntimeError('Protected files changed')


if __name__=='__main__': asyncio.run(main())
