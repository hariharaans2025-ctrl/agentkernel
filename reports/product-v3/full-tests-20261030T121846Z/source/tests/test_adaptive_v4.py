import json
from pathlib import Path
import pytest

from agentkernel.repository import adaptive_v4_core as core
from agentkernel.repository.line_repair import _LineResponse, _candidate_files

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / 'reports/cloud-comparison/20261029T170003Z'
SRC = {'writer.c': '#include "state.h"\nvoid update(State*s){ s->n++; sched_yield(); }\n'}
ID = core.source_identity(SRC)


def saved(case, arm, stage):
    path = FROZEN / f'{case}--{arm}' / stage / 'result.json'
    if not path.exists(): pytest.skip('frozen evidence not present')
    return json.loads(path.read_text(encoding='utf-8'))


@pytest.mark.parametrize('case,arm', [('ledger_3', 'super_only'), ('predicate_3', 'super_only'), ('aggregate_3', 'fast')])
def test_saved_super_quote_closure_reproduced(case, arm):
    row = saved(case, arm, 'super')
    assert row['response'].endswith('"replacement_lines": ["#include "]}]}')
    assert core.classify_attempt(row) == {'primary': 'truncation', 'gates': ['invalid_line_repair_contract'], 'signature': 'string_closed_at_unescaped_quote'}


def test_saved_super_out_of_bounds_reproduced_by_v3_parser():
    row = saved('snapshot_3', 'super_only', 'super')
    sources = {n: (FROZEN / 'inputs/snapshot_3' / n).read_text(encoding='utf-8') for n in ('publisher.c', 'snapshot.c')}
    with pytest.raises(ValueError, match='line_range_out_of_bounds'):
        _candidate_files(_LineResponse.model_validate(json.loads(row['response'])), sources)
    assert core.classify_attempt(row)['primary'] == 'line_mapping'


def test_saved_rejected_candidates_categorized_by_gate():
    row = saved('audit_3', 'ultra_only', 'ultra')
    assert core.classify_attempt(row)['gates'] == ['original_tests', 'stress', 'tsan']
    row = saved('rendezvous_3', 'ultra_only', 'ultra')
    assert core.classify_attempt(row)['gates'] == ['original_tests', 'stress', 'semantics', 'tsan']


def test_block_contract_keeps_raw_quotes_and_line_endings():
    reply = '@@ REPLACE writer.c 2-2\nvoid update(State*s){ pthread_mutex_lock(&s->m); s->n++; sched_yield(); pthread_mutex_unlock(&s->m); }\n@@ END'
    files, notes = core.parse_blocks(reply, SRC, ID)
    assert files['writer.c'].startswith('#include "state.h"\n') and files['writer.c'].endswith('}\n')
    crlf = {'writer.c': SRC['writer.c'].replace('\n', '\r\n')}
    out, _ = core.parse_blocks(reply, crlf, core.source_identity(crlf))
    assert out['writer.c'].count('\r\n') == 2 and '\n' not in out['writer.c'].replace('\r\n', '')
    assert notes['blocks'] == [{'file': 'writer.c', 'start': 2, 'end': 2, 'replacement_lines': 1}]


@pytest.mark.parametrize('reply,code', [
    ('Here is the fix\n@@ REPLACE writer.c 2-2\nx; sched_yield();\n@@ END', 'text_outside_blocks'),
    ('@@ REPLACE writer.c 3-3\nx; sched_yield();\n@@ END', 'line_range_out_of_bounds'),
    ('@@ REPLACE writer.c 2-2\nx; sched_yield();', 'unterminated_block'),
    ('@@ REPLACE other.c 1-1\nx\n@@ END', 'file_not_editable'),
    ('@@ REPLACE writer.c 2-2\n000002|x; sched_yield();\n@@ END', 'line_prefix_copied'),
    ('@@ REPLACE writer.c 2-2\n#include "state.h"\nx; sched_yield();\n@@ END', 'ambiguous_neighbour_duplicated'),
    ('@@ REPLACE writer.c 1-2\na\n@@ END\n@@ REPLACE writer.c 2-2\nb\n@@ END', 'line_ranges_overlap'),
    ('@@ REPLACE writer.c 2-2\nvoid update(State*s){ s->n++; }\n@@ END', 'scheduling_hooks_changed'),
    ('@@ REPLACE writer.c 2-2\nvoid update(State*s){ s->n++; sched_yield(); }\n@@ END', 'no_change'),
])
def test_block_contract_rejects_ambiguous_or_invalid(reply, code):
    with pytest.raises(core.ContractError) as exc:
        core.parse_blocks(reply, SRC, ID)
    assert exc.value.code == code


def test_no_op_block_beside_a_real_fix_is_dropped_and_recorded():
    # Shape of the 30 Oct live capacity_3 Ultra reply: one real edit plus an unchanged file restated.
    src = {**SRC, 'reader.c': '#include "state.h"\nint read(State*s){ return s->n; }\n'}
    reply = ('@@ REPLACE writer.c 2-2\nvoid update(State*s){ pthread_mutex_lock(&s->m); s->n++; sched_yield(); pthread_mutex_unlock(&s->m); }\n@@ END\n'
             '@@ REPLACE reader.c 2-2\nint read(State*s){ return s->n; }\n@@ END')
    files, notes = core.parse_blocks(reply, src, core.source_identity(src))
    assert files['reader.c'] == src['reader.c'] and 'pthread_mutex_unlock' in files['writer.c']
    assert notes['no_op_blocks_dropped'] == [{'file': 'reader.c', 'start': 2, 'end': 2}]


def test_saved_live_capacity_3_reply_now_parses():
    run = ROOT / 'reports/adaptive-v4-live/20261030T120841Z/capacity_3'
    if not (run / '1-ultra/result.json').exists(): pytest.skip('live evidence not present')
    row = json.loads((run / '1-ultra/result.json').read_text(encoding='utf-8'))
    src = json.loads((run / '1-ultra/../started.json').read_text(encoding='utf-8'))['task']['source_files']
    sources = {n: (run / 'input' / n).read_bytes().decode('utf-8') for n in src}
    files, notes = core.parse_blocks(row['response'], sources, core.source_identity(sources))
    assert files['acquire.c'] != sources['acquire.c'] and notes['no_op_blocks_dropped'][0]['file'] == 'inspect.c'


def test_identity_is_exact_bytes_and_changes_are_rejected():
    with pytest.raises(core.ContractError, match='source_identity_changed'):
        core.parse_blocks('@@ REPLACE writer.c 2-2\nx; sched_yield();\n@@ END', {'writer.c': SRC['writer.c'] + ' '}, ID)


def test_whole_reply_fence_only_is_unwrapped():
    files, notes = core.parse_blocks('```\n@@ REPLACE writer.c 2-2\nv(); sched_yield();\n@@ END\n```', SRC, ID)
    assert notes['outer_fence_removed'] and 'v(); sched_yield();' in files['writer.c']


def test_messages_number_lines_and_never_include_references():
    msgs = core.v4_messages(SRC, {'state.h': 'typedef int State;'}, {'description': 'd'})
    assert '000001|#include "state.h"' in msgs[1]['content'] and 'reference' not in msgs[1]['content'].lower()
    assert 'response_format' not in json.dumps(msgs)


RACE = ('==9==WARNING: invalid path\nWARNING: ThreadSanitizer: data race (pid=9)\n  Write of size 4 at 0x55aa by thread T2:\n'
        '    #0 <null> (app+0xe657d) (BuildId: 11ac)\n  Previous read of size 4 at 0x55aa by thread T1:\n    #0 <null> (app+0xe6657)\n'
        'SUMMARY: ThreadSanitizer: data race')


def test_dedupe_is_lossless_and_keeps_reader_writer_conflict():
    runs = [{'run_id': f'r{i}', 'classification': 'RACE_DETECTED', 'exit_code': 66, 'timed_out': False, 'stdout': '',
             'stderr': RACE.replace('pid=9', f'pid={i}').replace('0x55aa', hex(4096 + i))} for i in range(3)]
    packet = core.dedupe_runs(runs)
    assert len(packet['records']) == 1
    for run in runs:
        ref = packet['runs'][run['run_id']]
        assert core.reconstruct(packet['records'][ref['fingerprint']]['stderr_template'], ref['stderr_values']) == run['stderr']
    conflict = next(iter(packet['records'].values()))['tsan_conflicts'][0]
    assert 'Write of size 4' in conflict and 'Previous read of size 4' in conflict


def test_evidence_packet_contains_required_fields_and_refuses_truncation():
    v = {'regressions': ['x'], 'evidence': {'build': {'success': True, 'exit_code': 0, 'stderr': ''},
         'original_tests': {'results': [{'exit_code': 1, 'timed_out': False, 'stdout': 'FAIL\n', 'stderr': ''}]},
         'campaign': {'counts': {'PASS': 99, 'UNKNOWN_FAILURE': 1}, 'total_runs': 100, 'representative_runs': []},
         'semantic': {'checks': [{'name': 'invariant', 'required': True, 'passed': False, 'run': {'stdout': 'FAIL'}}]},
         'sanitizer': {'status': 'failed', 'campaign': {'counts': {'RACE_DETECTED': 3}, 'representative_runs': [
             {'run_id': 't1', 'classification': 'RACE_DETECTED', 'exit_code': 66, 'timed_out': False, 'stdout': '', 'stderr': RACE}]}}}}
    p = core.evidence_packet(failed_files={'writer.c': 'x'}, patch='--- a', verification=v)
    assert p['stress']['fingerprint'] == 'UNKNOWN_FAILURE:1' and p['semantics'][0]['required'] and p['tsan']['failing_runs']['records']
    with pytest.raises(core.ContractError, match='evidence_budget_exceeded'):
        core.evidence_packet(failed_files={'writer.c': 'x' * 30000}, patch='', verification=v)


PRICES = {'super': {'expected_usd': 0.0005, 'expected_s': 32.0}, 'ultra': {'expected_usd': 0.0020, 'expected_s': 32.0}}
CTX = {'super': 262144, 'ultra': 1048576}


def feats(**kw):
    f = core.route_features({'a.c': 'void f(S*s){pthread_mutex_lock(&s->m);}'}, {'s.h': ''}, {'UNKNOWN_FAILURE': 3}, None)
    f.update(kw); return f


def test_router_uncalibrated_goes_ultra_direct_with_logged_reason():
    d = core.decide_route(feats(), {}, PRICES, input_bound_tokens=2000, contexts=CTX, output_caps={'super': 4096, 'ultra': 8192})
    assert d.stages == ['ultra'] and d.skip_reasons['super'] == 'protocol_capability_not_demonstrated' and d.policy == core.ROUTER_VERSION


def test_router_uses_super_first_only_when_calibrated_and_cheaper():
    cal = core.calibrate([{'bucket': 'single_lock_invariant', 'primary': 'verified'}] * 4)
    d = core.decide_route(feats(), cal, {**PRICES, 'super': {'expected_usd': 0.0005, 'expected_s': 20.0}}, input_bound_tokens=2000, contexts=CTX, output_caps={'super': 4096, 'ultra': 8192})
    assert d.stages == ['super', 'ultra'] and d.expected['p_super_lower'] == pytest.approx(4 / 6)
    weak = core.calibrate([{'bucket': 'single_lock_invariant', 'primary': 'tsan'}] * 4)
    assert core.decide_route(feats(), weak, PRICES, input_bound_tokens=2000, contexts=CTX, output_caps={'super': 4096, 'ultra': 8192}).stages == ['ultra']


def test_accepted_false_fix_is_counted_and_skips_super():
    rows = [{'bucket': 'single_lock_invariant', 'primary': 'verified'}] * 3 + [
        {'bucket': 'single_lock_invariant', 'primary': 'verified', 'accepted_false_fix': True}]
    cal = core.calibrate(rows)
    assert cal['super']['single_lock_invariant'] == {'n': 4, 'verified': 3, 'accepted_false_fix': 1}
    fast = {**PRICES, 'super': {'expected_usd': 0.0005, 'expected_s': 20.0}}
    d = core.decide_route(feats(), cal, fast, input_bound_tokens=2000, contexts=CTX, output_caps={'super': 4096, 'ultra': 8192})
    assert d.stages == ['ultra'] and d.skip_reasons['super'] == 'false_fix_history'


def test_calibration_counts_only_super_rows_for_buckets():
    cal = core.calibrate([{'bucket': 'multi_lock', 'primary': 'verified', 'stage': 'ultra'},
                          {'bucket': 'multi_lock', 'primary': 'tsan', 'stage': 'super'}])
    assert cal['super']['multi_lock'] == {'n': 1, 'verified': 0, 'accepted_false_fix': 0} and cal['super']['_protocol']['n'] == 1


def test_latency_uses_own_inference_plus_pooled_verification():
    rows = [{'stage': 'super', 'bucket': 'b', 'primary': 'line_mapping', 'inference_ms': 4000},   # rejected before execution
            {'stage': 'super', 'bucket': 'b', 'primary': 'tsan', 'inference_ms': 6000, 'verification_ms': 30000},
            {'stage': 'ultra', 'bucket': 'b', 'primary': 'verified', 'inference_ms': 20000, 'verification_ms': 34000}]
    lat = core.calibrate(rows)['latency']
    # Super is charged median verification (32 s) even though one reply never reached execution.
    assert lat['seconds'] == {'super': pytest.approx(37.0), 'ultra': pytest.approx(52.0)}
    assert lat['samples'] == {'verification': 2, 'super': 2, 'ultra': 1}
    assert core.calibrate([{'stage': 'super', 'bucket': 'b', 'primary': 'envelope', 'inference_ms': 1}])['latency']['seconds'] == {}


def test_v4_latency_source_is_explicit_then_measured_then_default():
    from agentkernel.repository import adaptive_v4
    options = {'super': {}, 'ultra': {}}
    measured = {'latency': {'seconds': {'super': 37.0, 'ultra': 52.0}}}
    k = adaptive_v4.AdaptiveV4('.', {}, ledger=object(), calibration=measured)
    assert k.latency_estimate(options) == ({'super': 37.0, 'ultra': 52.0}, 'development_phase_timings')
    k.latency_s = {'super': 1.0, 'ultra': 2.0}
    assert k.latency_estimate(options)[1] == 'explicit'
    partial = adaptive_v4.AdaptiveV4('.', {}, ledger=object(), calibration={'latency': {'seconds': {'super': 37.0}}})
    lat, source = partial.latency_estimate(options)
    assert source == 'default_equal_uncalibrated' and lat['super'] == lat['ultra'] == adaptive_v4.DEFAULT_LATENCY_S


def test_correction_stage_added_only_to_single_tier_routes():
    ultra = core.decide_route(feats(), {}, PRICES, input_bound_tokens=2000, contexts=CTX, output_caps={'super': 4096, 'ultra': 8192})
    d = core.with_correction(ultra)
    assert d.stages == ['ultra', 'ultra'] and d.expected['correction_stage'] == 'ultra'
    ladder = core.RouteDecision(core.ROUTER_VERSION, ['super', 'ultra'], {}, 'b')
    assert core.with_correction(ladder).stages == ['super', 'ultra'] and 'correction_stage' not in ladder.expected
    assert core.with_correction(core.RouteDecision(core.ROUTER_VERSION, [], {}, 'b')).stages == []


def test_router_context_capacity_and_blocking_helper_bucket():
    d = core.decide_route(feats(), {}, PRICES, input_bound_tokens=300000, contexts=CTX, output_caps={'super': 4096, 'ultra': 8192})
    assert d.skip_reasons['super'] == 'context_capacity' and d.stages == ['ultra']
    f = core.route_features({'p.c': 'x'}, {'s.h': 'static inline void c(S*s){pthread_barrier_wait(&s->g);}'}, {'TIMEOUT': 3}, None)
    assert core.bucket_of(f) == 'protected_blocking_helper'


def test_v4_route_is_opt_in_and_v3_unchanged():
    from agentkernel.repository import adaptive_v3, adaptive_v4
    assert adaptive_v3.FAST_ID == 'agentkernel/adaptive-v3-fast' and adaptive_v4.ROUTE_ID == 'agentkernel/adaptive-v4'
    assert 'response_format' not in adaptive_v4.plan_v4({'id': 'm', 'context_length': 100000, 'pricing': {'prompt': '0', 'completion': '0'}},
        core.v4_messages(SRC, {}, {}), SRC, max_cost_usd=1, max_input_tokens=12000, max_output_tokens=4096, max_total_tokens=36288).payload
