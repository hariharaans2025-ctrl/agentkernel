"""Product workflow boundaries with fake I/O and the real acceptance verifier.

No model API, compiler, or repository program is executed by these tests. The
entire pytest suite itself is run in Nebius by scripts/push_sandbox.py.
"""
import asyncio
from collections import Counter
import json
from pathlib import Path
import shutil

import httpx
import pytest

from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.campaign.scheduler import StressSchedule
from agentkernel.concurrency.execution.models import ExecutionRun, RunClassification
from agentkernel.concurrency.models import ConcurrencyTask, SemanticCheck, VerificationConfig
from agentkernel.concurrency.repair.patch_applier import UnifiedDiffApplier
from agentkernel.concurrency.sandbox.base import CommandResult
from agentkernel.repository import adaptive_v3, product_campaign
from agentkernel.repository.adaptive_v3 import ProductRepair
from agentkernel.repository.budget import BudgetLedger

SUPER = 'nvidia/nemotron-3-super-120b-a12b'
ULTRA = 'nvidia/Nemotron-3-Ultra-550b-a55b'
SOURCE = 'int value = 0;\nvoid work(void) { sched_yield(); value++; }\n'
HEADER = 'void work(void);\n'
ORACLE = 'PROTECTED_ORACLE_PRIVATE_SENTINEL\n'


def model_catalog():
    return [{'id': identifier, 'context_length': 128000,
             'pricing': {'prompt': '.000001', 'completion': '.000003', 'request': '.001'}}
            for identifier in (SUPER, ULTRA)]


def edits():
    # The comment marks a candidate for fake command results. It is never a
    # real repair claim; these tests exercise routing and admission machinery.
    return json.dumps({'edits': [{'file': 'solution.c', 'start_line': 2, 'end_line': 2,
        'replacement_lines': ['void work(void) { sched_yield(); value++; /* FIX */ }']}]})


class Harness:
    def __init__(self, tmp_path, monkeypatch):
        self.root = tmp_path
        self.workspace = tmp_path / 'repository'
        self.workspace.mkdir()
        # The fake upload checks exact bytes, so fixtures must retain LF on Windows.
        (self.workspace / 'solution.c').write_text(SOURCE, newline='')
        (self.workspace / 'state.h').write_text(HEADER, newline='')
        (self.workspace / 'oracle.c').write_text(ORACLE, newline='')
        self.task = ConcurrencyTask(task_id='runtime-boundary', workspace=self.workspace,
            source_files=['solution.c'], support_files=['state.h', 'oracle.c'],
            build_command=['gcc', 'solution.c', 'oracle.c', '-o', 'app'], run_command=['./app'],
            max_runtime_seconds=2,
            verification_config=VerificationConfig(stress_runs=100, required_original_tests=True,
                original_test_commands=[['./app']], sanitizer_enabled=True, sanitizer_required=True,
                sanitizer_runs=3, sanitizer_compiler='clang',
                semantic_checks=[SemanticCheck(name='Protected retained-work invariant',
                    build_command=['gcc', 'solution.c', 'oracle.c', '-o', 'semantic'],
                    run_command=['./semantic'])]),
            metadata={'description': 'Repair the observed concurrency bug; retain all work.'})
        self.payloads, self.uploads, self.commands, self.campaigns = [], [], [], []
        self.responses = [edits()]
        self.baseline_tsan_only = False
        self.tsan_unavailable = False
        self.fail_candidate_build = False
        self.short_stress = False
        self.on_request = None
        self.box_count = 0
        self.ledger = BudgetLedger(tmp_path / 'ledger.json')
        self.ledger.initialize(total_usd=1, authorization='fake-test-only')
        outer = self

        class FakeBox:
            output_limit = 65536

            def __init__(self, **unused):
                self.workspace = outer.root / ('box-' + str(outer.box_count))
                outer.box_count += 1
                self.workspace.mkdir()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *unused):
                return None

            async def upload_project(self, source, files):
                captured = {}
                for name in files:
                    target = self.workspace / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(Path(source) / name, target)
                    captured[name] = target.read_bytes().decode('utf-8')
                outer.uploads.append({'root': Path(source), 'files': captured})

            async def read_file(self, name):
                return (self.workspace / name).read_bytes().decode('utf-8')

            async def apply_patch(self, patch, allowed_files):
                return UnifiedDiffApplier().apply(self.workspace, patch, allowed_files)

            async def run_command(self, command, *, timeout, environment=None):
                outer.commands.append(list(command))
                is_candidate = '/* FIX */' in (self.workspace / 'solution.c').read_text()
                compile_command = command[0] in ('gcc', 'clang')
                failed = outer.fail_candidate_build and is_candidate and compile_command
                stdout = 'SEMANTIC_PASS' if command == ['./semantic'] else ('PASS' if command == ['./app'] else '')
                return CommandResult(command=command, exit_code=1 if failed else 0,
                    stdout=stdout, stderr='fake compiler rejected candidate' if failed else '', duration_ms=1)

        class FakeCampaign:
            def __init__(self, out):
                self.baseline = Path(out).name == 'baseline'

            async def run(self, task, box, *, runs=None):
                count = task.stress_runs if runs is None else runs
                tsan = 'TSAN_OPTIONS' in task.environment
                failure = self.baseline and (tsan or not outer.baseline_tsan_only)
                unavailable = self.baseline and tsan and outer.tsan_unavailable
                if outer.short_stress and not self.baseline and count == 100:
                    count = 99
                kind = (RunClassification.SANITIZER_FAILURE if unavailable else
                        RunClassification.RACE_DETECTED if failure and tsan else
                        RunClassification.POSSIBLE_DEADLOCK if failure else RunClassification.PASS)
                stderr = ('FATAL: ThreadSanitizer: unexpected memory mapping 0x1234' if unavailable else
                          'WARNING: ThreadSanitizer: data race\n work solution.c:2' if failure and tsan else '')
                records = [ExecutionRun(run_id=f'{task.task_id}:{i+1}', duration_ms=1,
                    exit_code=66 if failure or unavailable else 0,
                    stdout='' if failure else 'PASS', stderr=stderr, timed_out=failure and not tsan,
                    crashed=False, sanitizer_detected=tsan and failure, classification=kind)
                    for i in range(count)]
                outer.campaigns.append({'baseline': self.baseline, 'tsan': tsan, 'count': count})
                return CampaignResult(task_id=task.task_id, runs=records, requested_runs=runs,
                    counts=dict(Counter(r.classification.value for r in records)), duration_ms=count)

        original_client = httpx.AsyncClient

        async def handler(request):
            payload = json.loads(request.content)
            outer.payloads.append(payload)
            if outer.on_request:
                value = outer.on_request(payload)
                if asyncio.iscoroutine(value):
                    await value
            supplied = outer.responses.pop(0)
            data = supplied if isinstance(supplied, dict) else {
                'model': payload['model'], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20},
                'choices': [{'finish_reason': 'stop', 'message': {'content': supplied}}],
            }
            return httpx.Response(200, json=data)

        monkeypatch.setenv('NEBIUS_API_KEY', 'fake-test-key')
        monkeypatch.setattr(adaptive_v3, 'NebiusSandboxBackend', FakeBox)
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs))
        self.runner = ProductRepair(tmp_path, model_catalog(), ledger=self.ledger,
            campaign_factory=FakeCampaign)

    def run(self, **kwargs):
        return asyncio.run(self.runner.run(self.task, self.root / 'run', max_cost_usd=1, **kwargs))


def test_invalid_super_escalates_once_ultra_verified_and_never_calls_after_success(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.responses = ['{}', edits()]
    result = h.run()
    assert result['status'] == 'verified'
    assert [p['model'] for p in h.payloads] == [SUPER, ULTRA]
    assert [a['outcome'] for a in result['attempts']] == ['invalid_output', 'verified']
    assert result['model_calls'] == result['remote_model_calls'] == 2
    assert result['tokens'] == 240 and result['cost_usd'] == pytest.approx(.00232)
    assert result['verification']['passed_runs'] == result['verification']['total_runs'] == 100
    assert result['verification']['original_tests_passed'] and result['verification']['semantic_passed']
    assert result['verification']['tsan_passed']
    assert h.campaigns[-2:] == [{'baseline': False, 'tsan': False, 'count': 100},
                               {'baseline': False, 'tsan': True, 'count': 3}]
    assert (h.workspace / 'solution.c').read_text() == SOURCE
    assert (h.workspace / 'oracle.c').read_text() == ORACLE


@pytest.mark.parametrize('profile,identifier',[('super_only',SUPER),('ultra_only',ULTRA)])
def test_matched_single_model_arms_never_call_the_other_model(tmp_path,monkeypatch,profile,identifier):
    h=Harness(tmp_path,monkeypatch)
    result=h.run(profile=profile,max_calls=1)
    assert [p['model'] for p in h.payloads]==[identifier]
    assert result['status']=='verified' and result['model_calls']==1
    assert result['verification']['passed_runs']==100
    assert result['verification']['tsan_passed'] is True


def test_first_verified_super_stops_without_an_ultra_request(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    result = h.run()
    assert result['status'] == 'verified'
    assert len(h.payloads) == len(h.ledger.snapshot()['calls']) == 1
    assert h.payloads[0]['model'] == SUPER


def test_unknown_paid_usage_stops_and_retains_full_reservation(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.responses = [{'model': SUPER, 'choices': [{'finish_reason': 'stop', 'message': {'content': edits()}}]}]
    result = h.run()
    assert result['status'] == 'unknown'
    assert len(h.payloads) == 1 and h.box_count == 1
    assert result['tokens'] is None and result['cost_usd'] is None
    ledger = h.ledger.snapshot()
    assert ledger['calls'][0]['status'] == 'unknown'
    assert ledger['committed_usd'] == pytest.approx(result['reserved_usd'])
    assert ledger['remaining_usd'] == pytest.approx(1 - result['reserved_usd'])


def test_baseline_tsan_race_evidence_reaches_model_without_protected_oracle_source(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.baseline_tsan_only = True
    result = h.run()
    assert result['status'] == 'verified'
    prompt = json.dumps(h.payloads[0]['messages'])
    assert 'ThreadSanitizer: data race' in prompt and 'RACE_DETECTED' in prompt
    assert ORACLE.strip() not in prompt
    assert HEADER.strip() in prompt and 'Protected retained-work invariant' in prompt


def test_unavailable_baseline_tsan_stops_before_any_paid_request(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.baseline_tsan_only = h.tsan_unavailable = True
    result = h.run()
    assert result['status'] == 'unknown'
    assert not h.payloads and not h.ledger.snapshot()['calls']


def test_source_snapshot_is_unchanged_when_caller_workspace_changes_during_inference(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)

    def external_edit(payload):
        (h.workspace / 'solution.c').write_text('EXTERNAL_CHANGE_AFTER_REVIEW\n')
        (h.workspace / 'oracle.c').write_text('EXTERNAL_ORACLE_CHANGE\n')

    h.on_request = external_edit
    result = h.run()
    assert result['status'] == 'verified'
    assert h.uploads[0]['root'] != h.workspace
    assert {row['root'] for row in h.uploads} == {h.uploads[0]['root']}
    assert all(row['files']['solution.c'] == SOURCE and row['files']['oracle.c'] == ORACLE for row in h.uploads)
    assert (h.workspace / 'solution.c').read_text() == 'EXTERNAL_CHANGE_AFTER_REVIEW\n'


@pytest.mark.parametrize('failure', ['fresh_build', 'missing_stress_run'])
def test_incomplete_acceptance_gate_never_becomes_verified(tmp_path, monkeypatch, failure):
    h = Harness(tmp_path, monkeypatch)
    h.responses = [edits(), edits()]
    h.fail_candidate_build = failure == 'fresh_build'
    h.short_stress = failure == 'missing_stress_run'
    result = h.run()
    assert result['status'] == 'rejected'
    assert all(a['outcome'] == 'rejected' for a in result['attempts'])
    assert result['false_fix']


def test_cancellation_after_paid_request_keeps_unknown_reservation_and_records_stop(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)

    async def run():
        started = asyncio.Event()

        async def wait_forever(payload):
            started.set()
            await asyncio.Event().wait()

        h.on_request = wait_forever
        running = asyncio.create_task(h.runner.run(h.task, h.root / 'run', max_cost_usd=1))
        await asyncio.wait_for(started.wait(), timeout=5)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    asyncio.run(run())
    recorded = json.loads((h.root / 'run/result.json').read_text())
    assert recorded['status'] == 'unknown' and recorded['tokens'] is None and recorded['cost_usd'] is None
    ledger = h.ledger.snapshot()
    assert len(h.payloads) == 1 and ledger['calls'][0]['status'] == 'unknown'
    assert ledger['committed_usd'] == pytest.approx(recorded['reserved_usd'])


@pytest.mark.parametrize('change', ['few_stress', 'missing_original_test', 'missing_semantics', 'no_tsan', 'few_tsan', 'allowed_race'])
def test_weak_verification_contract_fails_before_baseline_or_inference(tmp_path, monkeypatch, change):
    h = Harness(tmp_path, monkeypatch)
    config = h.task.verification_config
    if change == 'few_stress': config.stress_runs = 99
    if change == 'missing_original_test': config.original_test_commands = []
    if change == 'missing_semantics': config.semantic_checks = []
    if change == 'no_tsan': config.sanitizer_required = False
    if change == 'few_tsan': config.sanitizer_runs = 2
    if change == 'allowed_race': config.allowed_races = 1
    with pytest.raises(ValueError): h.run()
    assert not h.uploads and not h.payloads and not (h.root / 'run').exists()


def test_40_run_transport_batch_preserves_standard_per_run_schedule(tmp_path, monkeypatch):
    source = tmp_path / 'solution.c'
    source.write_text(SOURCE)
    task = ConcurrencyTask(task_id='scheduled', workspace=tmp_path, source_files=['solution.c'],
        build_command=['gcc', 'solution.c', '-o', 'app'], run_command=['./app'],
        environment={'EXPLICIT_TEST_SETTING': 'retained'}, max_runtime_seconds=2)
    batches = []

    async def batch(box, specs):
        batches.append(specs)
        return [{'index': index, 'start_time': '2026-10-12T00:00:00+00:00',
                 'result': {'exit_code': 0, 'timed_out': False, 'stdout': 'PASS', 'stderr': '',
                            'duration_ms': 1, 'metadata': {'execution_backend': 'fake'}}}
                for index in range(len(specs))]

    monkeypatch.setattr(product_campaign, 'remote_batch', batch)
    box = type('FakeRemote', (), {'output_limit': 65536})()
    result = asyncio.run(product_campaign.ProductCampaign(tmp_path / 'journal').run(task, box, runs=83))
    assert [len(items) for items in batches] == [40, 40, 3]
    assert result.requested_runs == len(result.runs) == 83 and result.counts == {'PASS': 83}
    schedule = StressSchedule()
    flattened = [spec for items in batches for spec in items]
    assert [spec['environment'] for spec in flattened] == [
        {**task.environment, **schedule.environment_for(index)} for index in range(83)]
    assert all(spec['command'] == task.run_command and spec['timeout'] == task.max_runtime_seconds for spec in flattened)
    assert [run.run_id for run in result.runs] == [f'scheduled:{index+1}' for index in range(83)]
    assert len(list((tmp_path / 'journal').glob('*-started.json'))) == 3
