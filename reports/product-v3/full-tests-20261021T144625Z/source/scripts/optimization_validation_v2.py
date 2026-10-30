"""Remote-only paired replay: reversed timing and known rejected candidates.

No model provider is imported or called. Existing experiment code is reused
unchanged. New evidence is exclusive-created; interrupted arms are never retried.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

from optimization_experiment import ROOT, RecordingCampaign, digest, snapshot
from agentkernel.config import load_env_file
from agentkernel.concurrency.benchmark.loader import load_task
from agentkernel.concurrency.campaign.scheduler import StressSchedule
from agentkernel.concurrency.execution.runner import ExecutionRunner
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier


def save(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def read_summary(path):
    for line in reversed(path.read_text(encoding='utf-8').splitlines()):
        event = json.loads(line)
        if event.get('event_type') == 'concurrency_job': return event['summary']
    raise ValueError('Missing preserved job summary')


class ProgressRunner(ExecutionRunner):
    def __init__(self, path):
        self.path = path

    async def run(self, task, sandbox, run_id, environment=None):
        result = await super().run(task, sandbox, run_id, environment)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'command': task.run_command, 'environment': {**task.environment, **(environment or {})},
                                     'run': result.model_dump(mode='json')}) + '\n')
        index = int(run_id.rsplit(':', 1)[1])
        if index % 10 == 0: print(f'Serial {task.task_id}: {index} executions', flush=True)
        return result


def preserved_files(out):
    files = snapshot()
    root = ROOT / 'reports/optimization-experiments'
    for path in root.rglob('*'):
        if path.is_file() and out not in path.parents:
            files[path.relative_to(ROOT).as_posix()] = digest(path)
    for path in (ROOT / 'scripts').glob('*.py'):
        files[path.relative_to(ROOT).as_posix()] = digest(path)
    return files


def check_campaigns(arm_out, config):
    expected = [config.stress_runs]
    if config.sanitizer_enabled or config.sanitizer_required: expected.append(config.sanitizer_runs)
    for number, count in enumerate(expected, 1):
        data = json.loads((arm_out / f'campaign-{number}.json').read_text(encoding='utf-8'))
        if len(data['runs']) != count or data['requested_runs'] != count:
            raise ValueError('Verification run count mismatch')
        if len({r['run_id'] for r in data['runs']}) != count:
            raise ValueError('Duplicate run IDs')


def report(out, results, unchanged, error):
    rows = ['# Optimization validation v2', '',
            'Saved-candidate replay on Nebius Sandbox. Model calls: 0. No production changes.',
            f'Prior source, fixtures, benchmark and experiment evidence unchanged: {unchanged}.',
            f'Completed arms: {len(results)}/6. Interrupted: {bool(error)}.', '',
            '| Candidate | Method | Verified | Stress passes | Deadlocks | Semantic pass | TSan pass | Seconds |',
            '|---|---|---:|---:|---:|---|---|---:|']
    for item in results:
        v = item['verification']
        tsan = str(v['sanitizer_passed']) if v['sanitizer_passed'] is not None else 'not configured'
        rows.append(f"| {item['fixture']} | {item['arm']} | {v['passed']} | {v['passed_runs']}/{v['total_runs']} | {v['deadlock_count']} | {v['semantic_passed']} | {tsan} | {v['duration_ms']/1000:.3f} |")
    rows.extend(['', '## Reversed timing', ''])
    timings = {r['arm']: r['verification']['duration_ms'] for r in results if r['fixture'] == 'race_002'}
    if len(timings) == 2:
        rows.append(f"Batch-first pair: serial {timings['serial']/1000:.3f}s, batch {timings['batch']/1000:.3f}s; {100*(1-timings['batch']/timings['serial']):.1f}% less time with batching.")
    first = ROOT / 'reports/optimization-experiments/20261005T160434Z'
    rows.append('Prior serial-first pair (read-only reference): ' + str(first))
    rows.extend(['', '## Detection gates', ''])
    for fixture in ('deadlock_001', 'deadlock_002'):
        arms = [r for r in results if r['fixture'] == fixture]
        if len(arms) == 2:
            detected = all(not r['verification']['passed'] and not r['verification']['infrastructure_failures'] for r in arms)
            rows.append(f'{fixture}: both methods rejected the saved faulty candidate = {detected}.')
    eligible = len(results) == 6 and all(r['verification']['passed'] == (r['fixture'] == 'race_002')
                                       and not r['verification']['infrastructure_failures'] for r in results)
    rows.extend(['', f'Observed replay gates passed: {eligible and unchanged and not error}.',
                 'This is not a production approval or proof of equivalent bug-detection sensitivity.', '',
                 'Only one successful candidate has two opposite-order pairs across two sessions. Negative candidates have one pair each; failure frequencies may differ because concurrency is nondeterministic.',
                 'The intermittent deadlock candidate previously passed 96/100; a clean rerun would not establish that it is correct. Any missed rejection blocks recommending production rollout.',
                 'All arms retain 100 stress runs and the original semantic oracle. race_002 additionally retains 3 required TSan runs; deadlock fixtures do not configure TSan.',
                 'No known TSan-failing candidate is included, so race-detection sensitivity remains unvalidated.',
                 'Batch shares a remote instance per 10 independent processes. Service load, scheduling and instance lifetime remain confounders.',
                 'No token savings or model quality measurements are produced. The interrupted frozen Super race_005 job is untouched.'])
    (out / 'REPORT.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')


async def main():
    out = ROOT / 'reports/optimization-experiments' / ('validation-v2-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True, exist_ok=False)
    print('Evidence: ' + str(out), flush=True)
    before = preserved_files(out)
    save(out / 'preserved-sha256.json', before)
    results, error = [], None
    try:
        original = json.loads((ROOT / 'reports/combined-view-20261004/evidence-sha256.json').read_text(encoding='utf-8'))
        if any(digest(ROOT / 'reports' / name) != value for name, value in original.items()):
            raise ValueError('Original frozen evidence mismatch')
        reference = ROOT / 'reports/optimization-experiments/20261005T160434Z'
        hashes = json.loads((reference / 'experiment-code-sha256.json').read_text(encoding='utf-8'))
        if any(digest(ROOT / name) != value for name, value in hashes.items()):
            raise ValueError('Prior experiment code changed')
        cases = [
            ('race_002', ROOT / 'reports/continuation-20261004T104857Z/race_002-adaptive.jsonl', ['batch', 'serial']),
            ('deadlock_001', ROOT / 'reports/deadlock_001-super_only.jsonl', ['serial', 'batch']),
            ('deadlock_002', ROOT / 'reports/continuation-20261004T104857Z/deadlock_002-adaptive.jsonl', ['batch', 'serial']),
        ]
        prepared, plan = [], []
        for fixture, evidence_path, arms in cases:
            data = read_summary(evidence_path)
            task = load_task(ROOT / 'benchmarks' / fixture)
            if task.verification_config.model_dump() != data['metadata']['verification_configuration']:
                raise ValueError('Verification configuration differs from preserved run')
            if any(digest(task.workspace / name) != value for name,value in data['metadata']['source_sha256'].items()):
                raise ValueError('Fixture or oracle differs from preserved run')
            attempt = data['metadata']['attempt_details'][0]
            if attempt['tier'] != 'SUPER': raise ValueError('Unexpected saved candidate tier')
            candidate = attempt['verification_evidence']['candidate_sources']
            if set(candidate) != set(task.source_files): raise ValueError('Unexpected candidate files')
            prior = attempt['verification_evidence']['verification']
            if prior['passed'] != (fixture == 'race_002'): raise ValueError('Unexpected prior verification')
            prepared.append((task, candidate, arms))
            plan.append({'fixture': fixture, 'arms': arms, 'source_evidence': str(evidence_path),
                'source_evidence_sha256': digest(evidence_path), 'prior_passed': prior['passed'],
                'prior_stress_passes': prior['passed_runs'],
                'candidate_sha256': {k: hashlib.sha256(v.encode('utf-8')).hexdigest() for k,v in candidate.items()},
                'verification_config': task.verification_config.model_dump(),
                'stress_environments': [{**task.environment, **StressSchedule().environment_for(i)} for i in range(100)]})
        save(out / 'plan.json', {'version': 2, 'model_calls': 0, 'cases': plan, 'retry': False,
                                'image': 'agentkernel-clang:20261003122908', 'batch_size': 10})
        load_env_file(ROOT / '.env')
        os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-clang:20261003122908'
        for task, candidate, arms in prepared:
            for arm in arms:
                arm_out = out / (task.task_id + '-' + arm)
                arm_out.mkdir()
                save(arm_out / 'started.json', {'time': datetime.now(timezone.utc).isoformat(), 'state': 'STARTED; outcome unknown until verification.json exists'})
                print(f'Starting {task.task_id} {arm}', flush=True)
                wall = perf_counter()
                async with NebiusSandboxBackend() as box:
                    await box.upload_project(task.workspace, task.source_files + task.support_files)
                    await box._upload({'/workspace/' + k: v.encode('utf-8') for k,v in candidate.items()})
                    campaigns = RecordingCampaign(arm_out, arm == 'batch')
                    campaigns.runner = ProgressRunner(arm_out / 'serial-runs.jsonl')
                    verified = await ConcurrencyVerifier(campaigns=campaigns).verify_workspace(task, box)
                    save(arm_out / 'verification.json', verified.model_dump(mode='json'))
                    item = {'fixture': task.task_id, 'arm': arm, 'verification': verified.model_dump(mode='json'),
                            'setup_plus_verification_wall_ms': (perf_counter()-wall)*1000}
                    results.append(item)
                    print(f'Completed {task.task_id} {arm}: verified={verified.passed}; stress={verified.passed_runs}/{verified.total_runs}; deadlocks={verified.deadlock_count}; seconds={verified.duration_ms/1000:.3f}', flush=True)
                    if verified.infrastructure_failures: raise ValueError('Infrastructure failure; no retry')
                    check_campaigns(arm_out, task.verification_config)
        save(out / 'results.json', results)
    except Exception as exc:
        error = type(exc).__name__
        save(out / 'error.json', {'type': error, 'message': 'Stopped without retry. Inspect completed evidence; current arm may be incomplete.'})
        raise
    finally:
        unchanged = before == preserved_files(out)
        save(out / 'integrity.json', {'unchanged': unchanged, 'files': len(before)})
        report(out, results, unchanged, error)
        if not unchanged: raise ValueError('Protected source or evidence changed')


if __name__ == '__main__':
    asyncio.run(main())
