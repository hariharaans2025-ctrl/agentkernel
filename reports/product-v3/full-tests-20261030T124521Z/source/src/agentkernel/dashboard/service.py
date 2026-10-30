import asyncio
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agentkernel.concurrency.app import ConcurrencyBugHunter, ConcurrencyPolicy
from agentkernel.concurrency.benchmark.loader import discover_tasks, load_task
from agentkernel.core.enums import InferenceTier
from agentkernel.observability import configured_observer
from agentkernel.observability.base import ObservabilityBackend
from agentkernel.providers.nebius_token_factory import NebiusTokenFactoryProvider
from agentkernel.telemetry.recorder import TelemetryRecorder
from agentkernel.telemetry.redaction import redact
from .metrics import OUTPUT_CAP, INPUT_BYTE_CAP, benchmark_metrics
from agentkernel.concurrency.progress import progress_sink
from agentkernel.repository.adaptive_v3 import CAPS as V4_CAPS, remote_models
from agentkernel.repository.adaptive_v4 import AdaptiveV4, V4_INPUT_CAP
from agentkernel.repository.remote_repair import quote_repair_model

TIERS = ('NANO', 'SUPER', 'ULTRA', 'ADAPTIVE', 'ADAPTIVE_V4')
V4_LABEL = 'Adaptive v4 · Nemotron Ultra + one evidence-directed Ultra correction'
V4_DATA = 'datasets/adaptive-v3/product-v1'
V4_IMAGE = 'agentkernel-clang:20261003122908'


async def live_catalog():
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get('https://api.tokenfactory.nebius.com/v1/models', params={'verbose': 'true'},
                                    headers={'Authorization': 'Bearer ' + os.environ['NEBIUS_API_KEY']})
        response.raise_for_status()
        return response.json()['data']


def v4_job(result):
    """Map an AdaptiveV4 result onto the dashboard's existing job/inference shapes; unknowns stay null."""
    attempts = result.get('attempts') or []
    def verification(summary):
        if not summary: return None
        return {'build_passed': summary.get('build_passed'), 'original_tests_passed': summary.get('original_tests_passed'),
                'passed_runs': summary.get('passed_runs'), 'total_runs': summary.get('total_runs'),
                'execution_passed': summary.get('passed_runs') == summary.get('total_runs') if summary.get('total_runs') else None,
                'semantic_passed': summary.get('semantic_passed'), 'sanitizer_passed': summary.get('tsan_passed'),
                'scheduling_hooks_preserved': summary.get('scheduling_hooks_preserved')}
    called = [a for a in attempts if a.get('model_calls')]
    inferences = [{'tier': 'ULTRA' if a.get('stage') == 'ultra' else 'SUPER', 'latency_ms': a.get('inference_ms') or 0,
                   'output_text': a.get('response'),
                   'metadata': {'actual_input_tokens': a.get('input_tokens'), 'actual_output_tokens': a.get('output_tokens'),
                                'actual_reasoning_tokens': a.get('reasoning_tokens'), 'requested_max_output_tokens': V4_CAPS.get(a.get('stage')),
                                'finish_reason': a.get('finish_reason'), 'error_code': a.get('error_code')}} for a in called]
    job = {'status': result.get('status'), 'cost_usd': result.get('cost_usd'),
           'route': [a.get('stage', '').upper() + (' (evidence correction)' if a.get('recovery') == 'verifier' else ' (format correction)' if a.get('recovery') == 'format' else '') for a in attempts],
           'verification': verification(result.get('verification')),
           'model_calls': {'ULTRA': sum(1 for a in called if a.get('stage') == 'ultra'), 'SUPER': sum(1 for a in called if a.get('stage') == 'super')},
           'repairs': [{'tier': a.get('stage', '').upper(), 'proposal': {'patch': a['patch']}, 'patch': {'success': a.get('outcome') != 'invalid_output'},
                        'false_fix': bool(a.get('false_fix')), 'verification': verification(a.get('verification'))} for a in attempts if a.get('patch')],
           'metadata': {'pricing_authoritative': result.get('cost_usd') is not None, 'final_tier': (attempts[-1].get('stage') or '').upper() if attempts else None,
                        'model_attempts': [{k: a.get(k) for k in ('stage', 'outcome', 'recovery', 'category', 'error_code', 'tokens', 'cost_usd', 'taxonomy')} for a in attempts]},
           'v4': {k: result.get(k) for k in ('route_decision', 'recoveries', 'phases_ms', 'stop_reason', 'tokens', 'end_to_end_ms', 'error')}}
    return job, inferences


def now():
    return datetime.now(timezone.utc).isoformat()


class BusyError(ValueError):
    pass


class ProgressObserver(ObservabilityBackend):
    def __init__(self, backend, update):
        self.backend, self.update = backend, update

    async def start_span(self, name, parent, metadata, run_type='chain'):
        labels = {'baseline_compile': 'Compiling baseline', 'baseline_stress_campaign': 'Reproducing bug',
                  'patch_application': 'Applying candidate', 'verification_campaign': 'Verifying in sandbox'}
        if name in labels:
            self.update(stage=labels[name])
        return await self.backend.start_span(name, parent, metadata, run_type)

    async def end_span(self, handle, metadata, error=None):
        return await self.backend.end_span(handle, metadata, error)

    async def record_feedback(self, handle, key, value):
        return await self.backend.record_feedback(handle, key, value)

    async def flush(self):
        return await self.backend.flush()


class CapturingProvider(NebiusTokenFactoryProvider):
    def __init__(self, update):
        super().__init__(max_retries=0)
        self.update, self.calls, self.inferences = update, {}, []

    async def generate(self, task, routing):
        tier = routing.selected_tier.value
        if self.calls.get(tier):
            raise ValueError('Comparison permits one inference per model')
        self.calls[tier] = 1
        metadata = {**task.metadata, 'max_output_tokens': 768 if task.metadata.get('phase') == 'triage' else OUTPUT_CAP,
                    'max_input_bytes': 48000 if task.metadata.get('bounded_concurrency') else INPUT_BYTE_CAP}
        task = task.model_copy(update={'metadata': metadata})
        self.update(stage='Requesting model', active_tier=tier, request_started_at=now())
        result = await super().generate(task, routing)
        self.inferences.append(result.model_dump(mode='json'))
        self.update(response=result.output_text, inference=result.model_dump(mode='json'),
                    inferences=self.inferences.copy(), stage='Checking response')
        return result


class DashboardService:
    def __init__(self, root, *, job_runner=None):
        self.root = Path(root).resolve()
        self.directory = self.root / 'reports/dashboard'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.runs = {}
        self.worker = None
        self.job_runner = job_runner
        self.connection = {'status': 'unchecked', 'checked_at': None}
        self.fixtures = {p.name: p for p in discover_tasks(self.root / 'benchmarks')}
        # v4 requires complete contracts (original tests, required semantics, >= 3 TSan runs): product-v1 test cases.
        manifest = self.root / V4_DATA / 'manifest.json'
        self.v4_fixtures = set()
        if manifest.is_file():
            for case in json.loads(manifest.read_text(encoding='utf-8'))['cases']:
                path = self.root / V4_DATA / 'tasks' / case['id']
                if case['split'] == 'test' and (path / 'task.json').is_file() and case['id'] not in self.fixtures:
                    self.fixtures[case['id']] = path; self.v4_fixtures.add(case['id'])
        for path in sorted(self.directory.glob('*.json')):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if data['status'] in {'queued', 'running'}:
                    data['status'] = 'interrupted'
                    data['note'] = 'Controller restarted. Requests are never automatically replayed.'
                    for item in data['results'].values():
                        if item['status'] in {'queued', 'running'}:
                            item.update(status='interrupted', stage='Interrupted')
                self.runs[data['id']] = data
                self._save(data)
            except (ValueError, KeyError, OSError):
                continue
        self._import_replay()

    def _import_replay(self):
        path = self.root / 'reports/nebius-sandbox/migration/remote-deadlock-100.json'
        if 'saved-super-replay' in self.runs or not path.exists():
            return
        try:
            job = json.loads(path.read_text())
            source = self.root / 'reports/patch-quality/paid-super-direct-100/inference.json'
            response = json.loads(source.read_text())['output_text'] if source.exists() else ''
            self.runs['saved-super-replay'] = {'id': 'saved-super-replay', 'fixture': job['task'],
                'created_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                'status': 'completed', 'provenance': 'saved_response_replay', 'tiers': ['SUPER'],
                'verification_runs': 100, 'stop_requested': False,
                'note': 'Saved Super response replayed in Nebius. No new inference; synthetic inference metrics are omitted.',
                'results': {'SUPER': {'status': 'completed', 'stage': 'Completed', 'job': job,
                    'response': response, 'model': 'Saved Nemotron Super response'}}, 'events': []}
        except (OSError, ValueError, KeyError):
            pass

    def _save(self, data):
        data['benchmark'] = benchmark_metrics(data)
        destination = self.directory / (data['id'] + '.json')
        temporary = destination.with_suffix('.tmp')
        temporary.write_text(json.dumps(redact(data), indent=2), encoding='utf-8')
        temporary.replace(destination)

    def configuration(self):
        models = NebiusTokenFactoryProvider(max_retries=0).models
        fixtures = []
        for name, path in self.fixtures.items():
            task = load_task(path)
            fixtures.append({'id': name, 'bug': task.expected_bug_category or 'concurrency',
                'baseline_runs': task.stress_runs, 'verification_runs': task.verification_config.stress_runs, 'v4': name in self.v4_fixtures})
        return {'api_version':2, 'models': {**{tier.value: model for tier, model in models.items()}, 'ADAPTIVE':'Nano triage → Super → Ultra only after failed verification', 'ADAPTIVE_V4': V4_LABEL}, 'fixtures': fixtures,
            'credentials_configured': bool(os.getenv('NEBIUS_API_KEY') and os.getenv('NEBIUS_PROJECT_ID')),
            'execution_backend': 'Nebius Sandbox', 'connection': copy.deepcopy(self.connection),
            'limits': {'requests_per_model': 1, 'retries': 0, 'escalation': False,
                       'max_output_tokens': OUTPUT_CAP, 'max_input_bytes': 48000}}

    async def check_connection(self):
        provider = NebiusTokenFactoryProvider(max_retries=0)
        catalog = await provider.check_models()
        sandbox = {'ready': False}
        try:
            from contree_sdk import Contree
            from contree_sdk.auth import IAMAuth
            from contree_sdk.config import ContreeConfig
            if not os.getenv('NEBIUS_API_KEY') or not os.getenv('NEBIUS_PROJECT_ID'):
                raise ValueError('missing_credentials')
            client = Contree(ContreeConfig(auth=IAMAuth(token=os.environ['NEBIUS_API_KEY'],
                project_id=os.environ['NEBIUS_PROJECT_ID']), transport_timeout=15))
            async with asyncio.timeout(25):
                info = await client.get_token_info()
            sandbox = {'ready': bool(info.permissions.get('spawn')), 'permissions': info.permissions}
        except Exception as exc:
            sandbox['error'] = type(exc).__name__
        with self.lock:
            self.connection = {'status': 'ready' if not catalog.error and sandbox['ready'] else 'error',
                'checked_at': now(), 'models': catalog.models, 'model_error': catalog.error, 'sandbox': sandbox}
            return copy.deepcopy(self.connection)

    def list_runs(self):
        with self.lock:
            return [copy.deepcopy(item) for item in sorted(self.runs.values(), key=lambda r: r['created_at'], reverse=True)]

    def get(self, ident):
        with self.lock:
            if ident not in self.runs:
                raise KeyError(ident)
            return copy.deepcopy(self.runs[ident])

    def start(self, request):
        if not isinstance(request, dict) or set(request) != {'fixture', 'tiers', 'client_id'}:
            raise ValueError('Choose a fixture and one to three models')
        fixture, tiers, ident = request['fixture'], request['tiers'], request['client_id']
        if not isinstance(fixture, str) or fixture not in self.fixtures:
            raise ValueError('Unknown fixture')
        if not isinstance(tiers, list) or not 1 <= len(tiers) <= 5 or any(t not in TIERS for t in tiers):
            raise ValueError('Choose one to three configured models')
        if len(set(tiers)) != len(tiers) or not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9-]{36}', ident):
            raise ValueError('Invalid or duplicate selection')
        if (fixture in self.v4_fixtures) != ('ADAPTIVE_V4' in tiers) or ('ADAPTIVE_V4' in tiers and len(tiers) != 1):
            raise ValueError('Adaptive v4 runs alone, and only on product-v1 cases with a complete verification contract')
        with self.lock:
            if ident in self.runs:
                if self.runs[ident]['fixture'] != fixture or self.runs[ident]['tiers'] != tiers:
                    raise ValueError('Request ID already used for another comparison')
                return self.get(ident)
            if any(r['status'] in {'running','queued'} for r in self.runs.values()):
                raise BusyError('A comparison is already running')
            if not os.getenv('NEBIUS_API_KEY') or not os.getenv('NEBIUS_PROJECT_ID'):
                raise ValueError('Configure private Nebius credentials before starting')
            task = load_task(self.fixtures[fixture])
            models = NebiusTokenFactoryProvider(max_retries=0).models
            data = {'id': ident, 'fixture': fixture, 'tiers': tiers, 'created_at': now(),
                'status': 'queued', 'provenance': 'real', 'verification_runs': task.verification_config.stress_runs,
                'baseline_runs': task.stress_runs, 'stop_requested': False, 'events': [],
                'limits': {'max_output_tokens_per_model': V4_CAPS['ultra'] if 'ADAPTIVE_V4' in tiers else OUTPUT_CAP,
                           'max_input_bytes_per_model': V4_INPUT_CAP if 'ADAPTIVE_V4' in tiers else 48000,
                           'max_combined_output_tokens': sum(2 * V4_CAPS['ultra'] if t == 'ADAPTIVE_V4' else 4864 if t=='ADAPTIVE' else OUTPUT_CAP for t in tiers),
                           'requests_per_model': 2 if 'ADAPTIVE_V4' in tiers else 1},
                'note': ('Adaptive v4: Ultra repair, plus one Ultra correction carrying the failed candidate and verifier evidence only if execution rejects it. '
                         'Development-seen product-v1 case; not an unseen benchmark.') if 'ADAPTIVE_V4' in tiers else
                        'Same frozen source and verification settings. Separate baseline measurements per model.',
                'results': {tier: {'status': 'queued', 'stage': 'Queued', 'model': V4_LABEL if tier == 'ADAPTIVE_V4' else 'Adaptive Nano / Super / Ultra' if tier == 'ADAPTIVE' else models[InferenceTier(tier)]} for tier in tiers}}
            self.runs[ident] = data
            self._save(data)
            self.worker = threading.Thread(target=self._work, args=(ident, task, models), daemon=False)
            self.worker.start()
            return self.get(ident)

    def stop(self, ident):
        with self.lock:
            data = self.runs[ident]
            if data['status'] not in {'queued','running'}:
                return self.get(ident)
            data['stop_requested'] = True
            self._save(data)
            return self.get(ident)

    def _update(self, ident, tier, **values):
        with self.lock:
            data = self.runs[ident]
            data['results'][tier].update(redact(values))
            if values.get('stage'):
                data['events'].append({'at': now(), 'tier': tier, 'message': values['stage']})
            self._save(data)

    def _work(self, ident, task, models):
        try:
            with tempfile.TemporaryDirectory(prefix='agentkernel-comparison-source-') as directory:
                for name in task.source_files + task.support_files:
                    from agentkernel.concurrency.sandbox.local import safe_path
                    src, dst = safe_path(task.workspace, name), safe_path(Path(directory), name)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                task = task.model_copy(update={'workspace': Path(directory)})
                with self.lock:
                    data = self.runs[ident]
                    data['source_sha256'] = {name: hashlib.sha256((Path(directory)/name).read_bytes()).hexdigest()
                                             for name in task.source_files + task.support_files}
                    data['status'] = 'running'
                    self._save(data)
                asyncio.run(self._execute(ident, task, models))
        except Exception as exc:
            with self.lock:
                data = self.runs[ident]
                data.update(status='failed', error=type(exc).__name__)
                for entry in data['results'].values():
                    if entry['status'] in {'queued', 'running'}:
                        entry.update(status='failed', stage='Execution stopped')
                self._save(data)

    async def _run_v4(self, ident, task, update, *, catalog=None, runner_factory=None):
        """Real Token Factory + Nebius Sandbox via the .env keys; bounded by the shared paid-call ledger."""
        catalog, runner_factory = catalog or live_catalog, runner_factory or AdaptiveV4
        # v4 requires TSan; only the prepared clang image has it (the CLI runner and Sites agent pin the same image).
        os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = V4_IMAGE
        rows = await catalog()
        bound = 2 * quote_repair_model(remote_models(rows)['ultra'], max_input_tokens=V4_INPUT_CAP, max_output_tokens=V4_CAPS['ultra'])
        update(stage='Reproducing bug', reserved_ceiling_usd=bound)
        runner = runner_factory(self.root, rows, on_progress=lambda d: update(stage=d['stage']) if d.get('stage') else None)
        result = await runner.run(task, self.directory / (ident + '-v4'), arm='v4', max_cost_usd=round(bound, 6))
        job, inferences = v4_job(result)
        responses = [i['output_text'] for i in inferences if i.get('output_text')]
        update(status='completed', stage='Completed', finished_at=now(), job=job, inferences=inferences,
               inference=inferences[-1] if inferences else None, response=responses[-1] if responses else None)

    async def _execute(self, ident, task, models):
        for tier in self.get(ident)['tiers']:
            if self.get(ident)['stop_requested']:
                self._update(ident, tier, status='skipped', stage='Stopped before model')
                continue
            self._update(ident, tier, status='running', stage='Starting sandbox', started_at=now())
            update = lambda **kw: self._update(ident, tier, **kw)
            provider = CapturingProvider(update)
            provider.models = models.copy()
            telemetry = TelemetryRecorder()
            token = progress_sink.set(lambda value: update(campaign_progress=value))
            try:
                if tier == 'ADAPTIVE_V4':
                    await self._run_v4(ident, task, update)
                    continue
                if self.job_runner:
                    result = await self.job_runner(task, tier, provider)
                else:
                    result = await ConcurrencyBugHunter(provider, telemetry,
                        ConcurrencyPolicy(mode='adaptive' if tier == 'ADAPTIVE' else tier.lower()+'-only', max_total_attempts=3 if tier == 'ADAPTIVE' else 1, max_super_repairs=1),
                        observer=ProgressObserver(configured_observer(), update)).run(task)
                self._update(ident, tier, status='completed', stage='Completed', finished_at=now(),
                             job=result.model_dump(mode='json'))
            except Exception as exc:
                self._update(ident, tier, status='failed', stage='Execution failed', error=type(exc).__name__,
                             detail='Remote operation failed. No local fallback or automatic model retry.', finished_at=now())
            finally:
                progress_sink.reset(token)
                telemetry.export_jsonl(self.directory / (ident+'-'+tier+'.jsonl'))
        with self.lock:
            data = self.runs[ident]
            data.update(status='stopped' if data['stop_requested'] else 'completed', finished_at=now())
            self._save(data)
