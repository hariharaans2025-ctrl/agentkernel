"""Adaptive v4 CLI. `diagnose` and `prepare` start NO paid inference.

  python scripts/run_adaptive_v4.py diagnose            # offline taxonomy of the frozen v3 comparison
  python scripts/run_adaptive_v4.py prepare --query-live  # frozen protocol + live IDs/prices + bound check
Execution of a prepared protocol is deliberately not wired here until its bounds are approved.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import glob
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from agentkernel.repository import adaptive_v4_core as core  # noqa: E402
from agentkernel.repository.budget import BudgetLedger  # noqa: E402

FROZEN = ROOT / 'reports/cloud-comparison/20261029T170003Z'
PILOT_USD, PILOT_CALLS, CEILING_USD = 0.50, 16, 10.0
CAPS = {'super': 4096, 'ultra': 8192}
INPUT_CAP = 12000


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def new_dir():
    out = ROOT / 'reports/adaptive-v4' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False); return out


def diagnose(out):
    rows = []
    for f in sorted(glob.glob(str(FROZEN / '*-summary.json'))):
        s = json.loads(Path(f).read_text(encoding='utf-8'))
        for a in s['attempts']:
            t = core.classify_attempt(a)
            rows.append({'case': s['case'], 'arm': s['arm'], 'stage': a['stage'], 'outcome': a['outcome'],
                         'error_code': a.get('error_code'), **t, 'tokens': a.get('tokens'), 'cost_usd': a.get('cost_usd'),
                         'include_line_rewritten': '#include' in (a.get('response') or ''),
                         'quote_substituted': "'state.h'" in (a.get('response') or '')})
    summary = {}
    for r in rows:
        summary.setdefault(r['stage'], {}).setdefault(r['primary'], 0); summary[r['stage']][r['primary']] += 1
    sup = [r for r in rows if r['stage'] == 'super']
    findings = {
        'super_attempts': len(sup), 'super_rewrote_include_line': sum(r['include_line_rewritten'] for r in sup),
        'super_quote_closure_truncations': sum(r.get('signature') == 'string_closed_at_unescaped_quote' for r in sup),
        'super_single_quote_include_substitution': sum(r['quote_substituted'] for r in sup),
        'interpretation': ('Super failures concentrate on rewriting the unchanged #include "state.h" line under a strict JSON '
                           'schema; the unescaped quote closes the JSON string (contract defect), or the include is replaced and '
                           'later line numbers shift. Remaining Super candidates failed real verifier gates. Unresolved Ultra '
                           'cases: audit_3 removed the lock (TSan race, unsymbolized stacks); rendezvous_3 kept barrier waits '
                           'inside the mutex (100/100 TIMEOUT). v3 fallback received only outcome summaries, not candidate evidence.')}
    value = {'source': str(FROZEN.relative_to(ROOT)), 'rows': rows, 'by_stage_primary': summary, 'findings': findings,
             'scope': 'Development-seen diagnosis only; not evaluation evidence.'}
    (out / 'diagnosis.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
    return value


async def live_models():
    import httpx
    from agentkernel.config import load_env_file
    load_env_file(ROOT / '.env')
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get('https://api.tokenfactory.nebius.com/v1/models', params={'verbose': 'true'},
                        headers={'Authorization': 'Bearer ' + os.environ['NEBIUS_API_KEY']})
        r.raise_for_status(); return r.json()['data']


def quote(m, cap):
    p = m['pricing']; ctx = m['context_length']
    return float(p['prompt']) * min(INPUT_CAP, ctx - cap) + float(p['completion']) * cap + float(p.get('request', 0))


def prepare(out, models):
    from agentkernel.repository.adaptive_v3 import remote_models
    chosen = remote_models(models) if models else None
    q = {s: quote(m, CAPS[s]) for s, m in chosen.items()} if chosen else None
    dev = ['ledger_2', 'snapshot_2', 'capacity_2', 'predicate_2']
    dev_calls = {'super_v3_contract': len(dev), 'super_v4_contract': len(dev), 'ultra_v4_evidence_correction_max': len(dev)}
    dev_bound = (q['super'] * 8 + q['ultra'] * 4) if q else None
    heldout_calls = {'super_only': 5, 'ultra_only': 5, 'fixed_fallback_max': 10, 'v4_max': 10}
    heldout_bound = (q['super'] * 5 + q['ultra'] * 5 + (q['super'] + q['ultra']) * 10) if q else None
    ledger = BudgetLedger(ROOT / 'reports/product-v3/budget.json').snapshot()
    protocol = {
        'frozen_utc': datetime.now(timezone.utc).isoformat(), 'route': 'agentkernel/adaptive-v4', 'contract': core.CONTRACT_ID,
        'router': core.ROUTER_VERSION, 'system_prompt_sha256': hashlib.sha256(core.SYSTEM_V4.encode()).hexdigest(),
        'example_rule': core.EXAMPLE_RULE, 'models': chosen, 'caps': CAPS, 'input_cap': INPUT_CAP, 'temperature': 0,
        'thinking': False, 'attempts': {'max_calls_per_job': 2, 'max_format_recoveries': 1, 'max_verifier_recoveries': 1},
        'no_retries': True, 'cache_used': False, 'image': 'agentkernel-clang:20261003122908',
        'verification': {'stress_runs': 100, 'tsan_runs': 3, 'original_tests': True, 'semantics_required': True, 'majority_pass': False},
        'implementation_sha256': {p: sha(ROOT / p) for p in ('src/agentkernel/repository/adaptive_v4_core.py',
                                  'src/agentkernel/repository/adaptive_v4.py', 'scripts/run_adaptive_v4.py')},
        'stage_A_development_pilot': {'programs': dev, 'source': 'datasets/adaptive-v3/product-v1 validation/train variants (families seen)',
                                      'purpose': 'compare v3 JSON vs v4 block contract on Super; calibrate router buckets',
                                      'paid_calls_max': sum(dev_calls.values()), 'calls': dev_calls, 'reserved_usd_bound': dev_bound,
                                      'within_delegated_cap': bool(dev_bound is not None and dev_bound <= PILOT_USD and sum(dev_calls.values()) <= PILOT_CALLS)},
        'stage_B_heldout_comparison': {'design': '5 new whole-program families not in product-v1 (refcount, handoff, rwlock stats, '
                                       'relaxed-flag publish, lazy once-init); references kept outside model inputs',
                                       'arms': heldout_calls, 'arm_order': 'rotated per case (Latin square)', 'concurrency': 1,
                                       'paid_calls_max': sum(heldout_calls.values()), 'reserved_usd_bound': heldout_bound,
                                       'within_delegated_cap': False,
                                       'status': 'REQUIRES EXPLICIT EXPANDED LIMIT; fixtures not yet built/validated'},
        'ledger': {'committed_usd': ledger['committed_usd'], 'unknown_calls': ledger['unknown_calls'], 'conservative_ceiling_usd': CEILING_USD,
                   'stored_total_is_not_permission': True},
        'targets': {'verified_vs_ultra_only': '>= equal', 'hosted_spend_reduction': '>= 25%', 'median_e2e_reduction': '>= 20%'}}
    (out / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    (out / 'hashes.json').write_text(json.dumps({'protocol.json': sha(out / 'protocol.json')}, indent=2), encoding='utf-8')
    return protocol


def scorecard(out, diag, protocol):
    f = diag['findings']; s = diag['by_stage_primary']
    lines = ['# Adaptive v4 scorecard (offline, judge-readable)', '',
             'No new paid inference was run for this record. All counts below come from the preserved v3 comparison '
             '(`reports/cloud-comparison/20261029T170003Z`, 6/8 Ultra-only, 6/8 fixed fallback, 0/8 Super-only), now development-seen.', '',
             '## Failure taxonomy of preserved attempts', '', '| Stage | ' + ' | '.join(core.CATEGORIES) + ' |',
             '| --- |' + ' --- |' * len(core.CATEGORIES)]
    for stage, c in s.items(): lines.append(f'| {stage} | ' + ' | '.join(str(c.get(k, 0)) for k in core.CATEGORIES) + ' |')
    lines += ['', f"Super attempts: {f['super_attempts']}; rewrote the unchanged include line: {f['super_rewrote_include_line']}; "
              f"quote-closure truncation: {f['super_quote_closure_truncations']}; `'state.h'` substitution: {f['super_single_quote_include_substitution']}.",
              '', f"Interpretation: {f['interpretation']}", '', '## Prepared, not executed', '',
              f"- Stage A development pilot: {protocol['stage_A_development_pilot']['paid_calls_max']} calls max, reserved bound "
              f"${protocol['stage_A_development_pilot']['reserved_usd_bound']}, within delegated cap: {protocol['stage_A_development_pilot']['within_delegated_cap']}.",
              f"- Stage B held-out four-arm comparison: {protocol['stage_B_heldout_comparison']['paid_calls_max']} calls max, reserved bound "
              f"${protocol['stage_B_heldout_comparison']['reserved_usd_bound']}: exceeds the 16-call/$0.50 delegated cap, so it needs an explicit expanded limit.", '',
              '## Claims', '', 'Supported: the Super failures in the frozen run are dominated by a response-contract defect that is reproducible offline.',
              '', 'Unsupported (not measured): any v4 verified-count, cost or latency improvement; any statistical claim.']
    (out / 'SCORECARD.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('command', choices=['diagnose', 'prepare'])
    p.add_argument('--query-live', action='store_true', help='GET the model catalog (no inference)')
    a = p.parse_args(); out = new_dir(); diag = diagnose(out)
    if a.command == 'prepare':
        protocol = prepare(out, asyncio.run(live_models()) if a.query_live else None); scorecard(out, diag, protocol)
    print(json.dumps({'evidence': str(out), 'paid_calls_started': 0, 'findings': diag['findings']}, indent=2))


if __name__ == '__main__':
    main()
