import json
from pathlib import Path
import pytest
from agentkernel.repository.specialist import to_proposal,active_root
from agentkernel.repository.adaptive import quote,route_quote,may_escalate


def test_specialist_cannot_edit_protected_or_extra_files():
    with pytest.raises(ValueError):
        to_proposal(json.dumps({'files':{'solution.c':'changed','oracle.c':'weakened'}}),{'solution.c':'old'})


def test_specialist_cannot_remove_scheduling_hooks():
    with pytest.raises(ValueError):
        to_proposal(json.dumps({'files':{'solution.c':'return;'}}),{'solution.c':'sched_yield();'})


def test_specialist_translates_exact_original_source_without_executing_it():
    proposal,text=to_proposal(json.dumps({'files':{'solution.c':'lock();\nsched_yield();\nunlock();\n'}}),{'solution.c':'sched_yield();\n'})
    assert '--- a/solution.c' in proposal.patch and 'lock();' in proposal.patch
    assert json.loads(text)['confidence']==.5


def test_malformed_or_fenced_specialist_responses_fail_closed():
    for response in ('```json\n{}\n```','null','{"files":{"solution.c":42}}'):
        with pytest.raises((ValueError,TypeError)):
            to_proposal(response,{'solution.c':'original'})


def test_unknown_or_infrastructure_outcomes_never_buy_another_model_call():
    assert may_escalate('rejected') and may_escalate('invalid_output')
    assert not may_escalate('unknown') and not may_escalate('infrastructure_failure')
    assert not may_escalate('verified')


def test_price_reservation_includes_full_allowed_input_output_and_request_charge():
    model={'id':'x','context_length':100000,'pricing':{'prompt':'.000001','completion':'.000002','request':'.01'}}
    assert quote(model)==pytest.approx(.048+2048*.000002+.01)
    with pytest.raises(ValueError):quote({**model,'pricing':{'prompt':'NaN','completion':'1'}})


def test_missing_configured_fallback_does_not_silently_substitute_a_model():
    with pytest.raises(ValueError):route_quote([])


def test_model_pointer_cannot_escape_the_project(tmp_path):
    (tmp_path/'models').mkdir()
    (tmp_path/'models/active-specialist.json').write_text('{"path":"../other-model"}')
    with pytest.raises(ValueError):active_root(tmp_path)



def test_raw_source_markers_preserve_c_quotes_and_scheduling_hooks():
    from agentkernel.repository.specialist import tagged_to_proposal
    proposal,_=tagged_to_proposal('<<<FILE:solution.c>>>\nlock();\nsched_yield();\nputs("PASS");\nunlock();\n<<<END_FILE>>>',{'solution.c':'sched_yield();\n'})
    assert 'puts("PASS");' in proposal.patch


@pytest.mark.parametrize('response',[
    'Explanation\n<<<FILE:solution.c>>>\nsched_yield(); changed();\n<<<END_FILE>>>',
    '<<<FILE:oracle.c>>>\nsched_yield(); changed();\n<<<END_FILE>>>',
    '<<<FILE:solution.c>>>\nsched_yield(); changed();\n<<<END_FILE>>>\n<<<FILE:solution.c>>>\nsched_yield(); changed();\n<<<END_FILE>>>',
    '<<<FILE:solution.c>>>\nchanged();\n<<<END_FILE>>>',
])
def test_marker_format_fails_closed_on_explanations_wrong_files_duplicates_and_removed_hooks(response):
    from agentkernel.repository.specialist import tagged_to_proposal
    with pytest.raises(ValueError):tagged_to_proposal(response,{'solution.c':'sched_yield();\n'})
