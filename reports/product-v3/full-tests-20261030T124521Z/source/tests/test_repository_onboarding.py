import json
from pathlib import Path
import pytest
from agentkernel.repository.onboarding import Budgets, RepositoryContract, create_plan
from agentkernel.repository.metrics import TokenBudget, summarize

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples/job-queue-service'


def contract():
    return json.loads((EXAMPLE / 'agentkernel.repository.json').read_text())


def test_example_plan_is_readonly_and_distinguishes_protected_files(tmp_path):
    result = create_plan(EXAMPLE, EXAMPLE / 'agentkernel.repository.json', tmp_path / 'plan')
    assert result['state'] == 'PLANNED_NOT_EXECUTED'
    assert result['model_calls'] == 0
    assert result['metrics']['input_tokens'] is None
    assert result['files']['src/queue.c']['editable']
    assert not result['files']['src/main.c']['editable']
    assert result['task']['verification_config']['stress_runs'] == 100
    assert result['task']['verification_config']['sanitizer_runs'] == 3
    assert not (EXAMPLE / 'job_service').exists()
    with pytest.raises(FileExistsError):
        create_plan(EXAMPLE, EXAMPLE / 'agentkernel.repository.json', tmp_path / 'plan')


@pytest.mark.parametrize('path', ['../x.c', '/x.c', 'C:/x.c', '.env', '.git/config', 'secrets.json', 'id.key', 'src\\x.c', 'a//b.c'])
def test_disallow_unsafe_or_secret_paths(path):
    data = contract()
    data['support_files'].append(path)
    with pytest.raises(ValueError): RepositoryContract.model_validate(data)


def test_prevent_editing_protected_test_by_case_alias():
    data = contract()
    data['source_files'].append('SRC/MAIN.C')
    with pytest.raises(ValueError): RepositoryContract.model_validate(data)


@pytest.mark.parametrize('key,value', [('stress_runs', 10), ('sanitizer_runs', 1), ('sanitizer_required', False),
    ('required_original_tests', False), ('allowed_deadlocks', 1), ('unknown_option', 1)])
def test_reject_weakened_or_mistyped_verification(key, value):
    data = contract()
    data['verification'][key] = value
    with pytest.raises(ValueError): RepositoryContract.model_validate(data)


def test_missing_file_leaves_no_output(tmp_path):
    data = contract()
    data['support_files'].append('missing.c')
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(data))
    with pytest.raises(ValueError): create_plan(EXAMPLE, config, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_link_escape_rejected(tmp_path):
    outside = tmp_path / 'outside.c'
    outside.write_text('sensitive')
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'escape.c').symlink_to(outside)
    data = contract()
    data['source_files'] = ['escape.c']
    config = tmp_path / 'config.json'
    config.write_text(json.dumps(data))
    with pytest.raises(ValueError): create_plan(root, config, tmp_path / 'out')


def test_reservation_blocks_overbudget_and_concurrent_calls():
    ledger = TokenBudget(Budgets(max_total_tokens=100, max_input_tokens_per_call=60, max_output_tokens_per_call=40))
    ledger.reserve(60, 40)
    with pytest.raises(ValueError): ledger.reserve(1, 1)
    ledger.settle(60, 30)
    with pytest.raises(ValueError): ledger.reserve(10, 1)
    assert ledger.spent == 90 and ledger.calls == 1


def test_unknown_usage_stops_more_calls():
    ledger = TokenBudget(Budgets())
    ledger.reserve(100, 100)
    ledger.settle(None, None)
    with pytest.raises(ValueError): ledger.reserve(100, 100)


def test_provider_overrun_preserves_usage_and_blocks_more_calls():
    ledger = TokenBudget(Budgets())
    ledger.reserve(100, 100)
    with pytest.raises(ValueError): ledger.settle(110, 100)
    assert ledger.spent == 210
    with pytest.raises(ValueError): ledger.reserve(1, 1)


def test_metrics_include_failed_cost_and_preserve_unknown():
    rows = [dict(outcome='verified', tokens=100, model_calls=1, inference_ms=10, verification_ms=20, end_to_end_ms=35, cost_usd=None),
            dict(outcome='rejected', tokens=300, model_calls=2, inference_ms=10, verification_ms=20, end_to_end_ms=40, cost_usd=None)]
    result = summarize(rows)
    assert result['tokens_per_verified_repair'] == 400
    assert result['cost_usd'] is None
    rows.append({'outcome': 'interrupted'})
    result = summarize(rows)
    assert result['unknown'] == 1 and result['rejected'] == 1
    assert result['tokens'] is None and result['tokens_per_verified_repair'] is None
