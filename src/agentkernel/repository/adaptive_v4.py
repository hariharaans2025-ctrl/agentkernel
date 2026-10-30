"""Adaptive v4 opt-in route: deterministic routing, v4 line blocks, evidence-directed correction.

Old routes (v2 Sites path, v3 ProductRepair) are unchanged. Acceptance uses the
same ConcurrencyVerifier gates as v3: fresh build, original tests, >=100 stress,
required semantics, >=3 TSan runs, preserved sched_yield hooks. Unknown usage,
transport interruption or sanitizer unavailability stops the route; no replay.
"""
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from time import perf_counter
import uuid
import httpx

from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.instrumentation.sanitizer import instrumented_task, SanitizerConfig, runtime_unavailable
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.sandbox.local import safe_path
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.repository.learning import require_verified
from .remote_repair import plan_remote_repair, parse_remote_response, repair_schema
from .specialist import to_proposal
from .budget import BudgetLedger
from .product_campaign import ProductCampaign
from .adaptive_v3 import remote_models, verification_summary, CAPS
from . import adaptive_v4_core as core

ROUTE_ID = 'agentkernel/adaptive-v4'
ENDPOINT = 'https://api.tokenfactory.nebius.com/v1/chat/completions'
ARMS = ('super_only', 'ultra_only', 'fixed_fallback', 'v4')
DEFAULT_LATENCY_S = 1.6 + 30.0
# The input bound must hold the original prompt PLUS a full evidence packet (MAX_EVIDENCE_BYTES), or the
# correction stage can never be planned (30 Oct live aggregate_3: 10,975-byte packet vs a 12,000 bound).
V4_INPUT_CAP = 36000
V4_TOTAL_CAP = 48000


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, default=str)


class Phases:
    def __init__(self): self.ms = {}
    def add(self, name, ms): self.ms[name] = self.ms.get(name, 0.0) + ms


class TimedCompiler(CCompiler):
    """Times builds; verifier order is build -> tests -> stress -> semantics -> TSan build -> TSan."""
    def __init__(self, phases, prefix): super().__init__(); self.phases, self.prefix = phases, prefix
    async def compile(self, task, sandbox, flags=None):
        tick = perf_counter()
        result = await (super().compile(task, sandbox, flags) if flags else super().compile(task, sandbox))
        self.phases.add(self.prefix + ('tsan_build' if flags else 'build'), (perf_counter() - tick) * 1000)
        return result


class TimedCampaign(ProductCampaign):
    def __init__(self, out, phases, prefix): super().__init__(out); self.phases, self.prefix = phases, prefix
    async def run(self, task, sandbox, *, runs=None):
        tick = perf_counter(); result = await super().run(task, sandbox, runs=runs)
        name = 'tsan' if '-fsanitize=thread' in ' '.join(task.build_command) or task.task_id.endswith('tsan') else 'stress'
        self.phases.add(self.prefix + name, (perf_counter() - tick) * 1000)
        return result


async def branch(parent):
    """Isolated branch of an immutable post-upload snapshot; never a shared mutable sandbox."""
    child = NebiusSandboxBackend(client=parent.client, output_limit=parent.output_limit)
    child.image = parent.snapshot
    child._temporary = tempfile.TemporaryDirectory(prefix='agentkernel-v4-branch-')
    child.workspace = Path(child._temporary.name).resolve()
    return child


def plan_v4(model, messages, sources, *, max_cost_usd, max_input_tokens, max_output_tokens, max_total_tokens):
    """Reuse reviewed charge planning; send plain text (no JSON grammar) under the v4 contract."""
    base = plan_remote_repair(model, [{'role': 'user', 'content': 'Plan one bounded repair request.'}], ['candidate.c'],
                              max_cost_usd=max_cost_usd, max_input_tokens=max_input_tokens,
                              max_output_tokens=max_output_tokens, max_total_tokens=max_total_tokens)
    bound = sum(len(m['content'].encode('utf-8')) + 64 for m in messages) + 512
    if bound > base.max_input_tokens: raise core.ContractError('input_budget_exceeded', 'envelope')
    if bound + base.max_output_tokens > base.max_total_tokens: raise core.ContractError('total_token_budget_exceeded', 'envelope')
    payload = {k: v for k, v in base.payload.items() if k != 'response_format'}
    payload['messages'] = [dict(m) for m in messages]
    return replace(base, payload=payload, input_token_bound=bound)


def parse_v4(data, plan, sources, identity):
    """Billing receipt from the shared parser, then the strict v4 block contract."""
    schema = repair_schema(['candidate.c']); schema['$defs']['SourceEdit']['properties']['file']['enum'] = list(sources)
    receipt = parse_remote_response(data, replace(plan, payload={**plan.payload, 'response_format': {'type': 'json_schema',
        'json_schema': {'schema': schema, 'name': 'accounting_only', 'strict': True}}}), sources)
    if receipt.outcome == 'unknown' or not receipt.usage_known:
        return receipt, None, {'category': 'unknown'}
    if receipt.finish_reason == 'length':
        return receipt, None, {'category': 'truncation', 'error_code': 'output_budget_exhausted'}
    if receipt.finish_reason != 'stop' or not isinstance(receipt.text, str):
        return receipt, None, {'category': 'envelope', 'error_code': receipt.error_code or 'malformed_message'}
    try:
        files, notes = core.parse_blocks(receipt.text, sources, identity)
        proposal, _ = to_proposal(json.dumps({'files': files}), sources)
    except core.ContractError as exc:
        return receipt, None, {'category': exc.category, 'error_code': exc.code}
    except (ValueError, TypeError):
        return receipt, None, {'category': 'schema', 'error_code': 'proposal_guard_rejected'}
    return receipt, proposal, {'category': None, 'error_code': None, 'notes': notes}


class AdaptiveV4:
    def __init__(self, root, models, *, ledger=None, calibration=None, latency_s=None, on_progress=None,
                 campaign_factory=TimedCampaign, backend_factory=NebiusSandboxBackend, client_factory=None):
        self.root = Path(root).resolve(); self.models = models
        self.ledger = ledger or BudgetLedger(self.root / 'reports/product-v3/budget.json')
        self.calibration = calibration or {}
        self.latency_s = latency_s
        self.progress = on_progress or (lambda d: None)
        self.campaign_factory, self.backend_factory = campaign_factory, backend_factory
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=150))

    def route(self, arm, features, input_bound):
        options = remote_models(self.models)
        if arm == 'super_only': return core.RouteDecision(core.ROUTER_VERSION, ['super'], features, core.bucket_of(features), {'ultra': 'arm_fixed'})
        if arm == 'ultra_only': return core.RouteDecision(core.ROUTER_VERSION, ['ultra'], features, core.bucket_of(features), {'super': 'arm_fixed'})
        if arm == 'fixed_fallback': return core.RouteDecision(core.ROUTER_VERSION, ['super', 'ultra'], features, core.bucket_of(features))
        latency, source = self.latency_estimate(options)
        prices = {s: core.expected_prices(m, input_tokens=input_bound // 3, output_tokens=300, seconds=latency[s]) for s, m in options.items()}
        decision = core.decide_route(features, self.calibration, prices, input_bound_tokens=input_bound,
                                     contexts={s: m['context_length'] for s, m in options.items()}, output_caps=CAPS)
        decision.expected['latency_source'] = source
        return core.with_correction(decision)

    def latency_estimate(self, options):
        """Explicit override, else development phase timings, else equal defaults.

        Equal defaults make Super-first unreachable (p < 1 always), which is the conservative choice
        when no inference + verification timings exist yet.
        """
        if self.latency_s: return self.latency_s, 'explicit'
        measured = (self.calibration.get('latency') or {}).get('seconds') or {}
        if all(s in measured for s in options): return measured, 'development_phase_timings'
        return dict.fromkeys(options, DEFAULT_LATENCY_S), 'default_equal_uncalibrated'

    async def run(self, task, folder, *, arm='v4', max_cost_usd, max_input_tokens=V4_INPUT_CAP, max_total_tokens=V4_TOTAL_CAP,
                  max_verifier_recoveries=1, max_format_recoveries=1, queue_ms=0.0):
        if arm not in ARMS: raise ValueError('Unknown v4 arm')
        if type(max_cost_usd) not in (int, float) or not math.isfinite(max_cost_usd) or not 0 <= max_cost_usd <= 1:
            raise ValueError('Explicit charge cap no greater than $1 required')
        cfg = task.verification_config
        if (cfg.stress_runs < 100 or not cfg.required_build_success or not cfg.required_original_tests or not cfg.original_test_commands
                or not cfg.semantic_checks or not all(c.required for c in cfg.semantic_checks) or not cfg.sanitizer_required
                or cfg.sanitizer_runs < 3 or cfg.allowed_deadlocks or cfg.allowed_races or cfg.allowed_crashes):
            raise ValueError('v4 requires complete independent verification before inference')
        options = remote_models(self.models)
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
        started = perf_counter(); phases = Phases(); phases.add('queue', queue_ms); rows = []
        frozen = folder / 'input'; frozen.mkdir()
        for name in task.source_files + task.support_files:
            if any(p.startswith('.') for p in Path(name).parts): raise ValueError('Hidden or credential files cannot enter repair scope')
            target = safe_path(frozen, name); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(safe_path(task.workspace.resolve(strict=True), name).read_bytes())
        task = task.model_copy(update={'workspace': frozen})
        sources = {n: (frozen / n).read_bytes().decode('utf-8') for n in task.source_files}
        headers = {n: (frozen / n).read_bytes().decode('utf-8') for n in task.support_files if n.endswith(('.h', '.hpp'))}
        identity = core.source_identity(sources)
        hashes = {n: hashlib.sha256((frozen / n).read_bytes()).hexdigest() for n in task.source_files + task.support_files}
        save(folder / 'started.json', {'route': ROUTE_ID, 'arm': arm, 'contract': core.CONTRACT_ID, 'caps': CAPS,
             'max_cost_usd': max_cost_usd, 'max_calls': 2, 'max_verifier_recoveries': max_verifier_recoveries,
             'max_format_recoveries': max_format_recoveries, 'source_hashes': hashes, 'automatic_replay': False,
             'task': task.model_dump(mode='json'), 'ledger': str(self.ledger.path)})
        result = {'status': 'unknown', 'route': ROUTE_ID, 'arm': arm, 'attempts': rows, 'model_calls': 0, 'calls_by_model': {},
                  'tokens': 0, 'cost_usd': 0, 'reserved_usd': 0, 'false_fix': False, 'cache_used': False}
        description = task.metadata.get('fixture_description', 'Repair the observed concurrency failure while preserving every task invariant.')
        context = {'description': description, 'requirements': [c.name for c in cfg.semantic_checks]}
        try:
            base_dir = folder / 'baseline'; base_dir.mkdir()
            tick = perf_counter()
            async with self.backend_factory() as box:
                phases.add('sandbox_create', (perf_counter() - tick) * 1000); tick = perf_counter()
                await box.upload_project(task.workspace, task.source_files + task.support_files)
                box.snapshot = box.image; phases.add('upload', (perf_counter() - tick) * 1000); tick = perf_counter()
                build = await CCompiler().compile(task, box); save(base_dir / 'build.json', build.model_dump(mode='json'))
                phases.add('baseline_build', (perf_counter() - tick) * 1000)
                if not build.success: raise RuntimeError('Baseline build unavailable; no inference started')
                campaign = self.campaign_factory(base_dir, phases, 'baseline_')
                baseline = await campaign.run(task, box, runs=3)
                if baseline.infrastructure_failures: raise RuntimeError('Baseline infrastructure unavailable')
                sanitizer = None
                if not baseline.failed_runs:
                    checked = instrumented_task(task)
                    if not (await TimedCompiler(phases, 'baseline_').compile(checked, box, SanitizerConfig().flags)).success:
                        raise RuntimeError('Required baseline sanitizer unavailable')
                    races = await campaign.run(checked, box, runs=3)
                    if races.infrastructure_failures or any(runtime_unavailable(r.stderr) for r in races.runs):
                        raise RuntimeError('Baseline sanitizer infrastructure unavailable')
                    sanitizer = races.compact()
                    if not races.failed_runs:
                        result.update(status='baseline_clean', stop_reason='No observed failure; no model call.'); return result
                context['observed_baseline'] = baseline.compact(); context['baseline_sanitizer'] = sanitizer
                self.progress({'stage': 'Baseline reproduced; routing'})
                features = core.route_features(sources, headers, baseline.counts, sanitizer and sanitizer['counts'])
                probe = core.v4_messages(sources, headers, context)
                decision = self.route(arm, features, sum(len(m['content'].encode()) + 64 for m in probe) + 512)
                save(folder / 'route.json', asdict(decision)); result['route_decision'] = asdict(decision)
                if not decision.stages: result.update(status='rejected', stop_reason='No tier fits context capacity'); return result
                evidence, verifier_recoveries, format_recoveries = None, 0, 0
                for index, stage in enumerate(decision.stages):
                    if index and rows[-1]['outcome'] == 'invalid_output':
                        if format_recoveries >= max_format_recoveries: break
                        format_recoveries += 1
                    elif index:
                        if verifier_recoveries >= max_verifier_recoveries: break
                        verifier_recoveries += 1
                    out = folder / f'{index + 1}-{stage}'; out.mkdir()
                    row = {'stage': stage, 'outcome': 'unknown', 'model_calls': 0, 'tokens': None, 'cost_usd': None, 'false_fix': False,
                           'recovery': None if not index else ('format' if rows[-1]['outcome'] == 'invalid_output' else 'verifier')}
                    rows.append(row)
                    self.progress({'stage': f"Call {index + 1}: {stage}" + (f" ({row['recovery']} correction)" if row['recovery'] else ''), 'attempts': rows})
                    chat = core.v4_messages(sources, headers, context, evidence)
                    used = sum(r.get('tokens') or 0 for r in rows)
                    try:
                        plan = plan_v4(options[stage], chat, sources, max_cost_usd=max_cost_usd - result['reserved_usd'],
                                       max_input_tokens=max_input_tokens, max_output_tokens=CAPS[stage], max_total_tokens=max_total_tokens - used)
                    except core.ContractError as exc:
                        # Refused before any reservation or call: a known outcome, not an unknown one.
                        row.update(outcome='not_started', error_code=exc.code, category=exc.category); save(out / 'result.json', row)
                        result['stop_reason'] = f'{stage} not started: {exc.code}; no call was made'; break
                    save(out / 'payload.json', plan.payload); save(out / 'pricing.json', options[stage])
                    call_id = uuid.uuid4().hex
                    self.ledger.reserve(call_id, bound_usd=plan.reservation_usd, model=options[stage]['id'], evidence=str(out))
                    row.update(model_calls=1, reserved_usd=plan.reservation_usd, model=options[stage]['id'], ledger_call_id=call_id)
                    result['model_calls'] += 1; result['reserved_usd'] += plan.reservation_usd
                    result['calls_by_model'][stage] = result['calls_by_model'].get(stage, 0) + 1
                    tick = perf_counter()
                    try:
                        async with self.client_factory() as client:
                            response = await client.post(ENDPOINT, json=plan.payload, headers={'Authorization': 'Bearer ' + os.environ['NEBIUS_API_KEY']})
                        save(out / 'http-status.json', {'status': response.status_code})
                        if response.status_code != 200:
                            save(out / 'provider-error.json', {'status': response.status_code, 'body': response.text[:5000]})
                            raise RuntimeError('Provider rejected request; no automatic replay')
                        data = response.json(); save(out / 'response.json', data)
                    except BaseException:
                        self.ledger.unknown(call_id, 'request_interrupted_or_provider_error'); raise
                    row['inference_ms'] = (perf_counter() - tick) * 1000; phases.add('inference', row['inference_ms'])
                    receipt, proposal, info = parse_v4(data, plan, sources, identity)
                    row.update(input_tokens=receipt.input_tokens, output_tokens=receipt.output_tokens, reasoning_tokens=receipt.reasoning_tokens,
                               tokens=receipt.tokens, cost_usd=receipt.cost_usd, response=receipt.text, finish_reason=receipt.finish_reason,
                               # The shared receipt parser expects JSON; its contract code is meaningless for v4 block text.
                               error_code=info.get('error_code') or (receipt.error_code if info.get('category') == 'unknown' else None),
                               category=info.get('category'), parse_notes=info.get('notes'))
                    if receipt.usage_known:
                        self.ledger.settle(call_id, actual_usd=receipt.cost_usd, input_tokens=receipt.input_tokens, output_tokens=receipt.output_tokens)
                    else:
                        self.ledger.unknown(call_id, receipt.error_code or 'unknown_usage'); row['outcome'] = 'unknown'
                        save(out / 'result.json', row); result['stop_reason'] = 'Unknown usage; route stopped'; break
                    if proposal is None:
                        row['outcome'] = 'invalid_output'; save(out / 'result.json', row)
                        # Format recovery gets the original task plus the rejected reply and its code, never verifier evidence.
                        evidence = {'previous_reply_rejected_before_execution': {'error_code': row['error_code'], 'category': row['category'], 'reply': (receipt.text or '')[:4000]}}
                        continue
                    row['patch'] = proposal.patch; (out / 'candidate.patch').write_text(proposal.patch, encoding='utf-8')
                    self.progress({'stage': f'Verifying {stage} candidate: build, tests, 100 stress, semantics, 3 TSan', 'attempts': rows})
                    vphases = Phases(); tick = perf_counter()
                    candidate_box = await branch(box)
                    try:
                        applied = await candidate_box.apply_patch(proposal.patch, task.source_files)
                        save(out / 'patch-application.json', applied.model_dump(mode='json'))
                        if not applied.success:
                            row.update(outcome='invalid_output', error_code='canonical_patch_rejected', category='line_mapping'); save(out / 'result.json', row); continue
                        for name in task.support_files:
                            if hashlib.sha256((await candidate_box.read_file(name)).encode()).hexdigest() != hashes[name]:
                                raise RuntimeError('Protected source changed')
                        candidate = {n: await candidate_box.read_file(n) for n in task.source_files}
                        save(out / 'candidate-sources.json', candidate); vphases.add('apply', (perf_counter() - tick) * 1000)
                        v = await ConcurrencyVerifier(compiler=TimedCompiler(vphases, ''), campaigns=self.campaign_factory(out, vphases, '')).verify_workspace(task, candidate_box, baseline)
                    finally:
                        await candidate_box.destroy()
                    save(out / 'verification.json', v.model_dump(mode='json'))
                    known = sum(vphases.ms.values()); vphases.add('original_tests_and_semantics', max(0.0, v.duration_ms - known + vphases.ms.get('apply', 0)))
                    row['verification_phases_ms'] = vphases.ms
                    for k, val in vphases.ms.items(): phases.add('verify_' + k, val)
                    hooks = all(candidate[n].count('sched_yield(') == sources[n].count('sched_yield(') for n in sources)
                    tsan_unavailable = (v.evidence.get('sanitizer') or {}).get('status') == 'unavailable'
                    row.update(outcome='unknown' if v.infrastructure_failures or tsan_unavailable else ('verified' if v.passed and hooks else 'rejected'),
                               verification=verification_summary(v, hooks), verification_ms=v.duration_ms, false_fix=v.false_fix or not hooks)
                    if row['outcome'] == 'verified': require_verified(v.model_dump(mode='json'), cfg.model_dump(mode='json'))
                    row['taxonomy'] = core.classify_attempt(row); save(out / 'result.json', row)
                    if row['outcome'] == 'verified': result['status'] = 'verified'; break
                    if row['outcome'] == 'unknown': result['stop_reason'] = 'Verifier infrastructure or sanitizer unavailable; route stopped'; break
                    evidence = core.evidence_packet(failed_files=candidate, patch=proposal.patch, verification=v.model_dump(mode='json'))
                    save(out / 'evidence-packet.json', evidence)
                else:
                    result['status'] = 'rejected'
                if result['status'] == 'unknown' and rows and rows[-1]['outcome'] in ('rejected', 'invalid_output', 'not_started'): result['status'] = 'rejected'
        except Exception as exc:
            result.update(status='unknown', error=type(exc).__name__, stop_reason='Stopped without automatic replay')
        finally:
            for r in rows: r.setdefault('taxonomy', core.classify_attempt(r))
            result['tokens'] = None if any(r.get('model_calls') and r.get('tokens') is None for r in rows) else sum(r.get('tokens') or 0 for r in rows)
            result['cost_usd'] = None if any(r.get('model_calls') and r.get('cost_usd') is None for r in rows) else sum(r.get('cost_usd') or 0 for r in rows)
            result['false_fix'] = any(r.get('false_fix') for r in rows)
            result['recoveries'] = {'format': sum(r.get('recovery') == 'format' for r in rows), 'verifier': sum(r.get('recovery') == 'verifier' for r in rows)}
            result['end_to_end_ms'] = (perf_counter() - started) * 1000; phases.add('e2e', result['end_to_end_ms'])
            result['phases_ms'] = phases.ms
            final = next((r for r in reversed(rows) if r.get('patch')), rows[-1] if rows else {})
            for key in ('patch', 'verification'): result[key] = final.get(key)
            save(folder / 'result.json', result)
        return result
