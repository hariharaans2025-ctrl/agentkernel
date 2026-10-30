"""Export a human-authored queue repair and verify it only in Nebius Sandbox."""
import asyncio
from datetime import datetime, timezone
import difflib
import os
from time import perf_counter

from repository_live_ab import ROOT, ONBOARD, BASELINE, read, save, digest, check_hashes
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from optimization_experiment import RecordingCampaign


async def main():
    check_hashes(read(ROOT / 'reports/repository-live-ab/20261007T121122Z/preserved-sha256.json'))
    task = ConcurrencyTask.model_validate(read(ONBOARD)['task'])
    original = (task.workspace / 'src/queue.c').read_text(encoding='utf-8')
    old_worker = '''    pthread_mutex_lock(&q->queue_lock);
    /* Test scheduling hook: overlap the two operations while holding first locks. */
    if (force_overlap) pthread_barrier_wait(&q->reproduce_barrier);'''
    new_worker = '''    /* Both participants must reach the barrier before acquiring shared locks. */
    if (force_overlap) pthread_barrier_wait(&q->reproduce_barrier);
    pthread_mutex_lock(&q->queue_lock);'''
    old_monitor = '''    /* Intentional fault: monitoring acquires the same locks in reverse order. */
    pthread_mutex_lock(&q->stats_lock);
    if (force_overlap) pthread_barrier_wait(&q->reproduce_barrier);
    if (force_overlap) fprintf(stderr, "MONITOR HOLD stats WAIT queue\\n");
    pthread_mutex_lock(&q->queue_lock);
    int outstanding = q->length - q->completed;
    pthread_mutex_unlock(&q->queue_lock);
    pthread_mutex_unlock(&q->stats_lock);'''
    new_monitor = '''    /* Match the worker: rendezvous without locks, then queue before stats. */
    if (force_overlap) pthread_barrier_wait(&q->reproduce_barrier);
    pthread_mutex_lock(&q->queue_lock);
    if (force_overlap) fprintf(stderr, "MONITOR HOLD queue WAIT stats\\n");
    pthread_mutex_lock(&q->stats_lock);
    int outstanding = q->length - q->completed;
    pthread_mutex_unlock(&q->stats_lock);
    pthread_mutex_unlock(&q->queue_lock);'''
    assert original.count(old_worker) == original.count(old_monitor) == 1
    candidate = original.replace(old_worker, new_worker).replace(old_monitor, new_monitor)
    patch = ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                       fromfile='a/src/queue.c', tofile='b/src/queue.c'))
    out = ROOT / 'reports/repository-manual-repair' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    protected = {p.relative_to(ROOT).as_posix(): digest(p)
                 for folder in ('src', 'examples', 'benchmarks', 'reports')
                 for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    out.mkdir(parents=True, exist_ok=False)
    print('Evidence: ' + str(out), flush=True)
    save(out / 'preserved-sha256.json', protected)
    save(out / 'plan.json', {'origin':'human_authored_repair', 'model_calls':0, 'tokens':0,
         'image':'agentkernel-clang:20261003122908', 'verification':task.verification_config.model_dump(),
         'baseline_sha256':digest(BASELINE), 'controller_sha256':digest(ROOT/'scripts/verify_queue_barrier_repair.py')})
    (out / 'candidate.patch').write_text(patch, encoding='utf-8')
    project = out / 'repaired-project'
    for name in task.source_files + task.support_files + ['agentkernel.repository.json']:
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(candidate.encode() if name == 'src/queue.c' else (task.workspace/name).read_bytes())
    staging = out / 'staging'
    staging.mkdir()
    load_env_file(ROOT / '.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-clang:20261003122908'
    started = perf_counter()
    try:
        async with NebiusSandboxBackend(temporary_parent=staging) as box:
            await box.upload_project(task.workspace, task.source_files + task.support_files)
            applied = await box.apply_patch(patch, task.source_files)
            save(out / 'patch-application.json', applied.model_dump())
            if not applied.success:
                raise RuntimeError('Patch application failed')
            assert await box.read_file('src/queue.c') == candidate
            for name in task.support_files:
                assert (await box.read_file(name)).encode() == (task.workspace/name).read_bytes()
            result = await ConcurrencyVerifier(campaigns=RecordingCampaign(out, True)).verify_workspace(
                task, box, CampaignResult.model_validate(read(BASELINE)))
            save(out / 'verification.json', result.model_dump(mode='json'))
        check_hashes(protected)
        save(out / 'integrity.json', {'unchanged':True, 'protected_files':len(protected)})
        save(out / 'metrics.json', {'model_calls':0, 'tokens':0, 'verification_ms':result.duration_ms,
             'end_to_end_ms':(perf_counter()-started)*1000, 'passed':result.passed})
        report = f'''# Queue barrier repair

Origin: human-authored repair, not a model success. Model calls: 0. Tokens: 0.

Both threads now rendezvous before holding either shared mutex. Both acquire queue then stats and release in reverse order. The barrier, workload, semantic oracle, test counts and timeouts are retained.

- Overall verified: {result.passed}
- Stress: {result.passed_runs}/{result.total_runs}
- Original tests: {result.evidence['original_tests']['passed']}
- Semantics: {result.semantic_passed}
- Required TSan: {result.sanitizer_passed} (3 configured runs; raw evidence in campaign-2.json)
- Infrastructure failures: {result.infrastructure_failures}
- Protected files unchanged: {len(protected)}

The repaired project is exported in repaired-project/. Only src/queue.c differs from the original. Original fixtures and all earlier evidence remain unchanged. This result covers the configured synthetic workload, not proof of correctness for arbitrary applications.
'''
        (out / 'REPORT.md').write_text(report, encoding='utf-8')
        print(report, flush=True)
        if not result.passed:
            raise RuntimeError('Candidate did not pass full verification')
    finally:
        check_hashes(protected)


if __name__ == '__main__':
    asyncio.run(main())
