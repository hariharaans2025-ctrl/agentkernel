"""Remote tests and synthetic baseline only. Never invoke an inference model."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from agentkernel.config import load_env_file
from agentkernel.repository.onboarding import create_plan
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.campaign.manager import StressCampaignManager

ROOT = Path(__file__).resolve().parents[1]


def save(path, data):
    with path.open('x', encoding='utf-8') as stream: json.dump(data, stream, indent=2)


def integrity():
    old = json.loads((ROOT / 'reports/optimization-experiments/validation-v2-20261005T161506Z/preserved-sha256.json').read_text())
    changes = [name for name, value in old.items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != value]
    if changes: raise ValueError('Protected prior files changed: ' + ', '.join(changes))
    return len(old)


async def main():
    out = ROOT / 'reports/repository-onboarding' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    staging = out / 'staging'
    staging.mkdir()
    print('Evidence: ' + str(out), flush=True)
    count = integrity()
    example = ROOT / 'examples/job-queue-service'
    plan = create_plan(example, example / 'agentkernel.repository.json', out / 'plan')
    files = [p.relative_to(ROOT).as_posix() for p in (ROOT / 'src/agentkernel/repository').glob('*.py')]
    files += [p.relative_to(ROOT).as_posix() for p in example.rglob('*') if p.is_file()]
    files += ['tests/test_repository_onboarding.py']
    save(out / 'code-sha256.json', {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files})
    load_env_file(ROOT / '.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-project:20261004t054834z'
    async with NebiusSandboxBackend(temporary_parent=staging) as box:
        await box.upload_project(ROOT, files)
        tests = await box.run_command(['python3', '-m', 'pytest', '-q', 'tests/test_repository_onboarding.py'], timeout=110,
                                      environment={'PYTHONPATH': '/workspace/src'})
        save(out / 'tests.json', tests.model_dump())
        print(tests.stdout, flush=True)
        if tests.exit_code != 0 or tests.timed_out: raise ValueError('Repository tests failed')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-clang:20261003122908'
    task = ConcurrencyTask.model_validate(plan['task'])
    async with NebiusSandboxBackend(temporary_parent=staging) as box:
        await box.upload_project(example, task.source_files + task.support_files)
        build = await CCompiler().compile(task, box)
        save(out / 'build.json', build.model_dump())
        if not build.success: raise ValueError('Example build failed')
        for index, command in enumerate(task.verification_config.original_test_commands):
            test = await box.run_command(command, timeout=task.max_runtime_seconds)
            save(out / f'original-test-{index+1}.json', test.model_dump())
            if test.exit_code != 0 or test.timed_out or 'SEMANTIC_PASS' not in test.stdout:
                raise ValueError('Example correctness test failed')
        baseline = await StressCampaignManager().run(task, box, runs=task.stress_runs)
        save(out / 'baseline.json', baseline.model_dump(mode='json'))
        reproduced = len(baseline.runs) == 3 and baseline.counts.get('POSSIBLE_DEADLOCK', 0) == 3 and baseline.infrastructure_failures == 0
        if not reproduced: raise ValueError('Expected baseline deadlock not reproduced')
    save(out / 'integrity.json', {'unchanged': integrity() == count, 'protected_files': count})
    text = ('# Repository onboarding: step 1\n\n'
            'Synthetic example only; not an external real-world repair.\n\n'
            f'Targeted onboarding tests: {tests.stdout.strip()}\n\n'
            'Nebius build passed. One-job smoke and 100-job exactly-once/checksum checks passed.\n'
            'Concurrent reproducer: 3/3 POSSIBLE_DEADLOCK timeouts; no infrastructure failures.\n'
            'No repair proposed. No inference calls. No token or application performance improvement claimed.\n'
            'The later repair contract requires 100 stress runs, protected semantics and 3 TSan runs; these are not completed in this onboarding step.\n'
            'Token reservation and metrics primitives are tested independently, not yet integrated into the live inference runtime.\n'
            f'All {count} protected prior files unchanged.\n')
    (out / 'REPORT.md').write_text(text, encoding='utf-8')
    print(text, flush=True)


if __name__ == '__main__': asyncio.run(main())
