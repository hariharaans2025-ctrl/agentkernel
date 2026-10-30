import asyncio
import pytest
from agentkernel.repository.adaptive_v3 import ProductRepair, product_quote
from agentkernel.repository.learning import require_verified


def models():
    return [{'id':name,'context_length':128000,'pricing':{'prompt':'.000001','completion':'.000003','request':'0'}} for name in
            ('nvidia/nemotron-3-super-120b-a12b','nvidia/Nemotron-3-Ultra-550b-a55b')]


def test_expanded_route_reserves_each_stage_full_output_cap(monkeypatch):
    monkeypatch.delenv('AGENTKERNEL_NEMOTRON_SUPER_MODEL',raising=False)
    monkeypatch.delenv('AGENTKERNEL_NEMOTRON_ULTRA_MODEL',raising=False)
    assert product_quote(models()) == pytest.approx(.096+(4096+8192)*.000003)


def test_profile_contract_preflight_never_starts_execution_or_paid_calls(tmp_path, monkeypatch):
    monkeypatch.delenv('AGENTKERNEL_NEMOTRON_SUPER_MODEL',raising=False)
    monkeypatch.delenv('AGENTKERNEL_NEMOTRON_ULTRA_MODEL',raising=False)
    runner=ProductRepair(tmp_path,models())
    for options in ({'max_cost_usd':.01}, {'max_cost_usd':1,'max_output_tokens':2048},
                    {'max_cost_usd':1,'max_calls':1}, {'max_cost_usd':float('nan')}):
        with pytest.raises(ValueError): asyncio.run(runner.run(None,tmp_path/'must-not-exist',**options))
        assert not (tmp_path/'must-not-exist').exists()


def test_larger_verification_contract_requires_every_reviewed_run():
    config={'stress_runs':200,'semantic_checks':[{}],'sanitizer_required':True,'sanitizer_runs':5}
    value={'passed':True,'build_passed':True,'total_runs':200,'passed_runs':200,'failed_runs':0,
           'infrastructure_failures':0,'regressions':[],'semantic_passed':True,'false_fix':False,
           'sanitizer_passed':True,'evidence':{'sanitizer':{'campaign':{'total_runs':5,'counts':{'PASS':5}}}}}
    require_verified(value,config)
    value['passed_runs']=100
    with pytest.raises(ValueError): require_verified(value,config)
