import pytest
from agentkernel.repository.context import group_runs, expand_runs, select_sources, index_functions

def test_grouping_retains_distinct_failures_and_every_run_field():
    runs = [dict(run_id=str(i), stdout='a' if i < 2 else 'b', stderr='', timed_out=True,
                 exit_code=-9, classification='TIMEOUT', duration_ms=i+1, metadata={'seed': i}) for i in range(3)]
    groups = group_runs(runs)
    assert len(groups) == 2
    assert sorted(expand_runs(groups), key=lambda x: x['run_id']) == runs

def test_retrieval_includes_callers_function_pointers_and_headers():
    index = [{'name':'lock', 'file':'lock.c', 'references':[]},
             {'name':'worker', 'file':'worker.c', 'references':['lock']},
             {'name':'main', 'file':'main.c', 'references':['worker', 'init']},
             {'name':'init', 'file':'init.c', 'references':[]}]
    sources = {n:'/* exact source */' for n in ['lock.c','worker.c','main.c','init.c','types.h','README.md']}
    selected, names = select_sources(sources, index, ['lock'], ['lock.c'])
    assert set(selected) == set(sources) - {'README.md'}
    assert names == ['init','lock','main','worker']

def test_unknown_seed_fails_instead_of_empty_context():
    with pytest.raises(ValueError): select_sources({'a.c':'x'}, [], ['missing'], ['a.c'])

def test_missing_header_stops_retrieval():
    with pytest.raises(ValueError): select_sources({'a.c':'#include "secret.h"'},
        [{'name':'f','file':'a.c','references':[]}], ['f'], ['a.c'])

def test_index_does_not_include_system_header_definitions():
    ast = {'kind':'FunctionDecl','name':'hidden','loc':{'includedFrom':{'file':'x.h'}}, 'inner':[{'kind':'CompoundStmt'}]}
    assert index_functions(ast, 'a.c', 'a') == []

def test_invalid_clang_offsets_fail_closed():
    ast = {'kind':'FunctionDecl','name':'f','loc':{},'range':{'begin':{'offset':0},'end':{'offset':100}}, 'inner':[{'kind':'CompoundStmt'}]}
    with pytest.raises(ValueError): index_functions(ast, 'a.c', 'a')
