"""Adaptive v4 live pilot: real Nebius Sandbox execution, real Token Factory inference.

  python scripts/live_adaptive_v4.py smoke --case audit_3    # real sandbox, scripted replies, scratch ledger, 0 paid calls
  python scripts/live_adaptive_v4.py prepare                 # freeze jobs, hashes, live IDs/prices; 0 paid calls
  python scripts/live_adaptive_v4.py execute <protocol.json> # paid; sequential; never replays

The v4 arm runs on all eight product-v1 test cases in manifest order (no selection). Those cases are
development-seen: the v4 diagnosis and prompt were written after their v3 failures. Results compare
against the frozen v3 run on identical cases, model IDs, prices and caps, but are NOT unseen evidence.
Run-level guard: at most 16 paid calls and $0.50 incremental committed spend (reservations count until settled).
"""
import argparse
import asyncio
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agentkernel.config import load_env_file  # noqa: E402
from agentkernel.concurrency.models import ConcurrencyTask  # noqa: E402
from agentkernel.repository import adaptive_v4_core as core  # noqa: E402
from agentkernel.repository.adaptive_v3 import CAPS, remote_models  # noqa: E402
from agentkernel.repository.adaptive_v4 import AdaptiveV4  # noqa: E402
from agentkernel.repository.budget import BudgetLedger  # noqa: E402
from agentkernel.repository.remote_repair import quote_repair_model  # noqa: E402

DATA = ROOT / 'datasets/adaptive-v3/product-v1'
FROZEN_V3 = ROOT / 'reports/cloud-comparison/20261029T170003Z/comparison-view.json'
IMAGE = 'agentkernel-clang:20261003122908'
MAX_CALLS, MAX_USD, INPUT_CAP = 16, 0.50, 12000


def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p, v): Path(p).write_text(json.dumps(v, indent=2, default=str), encoding='utf-8')
def stamp(): return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def task_for(case):
    root = DATA / 'tasks' / case
    return ConcurrencyTask.model_validate({**read(root / 'task.json'), 'workspace': root})


async def catalog():
    import httpx
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://api.tokenfactory.nebius.com/v1/models', params={'verbose': 'true'},
                        headers={'Authorization': 'Bearer ' + os.environ['NEBIUS_API_KEY']})
        r.raise_for_status(); return r.json()['data']


def implementation_hashes():
    files = [*(ROOT / 'src/agentkernel/repository').rglob('*.py'), *(ROOT / 'src/agentkernel/concurrency').rglob('*.py'), Path(__file__)]
    return {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in sorted(files)}


# ------------------------------------------------------------------ smoke (no provider call)
def blocks_from(original, target, name):
    """Scripted v4 reply turning ``original`` into ``target`` (smoke plumbing only, never a model result)."""
    a, b = original.splitlines(), target.splitlines(); spans = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == 'equal': continue
        if i1 == i2:  # pure insertion: widen to replace one anchoring original line
            i1, i2, j1, j2 = (i1 - 1, i1, j1 - 1, j2) if i1 else (0, 1, 0, j2 + 1)
        if spans and i1 < spans[-1][1]: spans[-1] = (spans[-1][0], max(i2, spans[-1][1]), spans[-1][2], max(j2, spans[-1][3]))
        else: spans.append((i1, i2, j1, j2))
    return '\n'.join(f'@@ REPLACE {name} {i1 + 1}-{i2}\n' + '\n'.join(b[j1:j2]) + ('\n' if j2 > j1 else '') + '@@ END' for i1, i2, j1, j2 in spans)


class ScriptedClient:
    """Stands in for Token Factory in the smoke only; returns scripted replies with nominal usage."""
    def __init__(self, replies): self.replies = replies
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False

    async def post(self, url, json, headers):
        reply = self.replies.pop(0)
        data = {'id': 'smoke', 'model': json['model'], 'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
                'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': reply}}]}
        return type('R', (), {'status_code': 200, 'text': '', 'json': lambda self: data})()


async def smoke(case):
    task = task_for(case); live = await catalog()
    sources = {n: (task.workspace / n).read_text(encoding='utf-8') for n in task.source_files}
    refs = {n: (DATA / 'references' / case / n).read_text(encoding='utf-8') for n in task.source_files}
    first = next(n for n in task.source_files)
    lines = sources[first].splitlines(); k = next(i for i, l in enumerate(lines) if l.strip() and not l.lstrip().startswith('#'))
    wrong = f'@@ REPLACE {first} {k + 1}-{k + 1}\n{lines[k]} /* smoke: deliberately not a fix */\n@@ END'
    fixed = '\n'.join(blocks_from(sources[n], refs[n], n) for n in task.source_files if sources[n] != refs[n])
    out = ROOT / 'reports/adaptive-v4-live' / ('smoke-' + stamp()); out.mkdir(parents=True)
    ledger = BudgetLedger(out / 'scratch-ledger.json')
    ledger.initialize(total_usd=1, authorization='Smoke only: scripted replies, no provider inference.')
    replies = [wrong, fixed]
    runner = AdaptiveV4(ROOT, live, ledger=ledger, client_factory=lambda: ScriptedClient(replies))
    result = await runner.run(task, out / 'run', arm='v4', max_cost_usd=0.2)
    summary = {'case': case, 'status': result['status'], 'stages': (result.get('route_decision') or {}).get('stages'),
               'attempts': [{k: a.get(k) for k in ('stage', 'outcome', 'recovery', 'category', 'error_code')} for a in result['attempts']],
               'recoveries': result.get('recoveries'), 'phases_ms': result.get('phases_ms'), 'error': result.get('error'),
               'scope': 'Plumbing smoke: real Nebius Sandbox build/verify; scripted replies (second is the private reference repair). '
                        'Not a model result; never counted.', 'provider_calls': 0}
    save(out / 'smoke-summary.json', summary); print(json.dumps(summary, indent=2))


# ------------------------------------------------------------------ paid pilot
async def prepare():
    live = await catalog(); models = remote_models(live)
    cases = [c['id'] for c in read(DATA / 'manifest.json')['cases'] if c['split'] == 'test']
    ultra_q = quote_repair_model(models['ultra'], max_input_tokens=INPUT_CAP, max_output_tokens=CAPS['ultra'])
    ledger = BudgetLedger(ROOT / 'reports/product-v3/budget.json').snapshot()
    if ledger['unknown_calls'] or ledger['committed_usd'] + MAX_USD > 10: raise ValueError('Ledger state does not permit this pilot')
    out = ROOT / 'reports/adaptive-v4-live' / stamp(); out.mkdir(parents=True)
    protocol = {
        'frozen_utc': datetime.now(timezone.utc).isoformat(), 'route': 'agentkernel/adaptive-v4', 'arm': 'v4',
        'router': core.ROUTER_VERSION, 'contract': core.CONTRACT_ID, 'system_prompt_sha256': sha256(core.SYSTEM_V4),
        'cases': cases, 'case_order': 'manifest order, all test cases, no selection', 'concurrency': 1,
        'models': models, 'caps': CAPS, 'input_cap': INPUT_CAP, 'max_calls_per_job': 2, 'image': IMAGE,
        'per_job_max_usd': 2 * ultra_q, 'run_max_calls': MAX_CALLS, 'run_max_incremental_usd': MAX_USD,
        'calibration': 'none (no v4 development calibration exists) -> router selects Ultra; correction stage is Ultra',
        'baseline_for_comparison': str(FROZEN_V3.relative_to(ROOT)),
        'case_hashes': {c: {n: sha(DATA / 'tasks' / c / n) for n in task_for(c).source_files + task_for(c).support_files} for c in cases},
        'implementation_sha256': implementation_hashes(), 'automatic_replay': False, 'cache_used': False,
        'disclosure': 'Cases are development-seen; v4 prompt includes lessons from their v3 failures. Not unseen evaluation.',
        'ledger_at_freeze': {'committed_usd': ledger['committed_usd'], 'unknown_calls': ledger['unknown_calls']}}
    save(out / 'protocol.json', protocol)
    print(json.dumps({'protocol': str(out / 'protocol.json'), 'cases': cases, 'max_paid_calls': MAX_CALLS,
                      'max_incremental_usd': MAX_USD, 'per_job_max_usd': protocol['per_job_max_usd'], 'paid_calls_started': 0}, indent=2))


def sha256(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()


async def execute(path):
    path = path.resolve(); out = path.parent; plan = read(path)
    if (out / 'started.json').exists(): raise ValueError('Never replay a started pilot')
    if implementation_hashes() != plan['implementation_sha256']: raise ValueError('Implementation changed after freeze')
    for c, files in plan['case_hashes'].items():
        if any(sha(DATA / 'tasks' / c / n) != h for n, h in files.items()): raise ValueError('Frozen case changed')
    live = await catalog()
    for s, m in remote_models(live).items():
        if any(m[k] != plan['models'][s][k] for k in ('id', 'pricing', 'context_length')): raise ValueError('Model pricing/configuration changed')
    ledger = BudgetLedger(ROOT / 'reports/product-v3/budget.json'); start = ledger.snapshot()
    if start['unknown_calls']: raise ValueError('Unknown paid calls outstanding')
    save(out / 'started.json', {'utc': datetime.now(timezone.utc).isoformat(), 'committed_usd_at_start': start['committed_usd'], 'automatic_replay': False})
    rows, calls = [], 0
    for case in plan['cases']:
        spent = ledger.snapshot()['committed_usd'] - start['committed_usd']
        budget = min(plan['per_job_max_usd'], MAX_USD - spent)
        if calls + plan['max_calls_per_job'] > MAX_CALLS or budget < plan['per_job_max_usd'] / 2:
            row = {'case': case, 'status': 'not_run_run_cap', 'model_calls': 0}
        else:
            print('START', case, flush=True)
            try:
                async with asyncio.timeout(1500):
                    value = await AdaptiveV4(ROOT, live, ledger=ledger).run(task_for(case), out / case, arm='v4', max_cost_usd=round(budget, 6))
            except Exception as exc:
                value = {'status': 'unknown', 'error': type(exc).__name__, 'tokens': None, 'cost_usd': None, 'model_calls': 0}
            row = {'case': case, **value}
            calls += row.get('model_calls') or 0
        rows.append(row); save(out / f'{case}-summary.json', row); report(out, rows, plan, False)
        print('DONE', case, row['status'], 'calls', row.get('model_calls'), 'tokens', row.get('tokens'), 'usd', row.get('cost_usd'), flush=True)
        if row['status'] == 'unknown' and row.get('error'): print('STOP: unknown outcome; remaining cases not run', flush=True); break
    report(out, rows, plan, True)
    print('REPORT', out / 'REPORT.md', flush=True)


def report(out, rows, plan, complete):
    v3 = read(FROZEN_V3); by = {(r['case'], r['arm']): r for r in v3['rows']}
    def agg(subset):
        e2e = [r['end_to_end_ms'] for r in subset if r.get('end_to_end_ms') is not None]
        verified = sum(r.get('status') == 'verified' for r in subset)
        tokens = None if any(r.get('tokens') is None for r in subset) else sum(r['tokens'] for r in subset)
        cost = None if any(r.get('cost_usd') is None for r in subset) else sum(r['cost_usd'] for r in subset)
        return {'jobs': len(subset), 'verified': verified, 'calls': sum(r.get('model_calls') or 0 for r in subset), 'tokens': tokens,
                'cost_usd': cost, 'usd_per_verified': cost / verified if cost is not None and verified else None,
                'median_e2e_s': statistics.median(e2e) / 1000 if e2e else None}
    done = [r['case'] for r in rows]
    arms = {'v4 (live)': agg(rows), **{a: agg([by[(c, a)] for c in done if (c, a) in by]) for a in ('ultra_only', 'fast', 'super_only')}}
    lines = ['# Adaptive v4 live pilot', '', f"Router `{plan['router']}`, contract `{plan['contract']}`. Real Nebius Sandbox and Token Factory. "
             f"Complete: {complete}.", '', plan['disclosure'], '',
             '## Per case', '', '| Case | v4 | v4 attempts | v3 ultra_only | v3 fast (Super→Ultra) | v3 super_only |', '| --- | --- | --- | --- | --- | --- |']
    for r in rows:
        att = ' → '.join(f"{a.get('stage')}:{a.get('outcome')}" for a in r.get('attempts', [])) or '—'
        lines.append(f"| {r['case']} | {r['status']} | {att} | " + ' | '.join(by.get((r['case'], a), {}).get('status', '—') for a in ('ultra_only', 'fast', 'super_only')) + ' |')
    lines += ['', '## Aggregates over the same cases', '', '| Route | Jobs | Verified | Calls | Tokens | USD | USD per verified | Median e2e (s) |',
              '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for name, a in arms.items():
        lines.append(f"| {name} | {a['jobs']} | {a['verified']} | {a['calls']} | {a['tokens']} | {a['cost_usd']} | {a['usd_per_verified']} | {a['median_e2e_s']} |")
    lines += ['', 'v3 rows are the frozen 29 Oct run (same model IDs, prices, caps, cases), not interleaved with this run. '
              'Network and service conditions differ between dates. Single pass, eight development-seen cases: no statistical or unseen-generalization claim. '
              'v4 may use a second Ultra call only after a real rejection; a gain over ultra_only can come from that extra call as well as from the evidence it carries — no blind-retry control was affordable within the 16-call cap.']
    save(out / 'pilot-view.json', {'complete': complete, 'rows': rows, 'aggregates': arms})
    (out / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('command', choices=['smoke', 'prepare', 'execute'])
    p.add_argument('protocol', nargs='?', type=Path); p.add_argument('--case', default='audit_3')
    a = p.parse_args()
    load_env_file(ROOT / '.env'); os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = IMAGE
    asyncio.run(smoke(a.case) if a.command == 'smoke' else prepare() if a.command == 'prepare' else execute(a.protocol))


if __name__ == '__main__':
    main()
