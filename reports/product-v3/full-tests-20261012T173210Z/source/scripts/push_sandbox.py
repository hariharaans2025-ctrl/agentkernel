"""Collect and run the full account-independent test suite on Nebius only.

This controller uploads an explicit source allowlist. Credentials, model weights,
historical private reports, and virtual environments are never transferred.
"""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from agentkernel.config import load_env_file
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.telemetry.redaction import redact

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "agentkernel-clang:20261003122908"
SELECTION = "not nebius and not langsmith and not gpu"
SOURCE_FOLDERS = ("src", "tests", "benchmarks", "scripts", "examples")
SOURCE_SUFFIXES = {".py", ".c", ".h", ".json", ".md", ".html", ".css", ".js", ".patch"}


def source_files():
    files = ["pyproject.toml", "README.md"]
    for folder in SOURCE_FOLDERS:
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(ROOT).parts):
                continue
            if path.suffix in SOURCE_SUFFIXES or path.name == "Makefile":
                files.append(path.relative_to(ROOT).as_posix())
    return sorted(set(files))


def save(path, data):
    path.write_text(json.dumps(redact(data), indent=2), encoding="utf-8")


async def fetch_report(box, remote, destination):
    try:
        value = json.loads(await box.read_file(remote))
    except (ValueError, OSError, KeyError):
        return None
    save(destination, value)
    return value


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--image", default=IMAGE)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 50:
        raise SystemExit("batch-size must be between 1 and 50")
    load_env_file(ROOT / '.env')
    os.environ["AGENTKERNEL_SANDBOX_IMAGE"] = args.image
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'reports/product-v3' / ('full-tests-' + stamp)
    out.mkdir(parents=True, exist_ok=False)
    files = source_files()
    frozen = out / 'source'
    for name in files:
        destination = frozen / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    manifest = {
        'status': 'started', 'execution_backend': 'nebius', 'image': args.image,
        'credentials_uploaded': False, 'historical_reports_uploaded': False,
        'files': {name: hashlib.sha256((frozen / name).read_bytes()).hexdigest() for name in files},
        'selection': SELECTION, 'default_integration_exclusion_overridden': True,
        'paid_model_calls': 0, 'live_account_tests_excluded': ['nebius', 'langsmith', 'gpu'],
    }
    save(out / 'manifest.json', manifest)
    print('Remote full validation: ' + str(out), flush=True)
    environment = {'PYTHONPATH': '/workspace/src:/workspace', 'AK_REMOTE_TEST_HOST': '1'}
    reports = []
    async with NebiusSandboxBackend() as box:
        await box.upload_project(frozen, files)
        setup = await box.run_command(['python3', '-m', 'pip', 'install', '-e', '.[dev]'], timeout=110)
        save(out / 'install.json', setup.model_dump())
        if setup.exit_code != 0 or setup.timed_out:
            raise SystemExit('Remote dependency installation failed; see ' + str(out))
        collect = await box.run_command([
            'python3', '-m', 'pytest', '--collect-only', '-q', '-o', 'addopts=',
            '-p', 'scripts.remote_test_recorder', '--ak-report', 'test-inventory.json',
        ], timeout=110, environment=environment)
        save(out / 'collection-command.json', collect.model_dump())
        inventory = await fetch_report(box, 'test-inventory.json', out / 'inventory.json')
        if collect.exit_code != 0 or collect.timed_out or inventory is None:
            raise SystemExit('Remote collection failed: ' + str(out))
        modules = sorted({item['nodeid'].split('::')[0] for item in inventory['collected']})
        for start in range(0, len(modules), args.batch_size):
            index = start // args.batch_size + 1
            remote = f'test-batch-{index:02d}.json'
            command = ['python3', '-m', 'pytest', '-q', '-ra', '-o', 'addopts=', '-m', SELECTION,
                '-p', 'scripts.remote_test_recorder', '--ak-report', remote,
                '--junitxml', f'test-batch-{index:02d}.xml', *modules[start:start + args.batch_size]]
            result = await box.run_command(command, timeout=150, environment=environment)
            save(out / f'batch-{index:02d}-command.json', result.model_dump())
            report = await fetch_report(box, remote, out / f'batch-{index:02d}.json')
            try:
                (out / f'batch-{index:02d}.xml').write_text(await box.read_file(f'test-batch-{index:02d}.xml'), encoding='utf-8')
            except (ValueError, OSError, KeyError):
                pass
            reports.append(report or {'error': 'missing_remote_report', 'outcomes': []})
            print(f'Batch {index}: ' + result.stdout.strip(), flush=True)
            if result.timed_out:
                manifest['status'] = 'incomplete'
                break
        outcomes = [row for report in reports for row in report.get('outcomes', [])]
        counts = {kind: sum(row['outcome'] == kind for row in outcomes) for kind in ('passed', 'failed', 'skipped', 'error')}
        deselected = [row for report in reports for row in report.get('deselected', [])]
        collected_ids = {row['nodeid'] for row in inventory['collected']}
        accounted = {row['nodeid'] for row in outcomes + deselected}
        summary = {
            'status': 'passed' if not counts['failed'] and not counts['error'] and collected_ids == accounted else 'failed',
            'collected': len(collected_ids), **counts, 'deselected': len(deselected),
            'missing_test_ids': sorted(collected_ids - accounted), 'outcomes': outcomes,
            'excluded': deselected, 'execution_backend': 'nebius', 'paid_model_calls': 0,
        }
        save(out / 'summary.json', summary)
        manifest.update(status=summary['status'], counts={key: summary[key] for key in ('collected', 'passed', 'failed', 'skipped', 'error', 'deselected')})
        save(out / 'complete.json', manifest)
        print(json.dumps({key: value for key, value in summary.items() if key not in ('outcomes', 'excluded')}), flush=True)
        if summary['status'] != 'passed':
            raise SystemExit('Remote validation failed: ' + str(out))


if __name__ == '__main__':
    asyncio.run(main())
