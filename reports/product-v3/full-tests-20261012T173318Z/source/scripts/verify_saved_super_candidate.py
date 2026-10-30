"""Fresh verification only of the immutable diagnostic-assisted Super patch."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
from time import perf_counter

from repository_live_ab import ROOT, ONBOARD, BASELINE, read, save, digest, check_hashes
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.campaign.manager import StressCampaignManager
from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.execution.models import ExecutionRun, RunClassification
from agentkernel.concurrency.analyzer.classifier import classify
from agentkernel.concurrency.sandbox.base import CommandResult
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from optimization_experiment import batch_commands

PRIOR = ROOT/'reports/barrier-repair-live/20261010T092756Z'


class JournalCampaign(StressCampaignManager):
    """Same schedule and batching, with each received batch saved immediately."""
    def __init__(self, out):
        super().__init__()
        self.out, self.number = out, 0

    async def run(self, task, sandbox, *, runs=None):
        count = task.stress_runs if runs is None else runs
        self.number += 1
        started, records = perf_counter(), []
        for first in range(0, count, 10):
            specs = [{'command':task.run_command,'timeout':task.max_runtime_seconds,
                      'environment':{**task.environment, **self.schedule.environment_for(i)},
                      'limit':sandbox.output_limit} for i in range(first, min(first+10,count))]
            save(self.out/f'campaign-{self.number}-batch-{first+1}-started.json',
                 {'first_run':first+1,'count':len(specs),'utc':datetime.now(timezone.utc).isoformat()})
            rows = await batch_commands(sandbox,specs)
            save(self.out/f'campaign-{self.number}-batch-{first+1}.json',rows)
            for i,row in enumerate(rows,first):
                result=CommandResult(command=task.run_command,**row['result'])
                kind=classify(result,task.expected_behavior)
                records.append(ExecutionRun(run_id=f'{task.task_id}:{i+1}',start_time=row['start_time'],
                    duration_ms=result.duration_ms,exit_code=result.exit_code,stdout=result.stdout,
                    stderr=result.stderr,timed_out=result.timed_out,crashed=kind==RunClassification.CRASH,
                    sanitizer_detected=kind in {RunClassification.RACE_DETECTED,RunClassification.SANITIZER_FAILURE},
                    classification=kind,metadata=result.metadata))
            print(f'Campaign {self.number}: {len(records)}/{count}; '+str(dict(Counter(r.classification.value for r in records))),flush=True)
        campaign=CampaignResult(task_id=task.task_id,runs=records,requested_runs=count,
            counts=dict(Counter(r.classification.value for r in records)),duration_ms=(perf_counter()-started)*1000)
        save(self.out/f'campaign-{self.number}.json',campaign.model_dump(mode='json'))
        return campaign


async def main():
    check_hashes(read(PRIOR/'preserved-sha256.json'))
    task=ConcurrencyTask.model_validate(read(ONBOARD)['task'])
    candidate=read(PRIOR/'candidate-sources.json')
    patch=(PRIOR/'candidate.patch').read_text(encoding='utf-8')
    out=ROOT/'reports/super-candidate-verification'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    print('Evidence: '+str(out),flush=True)
    protected={p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports','scripts')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json',protected)
    save(out/'plan.json',{'origin':str(PRIOR.relative_to(ROOT)),'new_model_calls':0,'new_tokens':0,
        'patch_sha256':digest(PRIOR/'candidate.patch'),'candidate_sha256':digest(PRIOR/'candidate-sources.json'),
        'verification':task.verification_config.model_dump(),'image':'agentkernel-clang:20261003122908',
        'policy':'Fresh, separately authorized verification-only campaign. Earlier interrupted outcome remains unknown; no model calls or patch changes. No automatic workload retries.'})
    staging=out/'staging'; staging.mkdir()
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    started=perf_counter()
    result=None
    try:
        async with asyncio.timeout(1800):
            async with NebiusSandboxBackend(temporary_parent=staging) as box:
                await box.upload_project(task.workspace,task.source_files+task.support_files)
                applied=await box.apply_patch(patch,task.source_files)
                save(out/'patch-application.json',applied.model_dump())
                if not applied.success: raise RuntimeError('Saved patch did not apply')
                for name,expected in candidate.items():
                    if await box.read_file(name)!=expected: raise RuntimeError('Candidate differs from model output')
                for name in task.support_files:
                    if (await box.read_file(name)).encode()!=(task.workspace/name).read_bytes(): raise RuntimeError('Support source changed')
                save(out/'candidate-identity.json',{'exact_saved_candidate':True,'support_files_unchanged':True})
                result=await ConcurrencyVerifier(campaigns=JournalCampaign(out)).verify_workspace(
                    task,box,CampaignResult.model_validate(read(BASELINE)))
                save(out/'verification.json',result.model_dump(mode='json'))
    except Exception as exc:
        save(out/'interruption.json',{'type':type(exc).__name__,'outcome':'UNKNOWN','model_calls':0,
                                    'reason':'Verification interrupted; persisted batches remain evidence, no automatic replay.'})
        raise
    finally:
        changed=[name for name,value in protected.items() if digest(ROOT/name)!=value]
        save(out/'integrity.json',{'unchanged':not changed,'protected_files':len(protected),'changed':changed})
        metrics={'new_model_calls':0,'new_tokens':0,'origin_model_calls':1,'origin_tokens':read(PRIOR/'metrics.json')['tokens'],
                 'end_to_end_ms':(perf_counter()-started)*1000,
                 'outcome':'unknown' if result is None or result.infrastructure_failures else ('verified' if result.passed else 'rejected')}
        if result:
            metrics.update(verification_ms=result.duration_ms,stress_passed=result.passed_runs,stress_total=result.total_runs,
                original_tests_passed=result.evidence['original_tests']['passed'],semantic_passed=result.semantic_passed,
                tsan_passed=result.sanitizer_passed,false_fix=result.false_fix,semantic_regression=result.semantic_regression,
                races=result.race_count,deadlocks=result.deadlock_count,infrastructure_failures=result.infrastructure_failures)
        save(out/'metrics.json',metrics)
        lines=['# Saved Super candidate verification','',
            'Exact candidate from reports/barrier-repair-live/20261010T092756Z; no edits or new inference.',
            'Fresh verification-only campaign. Earlier interrupted run remains UNKNOWN and immutable.','']
        lines.extend(f'- {k}: {v}' for k,v in metrics.items())
        lines += ['',f'Protected files unchanged: {not changed} ({len(protected)} files).',
            'Each completed stress/TSan batch is saved separately. Full configured checks remain unchanged: original tests, 100 stress executions, semantic oracle and 3 TSan executions.',
            'Model confidence and stress success alone cannot establish a correct repair. Results cover this synthetic workload only.']
        (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(json.dumps(metrics),flush=True)
        if changed: raise RuntimeError('Protected evidence changed')


if __name__=='__main__': asyncio.run(main())
