import pytest
from agentkernel.repository.learning import require_verified, evaluation_metrics


def test_false_fix_with_all_stress_passes_cannot_enter_training():
    with pytest.raises(ValueError):
        require_verified({'passed':False,'passed_runs':100,'false_fix':True},{'stress_runs':100})


def test_zero_verified_has_no_token_efficiency():
    r=evaluation_metrics([{'outcome':'rejected','tokens':600,'false_fix':True}])
    assert r['tokens_per_verified_repair'] is None and r['false_fixes']==1


def test_failed_attempt_tokens_count_towards_success_cost():
    r=evaluation_metrics([{'outcome':'verified','tokens':400},{'outcome':'rejected','tokens':600}])
    assert r['tokens_per_verified_repair']==1000


def test_unknown_usage_and_latency_stay_unknown():
    r=evaluation_metrics([{'outcome':'verified','tokens':400,'inference_ms':10},{'outcome':'unknown','tokens':None}])
    assert r['tokens'] is None and r['tokens_per_verified_repair'] is None
    assert r['inference_latency']['total_ms'] is None and r['unknown']==1


def test_tsan_cannot_be_skipped_for_required_configuration():
    v={'passed':True,'build_passed':True,'total_runs':100,'passed_runs':100,'failed_runs':0,
       'infrastructure_failures':0,'semantic_passed':True,'sanitizer_passed':True}
    with pytest.raises(ValueError):
        require_verified(v,{'stress_runs':100,'semantic_checks':[{}],'sanitizer_required':True,'sanitizer_runs':3})
