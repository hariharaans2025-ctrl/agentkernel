"""Measured single-attempt benchmark metrics; missing values stay unknown."""
from datetime import datetime


OUTPUT_CAP = 2048
INPUT_BYTE_CAP = 12000


def elapsed(start, end):
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000 if start and end else None


def model_metrics(item, *, real=True):
    job = item.get('job') or {}
    inf = (item.get('inference') or {}) if real else {}
    meta = inf.get('metadata') or {}
    history = item.get('inferences', [inf] if inf else []) if real else []
    def measured_sum(key):
        values = [i.get('metadata', {}).get(key) for i in history]
        return sum(values) if values and all(v is not None for v in values) else None
    baseline = job.get('baseline') or {}
    verification = job.get('verification') or {}
    repairs = job.get('repairs') or []
    patches = [r.get('proposal', {}).get('patch', '') for r in repairs]
    lines = '\n'.join(patches).splitlines()
    latency = sum(i['latency_ms'] for i in history) if history else None
    output = measured_sum('actual_output_tokens')
    incoming = measured_sum('actual_input_tokens')
    total = verification.get('total_runs')
    passed = verification.get('passed_runs')
    return {
        'input_tokens': incoming, 'output_tokens': output,
        'total_tokens': incoming + output if incoming is not None and output is not None else None,
        'reasoning_tokens': measured_sum('actual_reasoning_tokens'),
        'output_budget_utilization': output / measured_sum('requested_max_output_tokens') if output is not None and measured_sum('requested_max_output_tokens') else None,
        'inference_ms': latency,
        'effective_output_tokens_per_second': output / (latency / 1000) if output is not None and latency else None,
        'end_to_end_ms': elapsed(item.get('started_at'), item.get('finished_at')),
        'baseline_ms': baseline.get('duration_ms'), 'baseline_runs': baseline.get('total_runs'),
        'baseline_failures': baseline.get('failed_runs'),
        'patch_accepted': any(r.get('patch', {}).get('success') for r in repairs) if job else None,
        'patch_added_lines': sum(line.startswith('+') and not line.startswith('+++') for line in lines) if patches else None,
        'patch_removed_lines': sum(line.startswith('-') and not line.startswith('---') for line in lines) if patches else None,
        'build_passed': verification.get('build_passed'),
        'execution_passed': verification.get('execution_passed'),
        'semantic_passed': verification.get('semantic_passed'),
        'sanitizer_passed': verification.get('sanitizer_passed'),
        'false_fix': any(r.get('false_fix', r.get('verification', {}).get('false_fix', False)) for r in repairs),
        'final_tier': job.get('metadata', {}).get('final_tier'),
        'nano_calls': job.get('model_calls', {}).get('NANO'),
        'super_calls': job.get('model_calls', {}).get('SUPER'),
        'ultra_calls': job.get('model_calls', {}).get('ULTRA'),
        'verification_ms': verification.get('duration_ms'), 'verification_runs': total,
        'verification_passes': passed, 'verification_pass_rate': passed / total if total else None,
        'deadlocks': verification.get('deadlock_count'), 'races': verification.get('race_count') if verification.get('sanitizer_passed') is not None else None,
        'crashes': verification.get('crash_count'), 'infrastructure_failures': verification.get('infrastructure_failures'),
        'verified': job.get('status') == 'verified',
        'estimated_inference_cost_usd': inf.get('estimated_cost_usd'),
        'finish_reason': meta.get('finish_reason'), 'error_code': meta.get('error_code'),
        'sanitizer_status': verification.get('evidence', {}).get('sanitizer', {}).get('status', 'not_measured'),
    }


def benchmark_metrics(run):
    individual = {tier: model_metrics(item, real=run.get('provenance') == 'real') for tier, item in run['results'].items()}
    values = list(individual.values())
    combined = {'selected_models': len(values), 'verified_models': sum(m['verified'] for m in values),
                'end_to_end_ms': elapsed(run.get('created_at'), run.get('finished_at'))}
    for field in ('input_tokens', 'output_tokens', 'total_tokens', 'inference_ms', 'estimated_inference_cost_usd'):
        present = [m[field] for m in values if m[field] is not None]
        combined[field] = sum(present) if len(present) == len(values) else None
        combined[field + '_known_subtotal'] = sum(present) if present else None
    measured = [m for m in values if m['verification_runs'] is not None]
    combined['models_with_verification'] = len(measured)
    combined['verification_runs'] = sum(m['verification_runs'] for m in measured)
    combined['verification_passes'] = sum(m['verification_passes'] or 0 for m in measured)
    combined['verification_pass_rate'] = combined['verification_passes'] / combined['verification_runs'] if combined['verification_runs'] else None
    for field in ('verification_ms', 'deadlocks', 'races', 'crashes', 'infrastructure_failures'):
        known = [m[field] for m in measured if m[field] is not None]
        combined[field] = sum(known) if measured and len(known) == len(measured) else None
    combined['patches_accepted'] = sum(m['patch_accepted'] is True for m in values)
    combined['verified_model_rate'] = combined['verified_models'] / len(values) if values else None
    return {'individual': individual, 'combined': combined,
            'notes': ['One attempt per model on one fixture; not a statistical model ranking.',
                      'Effective token rate includes catalog check and request overhead; it is not decode throughput.',
                      'Combined metrics aggregate independent runs, not an ensemble.',
                      'Unknown usage/cost is null; known subtotals are explicitly labeled. Sandbox cost is excluded.',
                      'A passing campaign does not establish semantic equivalence.']}
