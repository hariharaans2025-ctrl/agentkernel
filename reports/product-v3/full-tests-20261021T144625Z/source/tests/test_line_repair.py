"""Line repairs preserve frozen positions, guarded source and paid usage."""
import json

import pytest

from agentkernel.repository.line_repair import line_messages, line_schema, plan_line_repair, parse_line_response
from agentkernel.repository.remote_repair import RepairRequestError


MODEL={"id":"nvidia/nemotron-3-super-120b-a12b","context_length":100000,
       "pricing":{"prompt":".000001","completion":".000002","request":".01"}}
SOURCE={"worker.c":"void run(void) {\n  sched_yield();\n  work();\n}\n"}


def plan(sources=None, **kwargs):
    sources=SOURCE if sources is None else sources
    limits={"max_cost_usd":.25,"max_output_tokens":4096,"max_total_tokens":52100};limits.update(kwargs)
    return plan_line_repair(MODEL,line_messages(sources),sources,**limits)


def response(edits, **kwargs):
    value={"model":MODEL["id"],"usage":{"prompt_tokens":200,"completion_tokens":100},
           "choices":[{"finish_reason":"stop","message":{"content":json.dumps({"edits":edits})}}]}
    value.update(kwargs);return value


def edit(start=3,end=3,lines=None,file="worker.c"):
    return {"file":file,"start_line":start,"end_line":end,
            "replacement_lines":["  lock();","  work();","  unlock();"] if lines is None else lines}


def test_raw_numbered_source_does_not_encode_c_newlines_or_quotes():
    sources={"a.c":'puts("hello\\n");\nnext();\n'}
    chat=line_messages(sources,{"api.hpp":"void run();"},{"failed_runs":3})
    assert '000001|puts("hello\\n");' in chat[-1]["content"]
    assert "000002|next();" in chat[-1]["content"]
    assert "READONLY HEADER: api.hpp" in chat[-1]["content"]
    assert "search strings" in chat[0]["content"]


def test_line_schema_has_nonempty_exact_files_and_bounded_individual_lines():
    schema=line_schema({"x.cpp":"code","y.cc":"code"})
    props=schema["$defs"]["_LineEdit"]["properties"]
    assert props["file"]["enum"]==["x.cpp","y.cc"]
    assert props["start_line"]["minimum"]==1 and props["end_line"]["minimum"]==1
    assert props["replacement_lines"]["maxItems"]==512
    assert props["replacement_lines"]["items"]["maxLength"]==12000
    assert schema["additionalProperties"] is False and schema["properties"]["edits"]["minItems"]==1


def test_plan_keeps_cost_limits_and_disables_thinking():
    request=plan()
    assert request.reservation_usd==pytest.approx(.066192)
    assert request.payload["chat_template_kwargs"]["enable_thinking"] is False
    assert request.payload["response_format"]["json_schema"]["name"]=="agentkernel_original_line_edits_v1"
    assert "candidate.c" not in json.dumps(request.payload)
    with pytest.raises(RepairRequestError): plan(max_cost_usd=.01)
    with pytest.raises(RepairRequestError): plan(max_input_tokens=100)


def test_valid_range_returns_candidate_with_billable_receipt():
    result=parse_line_response(response([edit()]),plan(),SOURCE)
    assert result.outcome=="candidate" and result.cost_usd==pytest.approx(.0104)
    assert result.tokens==300 and "+  lock();" in result.proposal.patch
    assert "fine-tuned" not in result.proposal.diagnosis and result.proposal.confidence==0
    assert result.text==response([edit()])["choices"][0]["message"]["content"]
    assert "search" in result.canonical_text and result.proposal is not None


@pytest.mark.parametrize("edits,code", [
    ([edit(4,2)],"line_range_reversed"),([edit(1,5)],"line_range_out_of_bounds"),
    ([edit(file="tests.c")],"line_file_not_allowed"),
    ([edit(2,3),edit(3,4)],"line_ranges_overlap"),
    ([edit(3,3,["  work();"])],"line_edit_no_change"),
])
def test_bad_ranges_reject_without_losing_paid_usage(edits,code):
    result=parse_line_response(response(edits),plan(),SOURCE)
    assert result.outcome=="invalid_output" and result.error_code==code
    assert result.usage_known and result.tokens==300 and result.may_escalate


@pytest.mark.parametrize("edits", [[],[edit(0,1)],[edit(True,3)],[edit(3,3,["work();\n"])],
                                   [edit(3,3,["work();\r"])],[edit(3,3,["x"]*513)],[edit(3,3,["x"*12001])]])
def test_schema_failures_are_explicit_invalid_outputs(edits):
    result=parse_line_response(response(edits),plan(),SOURCE)
    assert result.outcome=="invalid_output" and result.usage_known
    assert result.proposal is None


def test_repeated_original_lines_are_addressed_by_position_without_guessing():
    sources={"a.c":"same();\nsame();\n"}
    result=parse_line_response(response([edit(2,2,["changed();"],file="a.c")]),plan(sources),sources)
    assert result.outcome=="candidate"
    assert result.proposal.patch.count("-same();")==1 and "+changed();" in result.proposal.patch


def test_multiple_ranges_apply_in_reverse_against_original_positions():
    sources={"a.c":"one();\ntwo();\nthree();\nfour();\n"}
    result=parse_line_response(response([edit(1,1,["new();","one();"],file="a.c"),edit(4,4,[],file="a.c")]),plan(sources),sources)
    assert result.outcome=="candidate"
    parsed=json.loads(result.canonical_text)
    assert parsed["edits"][0]["replacement"]=="new();\none();\ntwo();\nthree();\n"


def test_edited_final_line_retains_original_missing_eof_newline():
    sources={"a.c":"one();\ntwo();"}
    result=parse_line_response(response([edit(2,2,["changed();"],file="a.c")]),plan(sources),sources)
    assert result.outcome=="candidate"
    assert json.loads(result.canonical_text)["edits"][0]["replacement"]=="one();\nchanged();"


def test_crlf_file_retains_crlf_in_edited_lines():
    sources={"a.c":"one();\r\ntwo();\r\n"}
    result=parse_line_response(response([edit(2,2,["changed();"],file="a.c")]),plan(sources),sources)
    assert result.outcome=="candidate"
    assert json.loads(result.canonical_text)["edits"][0]["replacement"]=="one();\r\nchanged();\r\n"


def test_c_backslash_escape_survives_json_line_decoding():
    sources={"a.c":'puts("before\\n");\n'}
    result=parse_line_response(response([edit(1,1,['puts("after\\n");'],file="a.c")]),plan(sources),sources)
    assert result.outcome=="candidate" and 'puts("after\\n");' in result.proposal.patch


def test_scheduling_hook_deletion_is_rejected():
    result=parse_line_response(response([edit(2,2,[])]),plan(),SOURCE)
    assert result.outcome=="invalid_output" and result.proposal is None and result.usage_known


def test_unknown_billable_usage_stops_without_escalation():
    result=parse_line_response(response([edit()],usage=None),plan(),SOURCE)
    assert result.outcome=="unknown" and not result.may_escalate and result.cost_usd is None


def test_truncation_preserves_charge_and_rejects_even_valid_looking_line_edits():
    data=response([edit()]);data["choices"][0]["finish_reason"]="length"
    result=parse_line_response(data,plan(),SOURCE)
    assert result.outcome=="invalid_output" and result.error_code=="output_budget_exhausted"
    assert result.proposal is None and result.usage_known


def test_refusal_is_not_reinterpreted_as_a_candidate():
    data=response([edit()]);data["choices"][0]["message"]["refusal"]="refused"
    result=parse_line_response(data,plan(),SOURCE)
    assert result.error_code=="model_refusal" and result.proposal is None


def test_duplicate_json_keys_are_not_silently_overwritten():
    data=response([edit()]);data["choices"][0]["message"]["content"]='{"edits":[],"edits":[]}'
    result=parse_line_response(data,plan(),SOURCE)
    assert result.outcome=="invalid_output" and result.error_code=="duplicate_json_key"


def test_unexpected_legacy_search_response_fails_without_crashing_receipt_parser():
    data=response([]);data["choices"][0]["message"]["content"]=json.dumps({"edits":[{
        "file":"worker.c","search":"  work();","replacement":"  lock();\n  work();\n  unlock();"}]})
    result=parse_line_response(data,plan(),SOURCE)
    assert result.outcome=="invalid_output" and result.usage_known and result.proposal is None


def test_original_source_beyond_512_lines_remains_addressable():
    sources={"a.c":"noop();\n"*570+"last();\n"}
    request=plan(sources)
    assert "000571|last();" in request.payload["messages"][-1]["content"]
    result=parse_line_response(response([edit(571,571,["changed();"],file="a.c")]),request,sources)
    assert result.outcome=="candidate"
