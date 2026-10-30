"""Benchmark metrics with explicit denominators and unknown-value handling."""
from statistics import mean, median
from ..app import ConcurrencyJobResult


def false_fix(repair):
    if not repair.get('patch', {}).get('success'):
        return False
    v = repair.get('verification')
    if not v or v.get('infrastructure_failures') or v.get('evidence', {}).get('execution_blocked'):
        return False
    if 'false_fix' in v:
        return v['false_fix']
    return v.get('passed') is False or bool(v.get('observed_program_failures', v.get('failed_runs', 0)) or v.get('regressions') or v.get('evidence', {}).get('sanitizer', {}).get('campaign', {}).get('failed_runs'))


def summarize(jobs: list[ConcurrencyJobResult]) -> dict[str, object]:
    repairs = [r for j in jobs for r in j.repairs]
    evaluated = [r for r in repairs if r.get('patch', {}).get('success') and r.get('verification') and not r['verification'].get('infrastructure_failures') and not r['verification'].get('evidence',{}).get('execution_blocked')]
    false_fixes = sum(false_fix(r) for r in repairs)
    verified = [j for j in jobs if j.status == 'verified']
    mock = any(j.inference_mode == 'mock' for j in jobs)
    calls = {t: sum(j.model_calls.get(t, 0) for j in jobs) for t in ('NANO','SUPER','ULTRA')}
    complete = bool(jobs) and all(j.metadata.get('usage_available',True) for j in jobs)
    costs = [j.cost_usd for j in jobs]
    authoritative = bool(jobs) and all(j.metadata.get('pricing_authoritative',False) for j in jobs)
    cost = sum(costs) if not mock and authoritative and all(c is not None for c in costs) else None
    durations = [j.total_time_ms for j in jobs]
    inference = [j.inference_latency_ms for j in jobs]
    verifications = [r['verification'] for r in repairs if r.get('verification')]
    races = [v.get('race_count') for v in verifications if v.get('sanitizer_passed') is not None]
    return {
        'tasks':len(jobs), 'attempted_fixtures':len({j.task for j in jobs}),
        'bugs_diagnosed':sum(any(r.get('proposal',{}).get('diagnosis') for r in j.repairs) for j in jobs),
        'diagnosis_definition':'Structured diagnosis present; correctness is not independently scored.',
        'candidate_repairs_generated':len(repairs), 'verified_repairs':len(verified),
        'verified_repair_rate':len(verified)/len(jobs) if jobs else None,
        'false_fixes':false_fixes,'false_fix_rate':false_fixes/len(evaluated) if evaluated else None,
        'false_fix_denominator':'Successfully applied candidates with a completed non-infrastructure verification outcome',
        'patches_rejected':sum(not r.get('patch',{}).get('success',False) for r in repairs),
        'format_rejections':sum(j.metadata.get('format_rejections',0) for j in jobs),
        'transport_infrastructure_failures':sum(j.metadata.get('infrastructure_failures',0) for j in jobs),
        'verification_infrastructure_failures':sum(v.get('infrastructure_failures',0) for v in verifications),
        'semantic_regression_count':sum(v.get('semantic_regression',False) for v in verifications),
        'race_count':sum(races) if races else None,
        'race_measurement':'Required/configured sanitizer campaigns only; uninstrumented zero is unknown',
        'deadlock_count':sum(v.get('deadlock_count',0) for v in verifications) if verifications else None,
        'tooling_unavailable':sum(j.status=='tooling_unavailable' for j in jobs),
        'model_calls':calls,'ultra_usage':calls['ULTRA'],'average_model_calls':sum(calls.values())/len(jobs) if jobs else None,
        'inference_tokens':sum(j.inference_tokens for j in jobs) if complete and not mock else None,
        'token_usage_complete':complete, 'tokens_per_verified_repair':sum(j.inference_tokens for j in jobs)/len(verified) if complete and verified and not mock else None,
        'inference_latency_ms':sum(inference), 'average_inference_latency_ms':mean(inference) if inference else None,
        'median_inference_latency_ms':median(inference) if inference else None,
        'average_end_to_end_latency_ms':mean(durations) if durations else None,
        'median_end_to_end_latency_ms':median(durations) if durations else None,
        'inference_measurement':'simulated' if mock else 'provider_reported_tokens_and_wall_clock_latency',
        'execution_latency_ms':sum(j.execution_latency_ms for j in jobs), 'total_time_ms':sum(durations),
        'average_time_to_verified_repair_ms':mean(j.total_time_ms for j in verified) if verified else None,
        'cost_usd':cost,'cost_per_verified_repair_usd':cost/len(verified) if cost is not None and verified else None,
        'inference_mode':'mock' if mock else 'real' if jobs else 'not_run'}
