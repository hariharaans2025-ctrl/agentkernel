"""Isolated, zero-inference experiments. Never imported by production code.

Controller runs locally; all child processes and verification run on Nebius.
Evidence compression is measured in UTF-8 bytes, not claimed model tokens.
"""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

from agentkernel.config import load_env_file
from agentkernel.concurrency.analyzer.classifier import classify
from agentkernel.concurrency.benchmark.loader import load_task
from agentkernel.concurrency.campaign.manager import StressCampaignManager
from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.execution.models import ExecutionRun, RunClassification
from agentkernel.concurrency.sandbox.base import CommandResult
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend, REMOTE_RUNNER
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier

ROOT = Path(__file__).resolve().parents[1]
CONTINUATION = ROOT / 'reports/continuation-20261004T104857Z'


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    files = []
    for folder in ('src', 'benchmarks', 'reports'):
        files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and 'optimization-experiments' not in p.parts)
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in files}


def compact_evidence(value):
    """Intern repeated long strings without deleting any information.

    Reserved-key collisions are rejected, so decoding cannot alter source data.
    This is an experimental model-readable wire format, not an approved prompt.
    """
    counts = Counter()
    def scan(node):
        if isinstance(node, str):
            counts[node] += 1
        elif isinstance(node, list):
            for item in node: scan(item)
        elif isinstance(node, dict):
            if '$evidence_ref' in node:
                raise ValueError('Reserved evidence reference key')
            for item in node.values(): scan(item)
    scan(value)
    strings = [s for s, count in counts.items() if count > 1 and len(s.encode('utf-8')) >= 256]
    ids = {s: str(i) for i, s in enumerate(strings)}
    def encode(node):
        if isinstance(node, str) and node in ids: return {'$evidence_ref': ids[node]}
        if isinstance(node, list): return [encode(item) for item in node]
        if isinstance(node, dict): return {k: encode(v) for k, v in node.items()}
        return node
    return {'format': 'lossless-evidence-v1', 'strings': dict(zip(ids.values(), strings)), 'evidence': encode(value)}


def expand_evidence(envelope):
    def decode(node):
        if isinstance(node, dict) and set(node) == {'$evidence_ref'}:
            return envelope['strings'][node['$evidence_ref']]
        if isinstance(node, dict): return {k: decode(v) for k, v in node.items()}
        if isinstance(node, list): return [decode(v) for v in node]
        return node
    return decode(envelope['evidence'])


def summary(fixture):
    events = [json.loads(line) for line in (CONTINUATION / f'{fixture}-adaptive.jsonl').read_text(encoding='utf-8').splitlines()]
    return next(e['summary'] for e in reversed(events) if e.get('event_type') == 'concurrency_job')


# Reuse the exact production child runner in a remote parent. Each command still
# has its own process group, timeout, environment, output cap and cleanup.
REMOTE_BATCH = r'''
import json, subprocess, sys, datetime
payload = json.loads(sys.argv[1])
for index, spec in enumerate(payload['specs']):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    child = subprocess.run(['python3', '-c', payload['runner'], json.dumps(spec)], capture_output=True, text=True, timeout=spec['timeout'] + 10)
    if child.returncode != 0:
        raise RuntimeError('Child wrapper failed')
    result = json.loads(child.stdout)
    print(json.dumps({'index': index, 'start_time': started, 'result': result}), flush=True)
'''


async def batch_commands(box, specs):
    if not specs or len(specs) > 10:
        raise ValueError('Experimental batch requires 1..10 commands')
    budget = sum(s['timeout'] + 10 for s in specs) + 10
    if budget > 170:
        raise ValueError('Batch exceeds bounded SDK operation budget')
    started = perf_counter()
    image = await box.image.run('python3', args=['-c', REMOTE_BATCH, wire({'runner': REMOTE_RUNNER, 'specs': specs})],
                                timeout=budget, disposable=False,
                                truncate_output_at=sum(s['limit'] * 12 + 8192 for s in specs))
    if image.exit_code != 0:
        raise ValueError('Batch wrapper failed; do not replay unknown executions')
    rows = [json.loads(line) for line in image.stdout.splitlines()]
    if [row['index'] for row in rows] != list(range(len(specs))):
        raise ValueError('Incomplete batch evidence; do not replay unknown executions')
    box.image = image
    wall = (perf_counter() - started) * 1000
    for row, spec in zip(rows, specs):
        CommandResult(command=spec['command'], **row['result'])
        row['result']['metadata'].update(remote_image_id=str(image.uuid), batch_transport_wall_ms=wall)
    return rows


class RecordingCampaign(StressCampaignManager):
    def __init__(self, out, batched):
        super().__init__()
        self.out, self.batched, self.number = out, batched, 0

    async def run(self, task, sandbox, *, runs=None):
        count = task.stress_runs if runs is None else runs
        if not self.batched:
            campaign = await super().run(task, sandbox, runs=count)
        else:
            if not 1 <= count <= 10000: raise ValueError('Invalid run count')
            started, records = perf_counter(), []
            for first in range(0, count, 10):
                specs = [{'command': task.run_command, 'timeout': task.max_runtime_seconds,
                          'environment': {**task.environment, **self.schedule.environment_for(i)},
                          'limit': sandbox.output_limit} for i in range(first, min(first + 10, count))]
                rows = await batch_commands(sandbox, specs)
                for i, row in enumerate(rows, first):
                    result = CommandResult(command=task.run_command, **row['result'])
                    kind = classify(result, task.expected_behavior)
                    records.append(ExecutionRun(run_id=f'{task.task_id}:{i + 1}', start_time=row['start_time'],
                        duration_ms=result.duration_ms, exit_code=result.exit_code, stdout=result.stdout,
                        stderr=result.stderr, timed_out=result.timed_out,
                        crashed=kind == RunClassification.CRASH,
                        sanitizer_detected=kind in {RunClassification.RACE_DETECTED, RunClassification.SANITIZER_FAILURE},
                        classification=kind, metadata=result.metadata))
                print(f'Batched campaign {first + len(rows)}/{count}', flush=True)
            campaign = CampaignResult(task_id=task.task_id, runs=records, requested_runs=count,
                counts=dict(Counter(r.classification.value for r in records)), duration_ms=(perf_counter()-started)*1000)
        self.number += 1
        (self.out / f'campaign-{self.number}.json').write_text(campaign.model_dump_json(indent=2), encoding='utf-8')
        return campaign


def compression_experiment(out):
    rows = []
    for fixture in sorted(p.name for p in (ROOT / 'benchmarks').iterdir() if (p / 'task.json').exists()):
        data = summary(fixture)
        # Stored context corpus, not a reconstruction of unavailable exact prompts.
        context = {'baseline': data['baseline'], 'triage': data['triage'],
                   'attempts': data['metadata'].get('attempt_details', [])}
        packed = compact_evidence(context)
        if expand_evidence(packed) != context: raise ValueError('Evidence round-trip mismatch')
        original = len(json.dumps(context, ensure_ascii=False).encode('utf-8'))
        compact = len(wire(packed).encode('utf-8'))
        minified = len(wire(context).encode('utf-8'))
        rows.append({'fixture': fixture, 'original_bytes': original, 'minified_bytes': minified,
                     'deduplicated_bytes': compact, 'round_trip_equal': True})
        (out / f'{fixture}-evidence.json').write_text(wire(packed), encoding='utf-8')
    (out / 'compression.json').write_text(json.dumps({'unit': 'utf8_bytes_not_tokens', 'rows': rows}, indent=2), encoding='utf-8')
    return rows


async def edge_checks(box, out):
    codes = ["print('unicode: \\u03bb')", 'raise SystemExit(7)',
             'import time; time.sleep(2)', "import sys; print('x'*70000); print('y'*70000, file=sys.stderr)"]
    specs = [{'command': ['python3', '-c', c], 'timeout': .2 if i == 2 else 2,
              'environment': {}, 'limit': box.output_limit} for i, c in enumerate(codes)]
    singles = [await box.run_command(s['command'], timeout=s['timeout']) for s in specs]
    batched = await batch_commands(box, specs)
    keys = ('exit_code', 'timed_out', 'stdout', 'stderr')
    for single, row in zip(singles, batched):
        if any(single.model_dump()[k] != row['result'][k] for k in keys):
            raise ValueError('Batch edge-case fidelity mismatch')
        if single.metadata.get('output_truncated') != row['result']['metadata'].get('output_truncated'):
            raise ValueError('Output truncation mismatch')
    (out / 'edge-checks.json').write_text(json.dumps({'passed': True, 'cases': ['unicode', 'nonzero_exit', 'timeout', 'output_caps'],
        'single': [s.model_dump() for s in singles], 'batch': batched}, indent=2), encoding='utf-8')


async def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'reports/optimization-experiments' / stamp
    out.mkdir(parents=True, exist_ok=False)
    print('Experiment evidence: ' + str(out), flush=True)
    before = snapshot()
    (out / 'preserved-sha256.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    expected = json.loads((ROOT / 'reports/combined-view-20261004/evidence-sha256.json').read_text(encoding='utf-8'))
    if any(digest(ROOT / 'reports' / name) != value for name, value in expected.items()):
        raise ValueError('Frozen evidence integrity mismatch')
    rows = compression_experiment(out)
    results = {}
    try:
        load_env_file(ROOT / '.env')
        os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-clang:20261003122908'
        task = load_task(ROOT / 'benchmarks/race_002')
        candidate = summary('race_002')['metadata']['attempt_details'][0]['verification_evidence']['candidate_sources']
        assert task.verification_config.stress_runs == 100 and task.verification_config.sanitizer_runs == 3
        assert task.verification_config.sanitizer_required
        (out / 'plan.json').write_text(json.dumps({'version': 'optimization-v1', 'model_calls': 0,
            'fixture': task.task_id, 'candidate_origin': 'preserved adaptive Super repair',
            'candidate_sha256': {k: hashlib.sha256(v.encode()).hexdigest() for k,v in candidate.items()},
            'image': os.environ['AGENTKERNEL_SANDBOX_IMAGE'], 'batch_size': 10,
            'verification_configuration': task.verification_config.model_dump(),
            'limitations': ['One fixture, single serial-then-batch pair; order and service load confounded.',
                             'Batch shares one remote instance per chunk; scheduling environment may differ.',
                             'Compression measurements are evidence bytes, not exact prompt/model token counts.']}, indent=2), encoding='utf-8')
        for arm in ('serial', 'batch'):
            arm_out = out / arm
            arm_out.mkdir()
            print('Starting ' + arm + ' full verification', flush=True)
            async with NebiusSandboxBackend() as box:
                await box.upload_project(task.workspace, task.source_files + task.support_files)
                await box._upload({'/workspace/' + k: v.encode('utf-8') for k,v in candidate.items()})
                if arm == 'serial': await edge_checks(box, out)
                verified = await ConcurrencyVerifier(campaigns=RecordingCampaign(arm_out, arm == 'batch')).verify_workspace(task, box)
                results[arm] = verified.model_dump(mode='json')
                (arm_out / 'verification.json').write_text(json.dumps(results[arm], indent=2), encoding='utf-8')
                print(f'{arm}: passed={verified.passed}, stress={verified.passed_runs}/{verified.total_runs}, ms={verified.duration_ms:.0f}', flush=True)
                if verified.infrastructure_failures: raise ValueError('Infrastructure failure; stopping without retry')
    except Exception as exc:
        (out / 'error.json').write_text(json.dumps({'type': type(exc).__name__, 'message': 'Experiment stopped; no automatic retry or model calls.'}), encoding='utf-8')
        raise
    finally:
        unchanged = before == snapshot()
        (out / 'integrity.json').write_text(json.dumps({'preserved_files': len(before), 'unchanged': unchanged}), encoding='utf-8')
        original, packed = sum(r['original_bytes'] for r in rows), sum(r['deduplicated_bytes'] for r in rows)
        report = ['# Optimization experiment v1', '', f'Model calls: 0. Frozen source/evidence unchanged: {unchanged}.',
                  f'Evidence corpus: {original:,} -> {packed:,} UTF-8 bytes ({100*(1-packed/original):.1f}% smaller).',
                  'All 10 evidence records round-trip exactly. This is not a measured token or repair-quality improvement.', '',
                  '| Arm | Verified | Stress passed | Semantics | TSan | Full verification seconds |',
                  '|---|---:|---:|---:|---:|---:|']
        for arm, r in results.items():
            report.append(f"| {arm} | {r['passed']} | {r['passed_runs']}/{r['total_runs']} | {r['semantic_passed']} | {r['sanitizer_passed']} | {r['duration_ms']/1000:.3f} |")
        report.extend(['', 'Single saved race_002 repair, serial then batch. Order/service-load effects are uncontrolled; no suite-wide speedup or semantic equivalence claim.',
                       'Batch size 10; distinct subprocesses and unchanged seeds, run counts, timeouts, output limits, oracle and TSan requirements. Instance lifetime differs.',
                       'No production integration, prompt replacement, routing change or paid model inference. Conditional Nano routing remains deferred.'])
        (out / 'REPORT.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
        if not unchanged: raise ValueError('Preserved files changed during experiment')


if __name__ == '__main__':
    asyncio.run(main())
