"""Paid-route protocol tests: no inference request or C execution is performed."""
import json
from decimal import Decimal

import pytest

from agentkernel.repository.remote_repair import (
    RepairRequestError, parse_remote_response, plan_remote_repair, quote_repair_model,
    repair_messages, repair_schema,
)


SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"
SOURCES = {"src/worker.c": "void tick(void) {\n  sched_yield();\n  work();\n}\n"}


def model(identifier=SUPER):
    return {"id": identifier, "context_length": 100000,
            "pricing": {"prompt": ".000001", "completion": ".000002", "request": ".01"}}


def plan(identifier=SUPER, **kwargs):
    limits = {"max_cost_usd": .25, "max_output_tokens": 4096, "max_total_tokens": 52100}
    limits.update(kwargs)
    return plan_remote_repair(model(identifier), repair_messages(SOURCES), SOURCES, **limits)


def valid_text():
    return json.dumps({"edits": [{"file": "src/worker.c", "search": "  sched_yield();\n  work();",
                                 "replacement": "  lock();\n  sched_yield();\n  work();\n  unlock();"}]})


def completion(text=None, **changes):
    value = {"model": SUPER, "usage": {"prompt_tokens": 200, "completion_tokens": 100,
             "completion_tokens_details": {"reasoning_tokens": 0}},
             "choices": [{"finish_reason": "stop", "message": {"content": valid_text() if text is None else text}}]}
    value.update(changes)
    return value


@pytest.mark.parametrize("identifier", [SUPER, ULTRA])
def test_both_fallbacks_use_nonempty_minimal_schema_and_disable_thinking(identifier):
    request = plan(identifier)
    assert request.payload["chat_template_kwargs"] == {"enable_thinking": False, "force_nonempty_content": True}
    fmt = request.payload["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema["required"] == ["edits"] and schema["additionalProperties"] is False
    assert schema["properties"]["edits"]["minItems"] == 1
    assert schema["$defs"]["SourceEdit"]["properties"]["file"]["enum"] == ["src/worker.c"]
    assert request.payload["max_tokens"] == 4096 and request.payload["n"] == 1


def test_unsupported_model_does_not_receive_speculative_template_extensions():
    assert "chat_template_kwargs" not in plan("some/other-model").payload


@pytest.mark.parametrize("files", [[], ["../oracle.c"], ["C:/oracle.c"], ["bad\\file.c"],
                                   ["file.py"], ["foo.c", "foo.c"], [None], ["a//b.c"]])
def test_schema_cannot_allow_extra_protected_or_ambiguous_paths(files):
    with pytest.raises(RepairRequestError, match="invalid_editable_files"):
        repair_schema(files)


def test_compact_messages_only_use_given_sources_headers_and_evidence():
    headers = {"types.h": "void tick(void);"}
    messages = repair_messages(SOURCES, headers, {"task": "observed failure", "baseline": {"failed_runs": 3}})
    assert len(messages) == 2 and messages[-1]["role"] == "user"
    assert "types.h" in messages[-1]["content"]
    assert "reference_repair" not in messages[-1]["content"]
    assert "untrusted data" in messages[0]["content"]
    with pytest.raises(RepairRequestError):
        repair_messages(SOURCES, {"oracle.c": "test source"})


def test_request_reserves_reviewed_input_output_and_fee_before_any_call():
    request = plan()
    assert request.reservation_usd == pytest.approx(.048 + .008192 + .01)
    assert quote_repair_model(model(), max_output_tokens=8192) == pytest.approx(.048 + .016384 + .01)
    assert request.input_token_bound < request.max_input_tokens
    assert "Required JSON response schema" in request.payload["messages"][-1]["content"]
    with pytest.raises(RepairRequestError, match="charge_budget_exceeded"):
        plan(max_cost_usd=.01)


@pytest.mark.parametrize("limits,code", [
    ({"max_output_tokens": True}, "invalid_output_limit"),
    ({"max_output_tokens": 8193}, "invalid_output_limit"),
    ({"max_input_tokens": 100}, "input_budget_exceeded"),
    ({"max_total_tokens": 4100}, "input_budget_exceeded"),
    ({"max_total_tokens": 4096}, "total_token_budget_exceeded"),
    ({"max_cost_usd": float("nan")}, "invalid_approved_charge"),
    ({"max_cost_usd": True}, "invalid_approved_charge"),
])
def test_preflight_never_silently_changes_reviewed_limits(limits, code):
    with pytest.raises(RepairRequestError, match=code):
        plan(**limits)


def test_unusable_pricing_is_not_treated_as_free_inference():
    for prices in ({"prompt": "NaN", "completion": "0"}, {"prompt": "-1", "completion": "0"}, {}):
        with pytest.raises(RepairRequestError):
            quote_repair_model({**model(), "pricing": prices})


def test_valid_edits_create_only_a_candidate_not_a_verified_repair():
    result = parse_remote_response(completion(), plan(), SOURCES)
    assert result.outcome == "candidate" and not result.may_escalate
    assert result.proposal.patch.startswith("--- a/src/worker.c")
    assert result.tokens == 300 and result.cost_usd == pytest.approx(.0104)
    assert result.proposal.confidence == 0 and "not model confidence" in result.canonical_text


@pytest.mark.parametrize("text", ["{}", '{"diagnosis":"deadlock"}', '{"edits":[]}',
                                   "```json\n{}\n```", "null", '{"edits":[],"edits":[]}',
                                   '{"patch":"--- a/src/worker.c"}'])
def test_contract_failure_keeps_known_billable_usage_and_allows_only_explicit_escalation(text):
    result = parse_remote_response(completion(text), plan(), SOURCES)
    assert result.outcome == "invalid_output" and result.tokens == 300
    assert result.cost_usd == pytest.approx(.0104) and result.may_escalate
    assert result.proposal is None


def test_protected_file_edit_is_rejected_even_if_provider_ignores_schema():
    text = json.dumps({"edits": [{"file": "oracle.c", "search": "work();", "replacement": "return;"}]})
    result = parse_remote_response(completion(text), plan(), SOURCES)
    assert result.outcome == "invalid_output" and result.validation[0]["type"] == "edit_path_not_allowed"


def test_changed_scheduling_hooks_rejected_before_expensive_verification():
    text = json.dumps({"edits": [{"file": "src/worker.c", "search": "  sched_yield();", "replacement": "  lock();"}]})
    result = parse_remote_response(completion(text), plan(), SOURCES)
    assert result.outcome == "invalid_output" and result.error_code == "scheduling_hooks_changed"


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "completion_tokens": 10},
                                    {"prompt_tokens": 10, "completion_tokens": -1},
                                    {"prompt_tokens": 48001, "completion_tokens": 100},
                                    {"prompt_tokens": 100, "completion_tokens": 4097}])
def test_unknown_or_over_contract_usage_stops_without_another_paid_call(usage):
    result = parse_remote_response(completion(usage=usage), plan(), SOURCES)
    assert result.outcome == "unknown" and result.cost_usd is None and not result.may_escalate


def test_truncated_reasoning_preserves_charge_but_never_becomes_a_patch():
    data = completion(usage={"prompt_tokens": 200, "completion_tokens": 4096,
                            "completion_tokens_details": {"reasoning_tokens": 4096}},
                      choices=[{"finish_reason": "length", "message": {"content": None, "reasoning_content": "a proposed fix"}}])
    result = parse_remote_response(data, plan(), SOURCES)
    assert result.outcome == "invalid_output" and result.error_code == "output_budget_exhausted"
    assert result.reasoning_tokens == 4096 and result.cost_usd == pytest.approx(.018392)
    assert result.proposal is None and result.may_escalate


def test_reasoning_only_or_refusal_is_not_rescued_into_code():
    for message, code in (({"content": "", "reasoning_content": valid_text()}, "reasoning_only_response"),
                          ({"content": valid_text(), "refusal": "refused"}, "model_refusal")):
        result = parse_remote_response(completion(choices=[{"finish_reason": "stop", "message": message}]), plan(), SOURCES)
        assert result.outcome == "invalid_output" and result.error_code == code
        assert result.proposal is None and result.usage_known


def test_returned_model_mismatch_keeps_full_reservation_unknown():
    result = parse_remote_response(completion(model="different/model"), plan(), SOURCES)
    assert result.outcome == "unknown" and result.error_code == "returned_model_mismatch"
    assert result.input_tokens == 200 and result.cost_usd is None and not result.may_escalate


def test_source_c_quotes_and_newlines_are_encoded_exactly_once():
    source = {"src/worker.c": 'puts("PASS\\n");\n'}
    request = plan_remote_repair(model(), repair_messages(source), source, max_cost_usd=.25)
    text = json.dumps({"edits": [{"file": "src/worker.c", "search": source["src/worker.c"],
                                 "replacement": 'lock();\nputs("PASS\\n");\nunlock();\n'}]})
    result = parse_remote_response(completion(text), request, source)
    assert result.outcome == "candidate" and 'puts("PASS\\n");' in result.proposal.patch


def test_provider_missing_finish_reason_stops_route_despite_known_usage():
    result = parse_remote_response(completion(choices=[{"message": {"content": valid_text()}}]), plan(), SOURCES)
    assert result.outcome == "unknown" and result.usage_known and not result.may_escalate


def test_global_token_balance_reduces_input_limit_without_raising_total():
    request = plan(max_total_tokens=10000)
    assert request.max_input_tokens == 5904 and request.max_total_tokens == 10000
    result = parse_remote_response(completion(usage={"prompt_tokens": 5905, "completion_tokens": 4096}), request, SOURCES)
    assert result.outcome == "unknown" and not result.may_escalate
