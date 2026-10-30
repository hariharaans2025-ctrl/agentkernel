import pytest
from agentkernel.repository.budget import BudgetLedger


def ledger(tmp_path):
    value = BudgetLedger(tmp_path / 'budget.json')
    value.initialize(total_usd=1, opening_reservation_usd=.1, authorization='test')
    return value


def test_unknown_paid_call_keeps_reservation_and_cannot_replay(tmp_path):
    value = ledger(tmp_path)
    value.reserve('first', bound_usd=.7, model='model', evidence='test')
    value.unknown('first', 'timeout')
    assert value.snapshot()['remaining_usd'] == pytest.approx(.2)
    with pytest.raises(ValueError): value.reserve('first', bound_usd=.1, model='model', evidence='test')
    with pytest.raises(ValueError): value.reserve('second', bound_usd=.21, model='model', evidence='test')


def test_actual_usage_releases_unused_reservation(tmp_path):
    value = ledger(tmp_path)
    value.reserve('first', bound_usd=.7, model='model', evidence='test')
    value.settle('first', actual_usd=.05, input_tokens=10, output_tokens=20)
    assert value.snapshot()['remaining_usd'] == pytest.approx(.85)
    assert value.snapshot()['known_new_spend_usd'] == .05
    with pytest.raises(ValueError): value.settle('first', actual_usd=.05, input_tokens=10, output_tokens=20)


def test_exceeding_provider_charge_stops_without_losing_reservation(tmp_path):
    value = ledger(tmp_path)
    value.reserve('first', bound_usd=.7, model='model', evidence='test')
    with pytest.raises(ValueError): value.settle('first', actual_usd=.71, input_tokens=10, output_tokens=20)
    assert value.snapshot()['committed_usd'] == pytest.approx(.8)


def test_new_process_cannot_reset_authorized_budget(tmp_path):
    value = ledger(tmp_path)
    again = BudgetLedger(value.path)
    again.initialize(total_usd=100, authorization='different')
    assert again.snapshot()['total_usd'] == 1
