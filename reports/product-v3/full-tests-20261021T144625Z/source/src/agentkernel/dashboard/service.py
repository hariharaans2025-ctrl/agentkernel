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
            fixtures.append({'id': name, 'bug': task.expected_bug_category,
                'baseline_runs': task.stress_runs, 'verification_runs': task.verification_config.stress_runs})
        return {'api_version':2, 'models': {**{tier.value: model for tier, model in models.items()}, 'ADAPTIVE':'Nano triage → Super → Ultra only after failed verification'}, 'fixtures': fixtures,
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
        if not isinstance(tiers, list) or not 1 <= len(tiers) <= 4 or any(t not in ('NANO','SUPER','ULTRA','ADAPTIVE') for t in tiers):
            raise ValueError('Choose one to three configured models')
        if len(set(tiers)) != len(tiers) or not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9-]{36}', ident):
            raise ValueError('Invalid or duplicate selection')
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
                'limits': {'max_output_tokens_per_model': OUTPUT_CAP, 'max_input_bytes_per_model': 48000,
                           'max_combined_output_tokens': sum(4864 if t=='ADAPTIVE' else OUTPUT_CAP for t in tiers), 'requests_per_model': 1},
                'note': 'Same frozen source and verification settings. Separate baseline measurements per model.',
                'results': {tier: {'status': 'queued', 'stage': 'Queued', 'model': 'Adaptive Nano / Super / Ultra' if tier == 'ADAPTIVE' else models[InferenceTier(tier)]} for tier in tiers}}
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
