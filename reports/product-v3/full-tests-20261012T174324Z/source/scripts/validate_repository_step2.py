"""Bounded remote diagnostics. No inference, repairs, or frozen benchmark edits."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from agentkernel.config import load_env_file
from agentkernel.repository.diagnostics import diagnose
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.campaign.manager import StressCampaignManager
from optimization_experiment import batch_commands

ROOT = Path(__file__).resolve().parents[1]


def save(path, data):
    with path.open('x', encoding='utf-8') as stream: json.dump(data, stream, indent=2)


def hashes():
    result = {}
    for folder in ('src', 'benchmarks', 'examples', 'reports/repository-onboarding', 'reports/optimization-experiments'):
        for path in (ROOT / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Original report/evidence and scripts preserved by the preceding validation.
    manifest = json.loads((ROOT / 'reports/optimization-experiments/validation-v2-20261005T161506Z/preserved-sha256.json').read_text())
    for name, value in manifest.items():
        current = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if current != value: raise ValueError('Frozen file changed: ' + name)
        result[name] = current
    return result


async def main():
    out = ROOT / 'reports/repository-diagnostics' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    staging = out / 'staging'
    staging.mkdir()
    print('Evidence: ' + str(out), flush=True)
    before = hashes()
    save(out / 'preserved-sha256.json', before)
    save(out / 'plan.json', {'model_calls': 0, 'queue_baseline_runs': 3,
        'tsan_controls': ['unsynchronized_counter', 'mutex_protected_counter'],
        'tsan_runs_per_control_per_method': 3, 'methods': ['serial', 'batch'],
        'note': 'Diagnostic controls only; not a 100-run candidate verification or production rollout.'})
    load_env_file(ROOT / '.env')
    results, deadlocks, stacks = {}, [], False
    error = None
    try:
        os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-project:20261004t054834z'
        async with NebiusSandboxBackend(temporary_parent=staging) as box:
            await box.upload_project(ROOT, ['src/agentkernel/repository/__init__.py',
                'src/agentkernel/repository/diagnostics.py', 'tests/test_repository_diagnostics.py'])
            test = await box.run_command(['python3', '-m', 'pytest', '-q', 'tests/test_repository_diagnostics.py'],
                timeout=60, environment={'PYTHONPATH': '/workspace/src'})
            save(out / 'tests.json', test.model_dump())
            print(test.stdout, flush=True)
            if test.exit_code != 0 or test.timed_out: raise ValueError('Diagnostic tests failed')
        os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-clang:20261003122908'
        async with NebiusSandboxBackend(temporary_parent=staging) as box:
            await box.upload_project(ROOT / 'examples/diagnostic-controls', ['race.c', 'capture.gdb.py'])
            version = await box.run_command(['clang', '--version'], timeout=10)
            save(out / 'toolchain.json', version.model_dump())
            for control, flags in [('racy', []), ('clean', ['-DSAFE'])]:
                binary = 'race_' + control
                build = await box.run_command(['clang', '-pthread', '-g', '-O1', '-fsanitize=thread', *flags, 'race.c', '-o', binary], timeout=30)
                save(out / f'{control}-build.json', build.model_dump())
                if build.exit_code != 0 or build.timed_out: raise ValueError('Control compilation failed')
                spec = {'command': ['./' + binary], 'timeout': 5,
                        'environment': {'TSAN_OPTIONS': 'halt_on_error=1:exitcode=66'}, 'limit': box.output_limit}
                for method in ('serial', 'batch'):
                    if method == 'serial':
                        runs = []
                        for i in range(3):
                            run = await box.run_command(spec['command'], timeout=spec['timeout'], environment=spec['environment'])
                            runs.append(run.model_dump())
                            save(out / f'{control}-{method}-{i+1}.json', runs[-1])
                    else:
                        rows = await batch_commands(box, [spec] * 3)
                        runs = [row['result'] for row in rows]
                        save(out / f'{control}-{method}-raw.json', rows)
                    diagnoses = [diagnose(r) for r in runs]
                    results[f'{control}-{method}'] = diagnoses
                    save(out / f'{control}-{method}-diagnoses.json', diagnoses)
                    print(control, method, [d['kind'] for d in diagnoses], flush=True)
                    expected = 'data_race' if control == 'racy' else 'completed_not_verified'
                    if any(d['kind'] != expected for d in diagnoses): raise ValueError('TSan control detection gate failed')
                    if control == 'clean' and any('counter=20000' not in r['stdout'] for r in runs):
                        raise ValueError('Clean control invariant failed')
            old_plan = json.loads((ROOT / 'reports/repository-onboarding/20261007T110957Z/plan/plan.json').read_text())
            task = ConcurrencyTask.model_validate(old_plan['task'])
            for name, info in old_plan['files'].items():
                if hashlib.sha256((task.workspace / name).read_bytes()).hexdigest() != info['sha256']:
                    raise ValueError('Queue sample changed since Step 1')
            await box.upload_project(task.workspace, task.source_files + task.support_files)
            build = await CCompiler().compile(task, box)
            save(out / 'queue-build.json', build.model_dump())
            if not build.success: raise ValueError('Queue compilation failed')
            campaign = await StressCampaignManager().run(task, box, runs=3)
            save(out / 'queue-campaign.json', campaign.model_dump(mode='json'))
            deadlocks = [diagnose(r.model_dump()) for r in campaign.runs]
            save(out / 'queue-diagnoses.json', deadlocks)
            if len(deadlocks) != 3 or any(d['kind'] != 'deadlock_supported_by_wait_cycle' for d in deadlocks):
                raise ValueError('Queue wait-cycle gate failed')
            print('Queue: 3/3 opposing wait cycles and timeouts. Installing diagnostic debugger in disposable workspace.', flush=True)
            update = await box.run_command(['apt-get', 'update'], timeout=60)
            save(out / 'debugger-package-index.json', update.model_dump())
            if update.exit_code == 0 and not update.timed_out:
                install = await box.run_command(['apt-get', 'install', '-y', '--no-install-recommends', 'gdb'], timeout=110,
                    environment={'DEBIAN_FRONTEND': 'noninteractive'})
                save(out / 'debugger-install.json', install.model_dump())
                if install.exit_code == 0 and not install.timed_out:
                    capture = await box.run_command(['gdb', '--batch', '--quiet', '--nx', '-x', 'capture.gdb.py', '--args', './job_service', '--stress'], timeout=15)
                    save(out / 'thread-stacks.json', capture.model_dump())
                    text = capture.stdout + capture.stderr
                    stacks = (capture.exit_code == 0 and not capture.timed_out and 'queue_process_one' in text
                              and 'queue_inspect' in text and 'pthread_mutex_lock' in text
                              and ' at src/main.c:' in text)
                    print('Thread stack capture:', stacks, flush=True)
    except Exception as exc:
        error = type(exc).__name__
        save(out / 'error.json', {'type': error, 'message': 'Validation stopped; no automatic retry or model calls.'})
        raise
    finally:
        unchanged = before == hashes()
        save(out / 'integrity.json', {'unchanged': unchanged, 'protected_files': len(before)})
        lines = ['# Step 2: repository diagnostics', '', 'Model calls: 0. Synthetic controls; no repair attempted.',
                 f'Protected files unchanged: {unchanged}. Runtime error: {error or "none"}.',
                 f'Queue diagnostic runs: {len(deadlocks)}. User-space thread stacks captured: {stacks}.', '',
                 '| Control / method | Diagnostic results |', '|---|---|']
        for key, values in results.items(): lines.append(f'| {key} | ' + ', '.join(d['kind'] for d in values) + ' |')
        lines += ['', 'Queue dependency: WORKER holds queue and waits for stats; MONITOR holds stats and waits for queue.',
                  'Wait edges are application-reported evidence. Timeouts without a cycle remain unexplained, and sanitizer runtime failures are infrastructure failures.',
                  'Raw diagnostics and sanitizer stack traces are retained. Fingerprints omit runtime addresses and retain finding locations.',
                  'TSan controls used 3 executions per method/control (12 total), not full repair verification. No production batching rollout or universal detection guarantee follows.',
                  'GDB was installed only in a disposable diagnostic snapshot after TSan controls; the pinned base tag is unchanged.',
                  'No token savings or application performance improvement is claimed.']
        if not stacks: lines += ['User-space stack capture remains unavailable/unverified; inspect debugger evidence before marking Step 2 complete.']
        (out / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        if not unchanged: raise ValueError('Protected files changed')


if __name__ == '__main__': asyncio.run(main())
