"""Direct source repair of both sides of the pair invariant; no model calls."""
import asyncio
from datetime import datetime, timezone
import difflib
import os
from time import perf_counter

from repository_live_ab import ROOT, read, save, digest, check_hashes
from verify_saved_super_candidate import JournalCampaign
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.repository.learning import require_verified

PRIOR = ROOT/'reports/race-correction/20261011T111419Z'


async def main():
    check_hashes(read(PRIOR/'preserved-sha256.json'))
    plan = read(PRIOR/'plan.json')
    prior_task = ConcurrencyTask.model_validate(plan['task'])
    latest = read(PRIOR/'corrected-sources.json')['solution.c']
    old_reader = '''int snapshot_ok(void) {
    int a = left;
    sched_yield();
    int b = right;
    return a + b == 0;
}'''
    new_reader = '''int snapshot_ok(void) {
    /* Read both fields in the same critical section as the writer. */
    pthread_mutex_lock(&guard);
    int a = left;
    sched_yield();
    int b = right;
    pthread_mutex_unlock(&guard);
    return a + b == 0;
}'''
    old_writer = '    left = n;\n    right = -n;'
    new_writer = '    left = n;\n    sched_yield();\n    right = -n;'
    if latest.count(old_reader) != 1 or latest.count(old_writer) != 1:
        raise ValueError('Unexpected candidate; refuse speculative patching')
    fixed = latest.replace(old_reader, new_reader).replace(old_writer, new_writer)
    patch = ''.join(difflib.unified_diff(latest.splitlines(True), fixed.splitlines(True),
                                       fromfile='a/solution.c', tofile='b/solution.c'))
    out = ROOT/'reports/pair-snapshot-repair'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    print('Evidence: '+str(out), flush=True)
    protected = {p.relative_to(ROOT).as_posix():digest(p)
        for folder in ('src','examples','benchmarks','reports','datasets','scripts','tests')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json', protected)
    base = out/'failed-candidate'; base.mkdir()
    repaired = out/'repaired-project'; repaired.mkdir()
    (base/'solution.c').write_text(latest, encoding='utf-8', newline='\n')
    (repaired/'solution.c').write_text(fixed, encoding='utf-8', newline='\n')
    for name in prior_task.support_files:
        data = (prior_task.workspace/name).read_bytes()
        (base/name).write_bytes(data)
        (repaired/name).write_bytes(data)
    task = prior_task.model_copy(update={'workspace':base})
    (out/'candidate.patch').write_text(patch, encoding='utf-8')
    save(repaired/'task.json', prior_task.model_copy(update={'workspace':repaired}).model_dump(mode='json'))
    save(out/'plan.json', {'origin':'direct_source_repair_not_target_model_success',
        'prior_correction':str(PRIOR.relative_to(ROOT)), 'model_calls':0, 'model_tokens':0,
        'model_cost_usd':0, 'sandbox_cost_basis':'User confirmed free beta access',
        'change':'One guard critical section for the paired write and another for the paired read. Restore writer scheduling hook.',
        'task':task.model_dump(mode='json'), 'image':plan['image'],
        'prior_candidate_sha256':digest(PRIOR/'corrected-sources.json'),
        'candidate_sha256':digest(repaired/'solution.c')})
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = plan['image']
    staging = out/'staging'; staging.mkdir()
    started = perf_counter()
    result = None
    try:
        async with asyncio.timeout(900):
            async with NebiusSandboxBackend(temporary_parent=staging) as box:
                await box.upload_project(base, task.source_files+task.support_files)
                applied = await box.apply_patch(patch, task.source_files)
                save(out/'patch-application.json', applied.model_dump())
                if not applied.success or await box.read_file('solution.c') != fixed:
                    raise ValueError('Remote candidate identity mismatch')
                for name in task.support_files:
                    if (await box.read_file(name)).encode() != (prior_task.workspace/name).read_bytes():
                        raise ValueError('Protected interface changed')
                result = await ConcurrencyVerifier(campaigns=JournalCampaign(out)).verify_workspace(task, box)
                save(out/'verification.json', result.model_dump(mode='json'))
                require_verified(result.model_dump(mode='json'), task.verification_config.model_dump())
    except Exception as exc:
        save(out/'failure.json', {'type':type(exc).__name__, 'automatic_replay':False})
        raise
    finally:
        check_hashes(protected)
        save(out/'integrity.json', {'unchanged':True, 'protected_files':len(protected)})
        save(out/'metrics.json', {'model_calls':0, 'model_tokens':0, 'model_cost_usd':0,
            'outcome':'verified' if result and result.passed else ('rejected' if result and not result.infrastructure_failures else 'unknown'),
            'verification_ms':result.duration_ms if result else None,
            'end_to_end_ms':(perf_counter()-started)*1000,
            'first_attempt_relabelled':False, 'model_correction_relabelled':False})
    print('VERIFIED: '+str(repaired), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
