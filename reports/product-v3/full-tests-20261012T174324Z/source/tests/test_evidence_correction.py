import copy
import json
import pytest
from agentkernel.repository.evidence_correction import require_race_failure,parse_correction


def evidence():
    return {'passed':False,'build_passed':True,'infrastructure_failures':0,'evidence':{'sanitizer':{'campaign':{
        'infrastructure_failures':0,'counts':{'RACE_DETECTED':3},'representative_runs':[
            {'classification':'RACE_DETECTED','stderr':'WARNING: ThreadSanitizer: data race'}]}}}}


def test_actual_race_qualifies():
    require_race_failure(evidence())


@pytest.mark.parametrize('change',['confidence_only','infrastructure','missing_raw','verified'])
def test_non_evidence_never_triggers(change):
    v=copy.deepcopy(evidence())
    if change=='confidence_only':v={'confidence':0.01}
    if change=='infrastructure':v['infrastructure_failures']=1
    if change=='missing_raw':v['evidence']['sanitizer']['campaign']['representative_runs']=[]
    if change=='verified':v['passed']=True
    with pytest.raises(ValueError):require_race_failure(v)


def test_exact_candidate_edit_and_protected_interface():
    response={'conflicting_accesses':[{'first_access':'write','second_access':'read','observed_evidence':'TSan race'}],
              'missing_synchronization':'shared lock','invariant_to_preserve':'preserve state',
              'edits':[{'file':'solution.c','search':'int a;\n','replacement':'int a=0;\n'}]}
    _,patch=parse_correction(json.dumps(response),{'solution.c':'int a;\n'})
    assert '+int a=0;' in patch
    response['edits'][0]['file']='oracle.c'
    with pytest.raises(ValueError):parse_correction(json.dumps(response),{'solution.c':'int a;\n'})
