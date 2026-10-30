"""Outbound owner-private Sites bridge. Never executes repository commands on the host."""
import argparse
from contextlib import contextmanager
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
from agentkernel.config import load_env_file
from agentkernel.repository.onboarding import create_plan, RepositoryContract
from agentkernel.repository.learning import require_verified
from agentkernel.repository.specialist import artifact_ready, active_root
from agentkernel.repository.adaptive import AdaptiveRepair, ADAPTIVE_ID, route_quote
from agentkernel.repository.adaptive_v3 import CAPS as V4_CAPS, remote_models
from agentkernel.repository.adaptive_v4 import AdaptiveV4, ROUTE_ID as V4_ID
from agentkernel.repository.remote_repair import quote_repair_model
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.repair.prompts import SYSTEM_PROMPT, repair_prompt
from agentkernel.concurrency.repair.patch_parser import parse_repair
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.providers.nebius_token_factory import DEFAULT_MODELS
from verify_saved_super_candidate import JournalCampaign

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://api.tokenfactory.nebius.com/v1'
SITE = 'https://agentkernel-control.abuzzleaf32.chatgpt.site'
IMAGE = 'agentkernel-clang:20261003122908'
QWEN = 'Qwen/Qwen3-30B-A3B-Instruct-2507'
OUTPUT_CAP = 2048
PILOT_BALANCE = 9.90  # Conservative reserve after the separately recorded earlier pilot calls.
V4_INPUT_CAP, V4_TOTAL_CAP, V4_CALLS = 12000, 36288, 2


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def single_agent(directory):
    """Hold an OS lock so two agents cannot spend against separate ledger views."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'agent.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('A connection agent is already running for this workspace.') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def safe_subdirectory(root, value):
    if not isinstance(value, str) or '\\' in value or ':' in value or value.startswith('/'):
        raise ValueError('Invalid project subdirectory')
    if value and any(p in ('', '.', '..') or p.startswith('.') for p in value.split('/')):
        raise ValueError('Subdirectory must be an explicit relative path')
    result = (root / value).resolve(strict=True)
    if not result.is_relative_to(root.resolve()) or not result.is_dir():
        raise ValueError('Subdirectory is outside the repository')
    return result


def model_quote(row):
    pricing = row['pricing']
    rates = [Decimal(str(pricing[k])) for k in ('prompt', 'completion')]
    request = Decimal(str(pricing.get('request', '0')))
    context = row['context_length']
    if type(context) is not int or not OUTPUT_CAP < context <= 10_000_000:
        raise ValueError('Unknown model context limit')
    if any(not r.is_finite() or r < 0 for r in rates + [request]):
        raise ValueError('Invalid model pricing')
    return float(rates[0] * min(context - OUTPUT_CAP, 48000) + rates[1] * OUTPUT_CAP + request)


class Agent:
    def __init__(self, state_dir=None):
        self.home = state_dir or ROOT / 'reports/sites-console'
        self.home.mkdir(parents=True, exist_ok=True)
        path = self.home / 'state.json'
        self.state = read(path) if path.exists() else {'repositories': [], 'runs': [], 'completed': []}
        self.models = []
        self.catalog_rows = []
        self.last_error = None
        # An interrupted paid request is never replayed, even if its response was lost.
        for run in self.state['runs']:
            if run['status'] == 'running':
                run.update(status='unknown', stage='Interrupted; no automatic replay', error='Agent stopped before a final outcome was recorded.')
        self.persist()

    def persist(self):
        save(self.home / 'state.json', self.state)

    def remaining(self):
        outside=0
        if self.home.resolve()==(ROOT/'reports/sites-console').resolve():
            for protocol in (ROOT/'reports/adaptive-v2').glob('evaluation-*/protocol.json'):
                completed=protocol.parent/'complete.json'
                data=read(completed) if completed.exists() else None
                outside+=data['remote_inference_cost_usd'] if data and data.get('all_costs_known') else read(protocol)['max_total_remote_inference_usd']
        return max(0, PILOT_BALANCE - outside - sum(r.get('cost_usd') if r.get('cost_usd') is not None else r.get('reserved_usd', 0) for r in self.state['runs']))

    async def catalog(self):
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(BASE + '/models', params={'verbose': 'true'}, headers={'Authorization': 'Bearer ' + os.environ['NEBIUS_API_KEY']})
            response.raise_for_status()
        choices = {QWEN: 'Qwen 3 - Efficient', **{os.environ.get(f'AGENTKERNEL_NEMOTRON_{tier.value}_MODEL', mid): 'Nemotron ' + tier.value.title() for tier, mid in DEFAULT_MODELS.items()}}
        found = []
        for row in response.json()['data']:
            if row['id'] not in choices:
                continue
            try:
                quote = model_quote(row)
            except (KeyError, ValueError, TypeError):
                continue
            found.append({**row, 'name': choices[row['id']], 'bound_usd': quote})
        self.models = sorted(found, key=lambda m: (m['id'] != QWEN, m['bound_usd']))
        self.catalog_rows = response.json()['data']
        try:
            # Uncalibrated v4 routes to Ultra, with at most one evidence-directed Ultra correction.
            ultra = remote_models(self.catalog_rows)['ultra']
            bound = V4_CALLS * quote_repair_model(ultra, max_input_tokens=V4_INPUT_CAP, max_output_tokens=V4_CAPS['ultra'])
            self.models.insert(0, {'id': V4_ID, 'name': 'Adaptive v4 | Evidence-routed Nemotron Ultra',
                                   'bound_usd': bound, 'max_calls': V4_CALLS, 'mode': 'adaptive_v4'})
        except (KeyError, ValueError, TypeError):
            pass
        if artifact_ready(active_root(ROOT)):
            try:
                bound=route_quote(found)
                self.models.insert(0,{'id':ADAPTIVE_ID,'name':'Adaptive v2 | Fine-tuned > Super > Ultra',
                    'bound_usd':bound,'max_calls':3,'mode':'adaptive','trained':True})
            except ValueError:
                pass
        self.last_error = None if found else 'No configured models with verifiable live prices are available.'

    def add_repository(self, root, contract, origin, revision):
        identifier = uuid.uuid4().hex
        home = self.home / 'repositories' / identifier
        home.mkdir(parents=True)
        row = {'id': identifier, 'root': str(root), 'name': root.name, 'origin': origin, 'revision': revision, 'ready': False, 'language': 'C / C++', 'files': []}
        self.state['repositories'].append(row)
        if contract:
            self.configure(row, contract)
        self.persist()
        return row

    def configure(self, row, contract):
        home = self.home / 'repositories' / row['id'] / ('contract-' + uuid.uuid4().hex)
        home.mkdir(parents=True)
        RepositoryContract.model_validate(contract)
        save(home / 'contract.json', contract)
        plan = create_plan(Path(row['root']), home / 'contract.json', home / 'plan')
        row.update(name=contract['project'], description=contract['description'], ready=True, contract=plan['contract'],
                   files=[{'name': name, **entry} for name, entry in plan['files'].items()],
                   upload_bytes=plan['upload_bytes'], plan_sha256=plan['plan_sha256'], plan_path=str(home / 'plan/plan.json'))
        row.pop('error', None)
        self.persist()

    def seed(self):
        if self.state['repositories']:
            return
        folder = ROOT / 'examples/job-queue-service'
        contract = read(folder / 'agentkernel.repository.json')
        # New console budgets only; no original example or frozen plan is modified.
        contract['budgets'].update(max_model_calls=1, max_input_tokens_per_call=48000, max_total_tokens=50048, max_output_tokens_per_call=2048)
        self.add_repository(folder, contract, 'Connected workspace - synthetic example', 'content-hashed')
        history = ROOT / 'reports/prompting-generalization/20261011T103149Z/plan.json'
        original = read(history)['jobs'][0]['task'] if history.is_file() else None
        if original is None or not Path(original['workspace']).is_dir():
            fixture = ROOT / 'tests/fixtures/sites-seed'
            original = {**read(fixture / 'task.json'), 'workspace': str(fixture / 'pair_snapshot')}
        config = {k: original[k] for k in ['source_files', 'support_files', 'build_command', 'run_command', 'binary_path', 'expected_behavior']}
        config.update(schema_version=1, project='pair-snapshot', description='Two shared values must be read as one consistent snapshot. Protected tests exercise concurrent readers and writers.', origin='synthetic_example', verification=original['verification_config'], budgets={'max_model_calls': 1, 'max_total_tokens': 50048, 'max_input_tokens_per_call': 48000, 'max_output_tokens_per_call': 2048})
        self.add_repository(Path(original['workspace']), config, 'Connected workspace - synthetic example', 'content-hashed')

    def seed_adaptive_cases(self):
        model_root=active_root(ROOT)
        if not artifact_ready(model_root):
            return
        metadata=read(model_root/'started.json')
        dataset=Path(metadata['dataset'].replace('\\', '/'))
        if not dataset.is_absolute():dataset=ROOT/dataset
        tests=ROOT/read(dataset/'manifest.json')['test_source']
        existing={r['name'] for r in self.state['repositories']}
        for case in read(tests/'manifest.json')['cases']:
            name=case['id'];folder=tests/name
            if name not in existing and (folder/'agentkernel.repository.json').exists():
                self.add_repository(folder,read(folder/'agentkernel.repository.json'),
                    'Fine-tuned adaptive pilot - held-out synthetic program','content-hashed')

    async def connect(self, command):
        url = command.get('url', '')
        if not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+/?', url):
            raise ValueError('Only public github.com repository URLs are supported')
        identifier = uuid.uuid4().hex
        checkout = self.home / 'checkouts' / identifier
        checkout.parent.mkdir(exist_ok=True)
        # Git downloads files only. No submodules, hooks, builds, or repository programs run locally.
        with tempfile.TemporaryDirectory() as isolated:
            environment = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_TERMINAL_PROMPT': '0', 'GIT_LFS_SKIP_SMUDGE': '1', 'HOME': isolated}
            proc = await asyncio.create_subprocess_exec('git', '-c', 'core.hooksPath=' + isolated, '-c', 'protocol.file.allow=never', 'clone', '--depth', '1', '--no-recurse-submodules', '--', url, str(checkout), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment)
            try:
                await asyncio.wait_for(proc.communicate(), timeout=90)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise ValueError('Repository download timed out') from None
            if proc.returncode:
                raise ValueError('Repository download failed. Check that it is public and the URL is correct.')
            root = safe_subdirectory(checkout, command.get('subdir', ''))
            head = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True, env=environment).stdout.strip()
        config = root / 'agentkernel.repository.json'
        if config.is_symlink() or (config.exists() and config.stat().st_size > 65536):
            raise ValueError('Invalid repository manifest')
        row = self.add_repository(root, None, url, head)
        if config.exists():
            try:
                self.configure(row, read(config))
            except (ValueError, OSError):
                row['error'] = 'The manifest did not pass validation. Add a valid verification contract.'
        self.persist()

    def experiments(self):
        result = []
        for folder, title in [('prompting-pilot/20261011T052135Z', 'Prompting pilot - 2 held-out programs'), ('prompting-generalization/20261011T103149Z', 'Frozen prompt - 4 additional programs')]:
            path = ROOT / 'reports' / folder / 'results.json'
            if not path.exists():
                continue
            data = read(path)
            rows = data.get('jobs', [])
            if not rows:
                continue
            table = []
            for arm in ('zero_shot', 'few_shot'):
                subset = [r for r in rows if r.get('arm') == arm]
                table.append(['Without examples' if arm == 'zero_shot' else 'With training examples', f"{sum(r['outcome'] == 'verified' for r in subset)} / {len(subset)}", sum(bool(r.get('false_fix')) for r in subset), f"{sum(r.get('tokens') or 0 for r in subset):,}", f"{sum(r.get('end_to_end_ms') or 0 for r in subset)/1000:.2f} s"])
            result.append({'title': title, 'label': 'QWEN 3 - MANDATORY VERIFIER', 'columns': ['Prompt arm', 'Verified', 'False fixes', 'Tokens', 'Total latency'], 'rows': table, 'note': 'One attempt per program and arm. Same output cap and verification. These are small-suite measurements, not evidence of statistical superiority.'})
        evaluations=sorted((ROOT/'reports/adaptive-v2').glob('evaluation-*/complete.json'))
        if evaluations:
            latest=evaluations[-1].parent
            data=read(latest/'results.json');protocol=read(latest/'protocol.json')
            table=[]
            for arm,label in [('base','Base specialist'),('fine_tuned','LoRA specialist'),('adaptive','Adaptive with fallback')]:
                rows=[r for r in data['rows'] if r['arm']==arm]
                table.append([label,f"{sum(r['status']=='verified' for r in rows)} / {len(rows)}",
                    sum(bool(a.get('false_fix')) for r in rows for a in r['attempts']),
                    'Unknown' if any(r.get('tokens') is None for r in rows) else f"{sum(r['tokens'] for r in rows):,}",
                    'Unknown' if any(r['cost_usd'] is None for r in rows) else f"${sum(r['cost_usd'] for r in rows):.6f}"])
            result.append({'title':'Fine-tuned specialist · adaptive comparison','label':'REAL LOCAL LORA · INDEPENDENT SANDBOX VERIFICATION',
                'columns':['Arm','Verified jobs','Rejected candidate fixes','Tokens','Hosted inference'],'rows':table,
                'note':'New synthetic test programs were excluded from training and checkpoint selection. Candidate-failure counts include failed intermediate adaptive attempts. A small pilot does not establish production generalization.'})
        return result

    def snapshot(self):
        repositories = [{k: v for k, v in r.items() if k not in ('root', 'plan_path')} for r in self.state['repositories']]
        for repo in repositories:
            if repo.get('name') in ('inventory_stock','barrier_cache'):repo['origin']='Fine-tuned adaptive pilot - held-out synthetic program'
        repositories.sort(key=lambda r:r.get('contract',{}).get('budgets',{}).get('max_model_calls',1)<3)
        trained=read(active_root(ROOT)/'training.json') if artifact_ready(active_root(ROOT)) else None
        training={k:trained.get(k) for k in ('output_format','training_seconds','gpu','base_model','selected_epoch','epochs_completed','trainable_parameters','initial_validation_loss','best_validation_loss','adapter_sha256')} if trained else None
        if training:
            started=read(active_root(ROOT)/'started.json');dataset=Path(started['dataset']);dataset=dataset if dataset.is_absolute() else ROOT/dataset
            manifest=read(dataset/'manifest.json');training['train_programs']=sum(1 for _ in (dataset/'train.jsonl').read_text().splitlines());training['validation_programs']=sum(1 for _ in (dataset/'validation.jsonl').read_text().splitlines())
        return {'heartbeat': int(time.time() * 1000), 'credentials_ready': bool(os.environ.get('NEBIUS_API_KEY') and os.environ.get('NEBIUS_PROJECT_ID')), 'remaining_budget_usd': self.remaining(), 'repositories': repositories,
                'models': [{'id':m['id'],'name':m['name'],'bound_usd':m['bound_usd'],'max_calls':m.get('max_calls',1),'trained':m.get('trained',False)} for m in self.models], 'runs': list(reversed(self.state['runs'][-50:])), 'experiments': self.experiments(), 'last_error': self.last_error,'training':training}

    async def repair(self, command, command_id):
        if not command.get('reviewed'):
            raise ValueError('Review the contract before starting a repair')
        if command.get('model')==ADAPTIVE_ID:
            return await self.repair_adaptive(command,command_id)
        if command.get('model')==V4_ID:
            return await self.repair_v4(command,command_id)
        repo = next(r for r in self.state['repositories'] if r['id'] == command['repository'])
        if not repo.get('ready') or command.get('plan_sha256') != repo['plan_sha256']:
            raise ValueError('Contract changed. Refresh and review it again.')
        await self.catalog()
        model = next(m for m in self.models if m['id'] == command['model'])
        approved = command.get('max_cost_usd')
        if type(approved) not in (float, int) or not math.isfinite(approved) or not 0 < model['bound_usd'] <= approved <= .25 or model['bound_usd'] > self.remaining():
            raise ValueError('Live model cost exceeds the approved or remaining budget')
        folder = self.home / 'runs' / command_id
        folder.mkdir(parents=True, exist_ok=False)
        old = read(repo['plan_path'])
        fresh = create_plan(Path(repo['root']), Path(repo['plan_path']).parent.parent / 'contract.json', folder / 'plan')
        if fresh['plan_sha256'] != old['plan_sha256']:
            raise ValueError('Repository source changed since review. Reconnect it before running.')
        # Freeze only the allowlisted files; the original codebase is never edited.
        workspace = folder / 'original'
        for name, entry in fresh['files'].items():
            source = Path(repo['root']) / name
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            if digest(target) != entry['sha256']:
                raise ValueError('Source changed during capture')
        task = ConcurrencyTask.model_validate({**fresh['task'], 'workspace': workspace})
        budgets = fresh['contract']['budgets']
        if budgets['max_output_tokens_per_call'] < OUTPUT_CAP:
            raise ValueError('Contract output budget is below the console cap; revise and review the contract')
        row = {'id': command_id, 'repository_name': repo['name'], 'model': model['id'], 'model_name': model['name'], 'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'stage': 'Preparing remote baseline', 'model_calls': 0, 'reserved_usd': 0, 'false_fix': False}
        self.state['runs'].append(row)
        self.persist()
        started = time.perf_counter()
        try:
            async with asyncio.timeout(min(1800, budgets['max_wall_seconds'])):
                staging = folder / 'staging'
                staging.mkdir()
                os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = IMAGE
                async with NebiusSandboxBackend(temporary_parent=staging) as box:
                    await box.upload_project(workspace, task.source_files + task.support_files)
                    build = await CCompiler().compile(task, box)
                    save(folder / 'baseline-build.json', build.model_dump(mode='json'))
                    campaign = JournalCampaign(folder)
                    baseline = await campaign.run(task, box, runs=task.stress_runs) if build.success else None
                    original = {n: (workspace / n).read_text(encoding='utf-8') for n in task.source_files}
                    context = {'task': fresh['contract']['description'], 'sources': original, 'protected_files': {n: (workspace/n).read_text(encoding='utf-8') for n in task.support_files}, 'verification': fresh['contract']['verification'], 'build_command': task.build_command, 'baseline_build': build.model_dump(mode='json'), 'observed_baseline': baseline.compact() if baseline else None}
                    prompt = repair_prompt(context) + '\nPreserve every original scheduling hook, including sched_yield calls. Cover all readers and writers of a shared invariant. Return exact source edits only in the requested JSON contract.'
                    upper = len((SYSTEM_PROMPT + prompt).encode('utf-8')) + 100
                    if upper > min(48000, model['context_length'] - OUTPUT_CAP, budgets['max_input_tokens_per_call']) or upper + OUTPUT_CAP > budgets['max_total_tokens']:
                        raise ValueError('Prompt exceeds the conservative input budget; narrow the source scope or review a larger input budget')
                    payload = {'model': model['id'], 'messages': [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}], 'max_tokens': OUTPUT_CAP, 'temperature': 0}
                    if model['id'].lower() == 'nvidia/nemotron-3-super-120b-a12b':
                        payload['chat_template_kwargs'] = {'enable_thinking': False}
                    save(folder/'payload.json', payload)
                    save(folder/'pricing.json', model)
                    row.update(stage='Model repair Ã‚· one bounded call', model_calls=1, reserved_usd=model['bound_usd'])
                    self.persist()  # Persist reservation BEFORE the paid request, including unknown outcomes.
                    tick = time.perf_counter()
                    async with httpx.AsyncClient(timeout=120) as client:
                        response = await client.post(BASE+'/chat/completions', headers={'Authorization': 'Bearer '+os.environ['NEBIUS_API_KEY']}, json=payload)
                    row['inference_ms'] = (time.perf_counter()-tick)*1000
                    save(folder/'http-status.json', {'status': response.status_code})
                    response.raise_for_status()
                    data = response.json()
                    save(folder/'response.json', data)
                    usage = data.get('usage', {})
                    inp, output = usage.get('prompt_tokens'), usage.get('completion_tokens')
                    if type(inp) != int or type(output) != int or inp < 0 or output < 0:
                        raise ValueError('Missing actual token usage; request remains unknown')
                    rates = model['pricing']
                    cost = float(Decimal(inp)*Decimal(str(rates['prompt'])) + Decimal(output)*Decimal(str(rates['completion'])) + Decimal(str(rates.get('request', '0'))))
                    row.update(input_tokens=inp, output_tokens=output, tokens=inp+output, cost_usd=cost)
                    if output > OUTPUT_CAP or inp > min(model['context_length'] - OUTPUT_CAP, 48000) or cost > model['bound_usd']:
                        raise ValueError('Provider usage exceeded the reserved contract')
                    choice = data['choices'][0]
                    row['response'] = choice['message']['content']
                    self.persist()
                    try:
                        if choice['finish_reason'] != 'stop':
                            raise ValueError('Incomplete model output')
                        proposal = parse_repair(row['response'], original)
                    except (ValueError, TypeError):
                        row.update(status='invalid_output', stage='Model output rejected', error='Response did not satisfy the exact-edit contract. No retry was made.')
                        return
                    row.update(patch=proposal.patch, stage='Applying canonical patch')
                    (folder/'candidate.patch').write_text(proposal.patch, encoding='utf-8')
                    applied = await box.apply_patch(proposal.patch, task.source_files)
                    save(folder/'patch-application.json', applied.model_dump(mode='json'))
                    if not applied.success:
                        row.update(status='invalid_output', error='Canonical patch could not be applied.')
                        return
                    candidate = {n: await box.read_file(n) for n in task.source_files}
                    save(folder/'candidate-sources.json', candidate)
                    for name in task.support_files:
                        if (await box.read_file(name)).encode() != (workspace/name).read_bytes():
                            raise ValueError('A protected file changed')
                    row['stage'] = 'Full verification Ã‚· 100 stress + semantics + 3 TSan'
                    self.persist()
                    verification = await ConcurrencyVerifier(campaigns=campaign).verify_workspace(task, box, baseline)
                    save(folder/'verification.json', verification.model_dump(mode='json'))
                    hooks = all(candidate[n].count('sched_yield(') == original[n].count('sched_yield(') for n in original)
                    v = {'build_passed': verification.build_passed, 'original_tests_passed': verification.evidence.get('original_tests', {}).get('passed'), 'passed_runs': verification.passed_runs, 'total_runs': verification.total_runs, 'semantic_passed': verification.semantic_passed, 'tsan_passed': verification.sanitizer_passed, 'scheduling_hooks_preserved': hooks}
                    row.update(verification=v, verification_ms=verification.duration_ms, false_fix=verification.false_fix or not hooks, status='unknown' if verification.infrastructure_failures else ('verified' if verification.passed and hooks else 'rejected'), stage='Complete')
                    if not hooks:
                        row['error'] = 'Rejected: original scheduling hooks were removed or added.'
                    if row['status'] == 'verified':
                        require_verified(verification.model_dump(mode='json'), task.verification_config.model_dump())
        except Exception as exc:
            row.update(status='unknown' if row['model_calls'] else 'error', stage='Stopped without retry', error=f'{type(exc).__name__}: the attempt stopped. Inspect the local evidence; no automatic replay.')
            # Redacted exception class only: external errors can contain credentials/URLs.
            save(folder/'interruption.json', {'type': type(exc).__name__, 'automatic_replay': False})
        finally:
            row['end_to_end_ms'] = (time.perf_counter()-started)*1000
            save(folder/'result.json', row)
            self.persist()

    async def repair_adaptive(self,command,command_id):
        repo=next(r for r in self.state['repositories'] if r['id']==command['repository'])
        if not repo.get('ready') or command.get('plan_sha256')!=repo['plan_sha256']:
            raise ValueError('Review the current source contract')
        await self.catalog()
        option=next(m for m in self.models if m['id']==ADAPTIVE_ID)
        approved=command.get('max_cost_usd')
        if type(approved) not in (int,float) or not math.isfinite(approved) or not 0<option['bound_usd']<=approved<=.25 or approved>self.remaining():
            raise ValueError('Adaptive route exceeds approved or remaining budget')
        if repo['contract']['budgets']['max_model_calls']<3:
            raise ValueError('Adaptive mode requires a reviewed three-call contract')
        folder=self.home/'runs'/command_id
        folder.mkdir(parents=True,exist_ok=False)
        fresh=create_plan(Path(repo['root']),Path(repo['plan_path']).parent.parent/'contract.json',folder/'plan')
        if fresh['plan_sha256']!=repo['plan_sha256']:raise ValueError('Source changed after review')
        workspace=folder/'original'
        for name,entry in fresh['files'].items():
            target=workspace/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((Path(repo['root'])/name).read_bytes())
            if digest(target)!=entry['sha256']:raise ValueError('Source changed during capture')
        task=ConcurrencyTask.model_validate({**fresh['task'],'workspace':workspace})
        task.metadata['fixture_description']=repo['contract']['description']
        budgets=fresh['contract']['budgets']
        if budgets['max_output_tokens_per_call']<OUTPUT_CAP:
            raise ValueError('Review an output cap of at least 2048 tokens per attempt')
        row={'id':command_id,'repository_name':repo['name'],'model':ADAPTIVE_ID,'model_name':option['name'],
            'created_at':datetime.now(timezone.utc).isoformat(),'status':'running','stage':'Preparing adaptive route',
            'model_calls':0,'cost_usd':0,'reserved_usd':option['bound_usd'],'false_fix':False,'attempts':[]}
        self.state['runs'].append(row);self.persist()
        def progress(data):
            row.update(data)
            row['model_calls']=sum(r.get('model_calls',0) for r in row.get('attempts',[]))
            row['reserved_usd']=option['bound_usd']
            row['cost_usd']=None if any(r.get('reserved_usd',0)>0 and r.get('tokens') is None for r in row.get('attempts',[])) else sum(r.get('cost_usd',0) for r in row.get('attempts',[]))
            known=[r for r in row.get('attempts',[]) if r.get('tokens') is not None]
            row['tokens']=None if any(r.get('model_calls') and r.get('tokens') is None for r in row.get('attempts',[])) else sum(r['tokens'] for r in known)
            self.persist()
        try:
            os.environ['AGENTKERNEL_SANDBOX_IMAGE']=IMAGE
            runner=AdaptiveRepair(ROOT,self.models,JournalCampaign,on_progress=progress)
            async with asyncio.timeout(min(1800,budgets['max_wall_seconds'])):
                result=await runner.run(task,folder/'route',max_cost_usd=approved,
                    max_calls=min(3,budgets['max_model_calls']),max_total_tokens=budgets['max_total_tokens'],max_input_tokens=budgets['max_input_tokens_per_call'])
            row.update({k:v for k,v in result.items() if k not in ('mode','base_model')})
            row['stage']='Complete'
        except Exception as exc:
            row.update(status='unknown',stage='Interrupted; no automatic replay',cost_usd=None,error=type(exc).__name__)
        finally:
            save(folder/'result.json',row);self.persist()

    async def repair_v4(self,command,command_id):
        repo=next(r for r in self.state['repositories'] if r['id']==command['repository'])
        if not repo.get('ready') or command.get('plan_sha256')!=repo['plan_sha256']:
            raise ValueError('Review the current source contract')
        await self.catalog()
        option=next(m for m in self.models if m['id']==V4_ID)
        approved=command.get('max_cost_usd')
        if type(approved) not in (int,float) or not math.isfinite(approved) or not 0<option['bound_usd']<=approved<=.25 or approved>self.remaining():
            raise ValueError('Adaptive v4 route exceeds approved or remaining budget')
        budgets=repo['contract']['budgets']
        if budgets['max_model_calls']<V4_CALLS or budgets['max_total_tokens']<V4_TOTAL_CAP or budgets['max_input_tokens_per_call']<V4_INPUT_CAP:
            raise ValueError('Adaptive v4 requires a reviewed two-call contract with its token limits')
        folder=self.home/'runs'/command_id
        folder.mkdir(parents=True,exist_ok=False)
        fresh=create_plan(Path(repo['root']),Path(repo['plan_path']).parent.parent/'contract.json',folder/'plan')
        if fresh['plan_sha256']!=repo['plan_sha256']:raise ValueError('Source changed after review')
        workspace=folder/'original'
        for name,entry in fresh['files'].items():
            target=workspace/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((Path(repo['root'])/name).read_bytes())
            if digest(target)!=entry['sha256']:raise ValueError('Source changed during capture')
        task=ConcurrencyTask.model_validate({**fresh['task'],'workspace':workspace})
        task.metadata['fixture_description']=repo['contract']['description']
        row={'id':command_id,'repository_name':repo['name'],'model':V4_ID,'model_name':option['name'],
            'created_at':datetime.now(timezone.utc).isoformat(),'status':'running','stage':'Preparing adaptive v4 route',
            'model_calls':0,'cost_usd':0,'reserved_usd':option['bound_usd'],'false_fix':False,'attempts':[]}
        self.state['runs'].append(row);self.persist()
        def progress(data):
            row.update(data);row['model_calls']=sum(a.get('model_calls',0) for a in row.get('attempts',[]));self.persist()
        try:
            os.environ['AGENTKERNEL_SANDBOX_IMAGE']=IMAGE
            runner=AdaptiveV4(ROOT,self.catalog_rows,on_progress=progress)
            async with asyncio.timeout(min(1800,budgets['max_wall_seconds'])):
                result=await runner.run(task,folder/'route',arm='v4',max_cost_usd=approved,
                    max_input_tokens=V4_INPUT_CAP,max_total_tokens=V4_TOTAL_CAP)
            attempts=result.get('attempts',[])
            def total(key):
                values=[a.get(key) for a in attempts if a.get('model_calls')]
                return None if any(v is None for v in values) else sum(values)
            row.update({k:v for k,v in result.items() if k not in ('route','arm','phases_ms')},model_name=option['name'],
                input_tokens=total('input_tokens'),output_tokens=total('output_tokens'),
                inference_ms=sum(a.get('inference_ms') or 0 for a in attempts),verification_ms=sum(a.get('verification_ms') or 0 for a in attempts))
            row['stage']='Complete'
        except Exception as exc:
            row.update(status='unknown',stage='Interrupted; no automatic replay',cost_usd=None,error=type(exc).__name__)
        finally:
            save(folder/'result.json',row);self.persist()

    async def handle(self, command):
        identifier = command['id']
        if identifier in self.state['completed'] or any(r['id'] == identifier for r in self.state['runs']):
            return
        payload = json.loads(command['payload'])
        try:
            if payload['kind'] == 'check':
                await self.catalog()
            elif payload['kind'] == 'connect':
                await self.connect(payload)
            elif payload['kind'] == 'configure':
                repo = next(r for r in self.state['repositories'] if r['id'] == payload['repository'])
                self.configure(repo, payload['contract'])
            elif payload['kind'] == 'run':
                await self.repair(payload, identifier)
            else:
                raise ValueError('Unknown command')
            self.last_error = None
        except Exception as exc:
            self.last_error = f'{type(exc).__name__}: request could not be completed. Check the repository contract, source scope, and live cost limit.'
            save(self.home/'commands'/f'{identifier}.json', {'status': 'failed', 'error_type': type(exc).__name__})
        finally:
            self.state['completed'].append(identifier)
            self.persist()

    async def serve(self, token):
        load_env_file(ROOT/'.env')
        self.seed()
        self.seed_adaptive_cases()
        try:
            await self.catalog()
        except Exception as exc:
            self.last_error = f'{type(exc).__name__}: model catalog unavailable.'
        work = None
        identifier = None
        async with httpx.AsyncClient(base_url=SITE, timeout=30, headers={'OAI-Sites-Authorization': 'Bearer '+token}) as client:
            while True:
                try:
                    completed = identifier if work is not None and work.done() else None
                    response = await client.post('/api/agent', json={'snapshot': self.snapshot(), 'completed': completed})
                    response.raise_for_status()
                    if completed:
                        await work
                        work, identifier = None, None
                    if work is None:
                        response = await client.get('/api/agent')
                        response.raise_for_status()
                        command = response.json().get('command')
                        if command:
                            identifier = command['id']
                            work = asyncio.create_task(self.handle(command))
                except (httpx.HTTPError, ValueError):
                    print('Console connection unavailable; preserving jobs and retrying heartbeat only.', flush=True)
                await asyncio.sleep(3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='store_true', help='Validate initialization without model calls')
    parser.add_argument('--token-stdin', action='store_true', help='Read the service token once from a private process pipe')
    args = parser.parse_args()
    if args.snapshot:
        load_env_file(ROOT/'.env')
        agent = Agent()
        agent.seed()
        agent.seed_adaptive_cases()
        asyncio.run(agent.catalog())
        print(json.dumps(agent.snapshot()))
    else:
        token = sys.stdin.readline().strip() if args.token_stdin else getpass.getpass('Private Sites service token (hidden): ')
        if not token:
            parser.error('A private Sites service token is required')
        with single_agent(ROOT / 'reports/sites-console'):
            asyncio.run(Agent().serve(token))
