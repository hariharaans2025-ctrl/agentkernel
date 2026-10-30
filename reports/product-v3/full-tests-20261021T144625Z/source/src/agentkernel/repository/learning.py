"""Fail-closed dataset admission and verifier-first evaluation metrics."""
from statistics import median


def require_verified(v, config):
    if not (v.get('passed') is True and v.get('build_passed') is True
            and type(config.get('stress_runs')) is int and config['stress_runs'] >= 100 and v.get('total_runs') == config['stress_runs']
            and v.get('passed_runs') == config['stress_runs'] and v.get('failed_runs') == 0
            and v.get('infrastructure_failures') == 0 and not v.get('regressions')
            and v.get('semantic_passed') is True and not v.get('false_fix')):
        raise ValueError('Unverified repair cannot be admitted')
    if not config.get('semantic_checks'):
        raise ValueError('Semantic oracle required')
    if config.get('sanitizer_required'):
        campaign=v.get('evidence',{}).get('sanitizer',{}).get('campaign',{})
        if (v.get('sanitizer_passed') is not True or type(config.get('sanitizer_runs')) is not int or config['sanitizer_runs'] < 3
                or campaign.get('total_runs') != config['sanitizer_runs'] or campaign.get('counts') != {'PASS':config['sanitizer_runs']}):
            raise ValueError('Required TSan evidence missing')


def evaluation_metrics(rows):
    """Failures consume tokens too; incomplete usage never becomes zero."""
    verified=sum(r.get('outcome')=='verified' for r in rows)
    unknown=sum(r.get('outcome')=='unknown' for r in rows)
    tokens=None if any(r.get('tokens') is None for r in rows) else sum(r['tokens'] for r in rows)
    def timing(key):
        values=[r[key] for r in rows if r.get(key) is not None]
        return {'observations':len(values),'median_ms':median(values) if values else None,
                'total_ms':sum(values) if len(values)==len(rows) else None}
    return {'jobs':len(rows),'verified_repairs':verified,'verified_rate':verified/len(rows) if rows else None,
        'unknown':unknown,'false_fixes':sum(r.get('false_fix') is True for r in rows),
        'tokens':tokens,'tokens_per_verified_repair':tokens/verified if tokens is not None and verified else None,
        'inference_latency':timing('inference_ms'),'verification_latency':timing('verification_ms'),
        'end_to_end_latency':timing('end_to_end_ms')}
