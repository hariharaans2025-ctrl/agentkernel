from agentkernel.repository.diagnostics import diagnose

def test_timeout_without_wait_evidence_is_not_deadlock():
    assert diagnose({'timed_out': True})['kind'] == 'timeout_unexplained'

def test_opposing_waits_support_deadlock_only_when_timed_out():
    r = {'stderr': 'WORKER HOLD queue WAIT stats\nMONITOR HOLD stats WAIT queue\n', 'timed_out': True}
    d = diagnose(r)
    assert d['kind'] == 'deadlock_supported_by_wait_cycle'
    assert d['cycles'] == [['MONITOR', 'WORKER']]
    assert diagnose({**r, 'timed_out': False, 'exit_code': 0})['kind'] == 'completed_not_verified'

def test_conflicting_owners_do_not_prove_cycle():
    r = {'stderr': 'A HOLD x WAIT y\nB HOLD y WAIT x\nC HOLD x WAIT z\n', 'timed_out': True}
    assert diagnose(r)['kind'] == 'timeout_unexplained'

def test_one_way_wait_does_not_prove_cycle():
    assert diagnose({'stderr': 'A HOLD x WAIT y\n', 'timed_out': True})['kind'] == 'timeout_unexplained'

def test_tsan_unavailable_is_infrastructure():
    assert diagnose({'stderr': 'FATAL: ThreadSanitizer: unexpected memory mapping', 'exit_code': 66})['kind'] == 'infrastructure_failure'

def test_race_fingerprint_ignores_runtime_addresses():
    a = {'stderr': 'WARNING: ThreadSanitizer: data race (pid=123)\n Write of size 4 at 0x123 by thread T1:\n worker race.c:12\n', 'exit_code': 66}
    b = {**a, 'stderr': a['stderr'].replace('0x123', '0x456').replace('pid=123', 'pid=456')}
    assert diagnose(a)['kind'] == 'data_race'
    assert diagnose(a)['fingerprint'] == diagnose(b)['fingerprint']

def test_nonzero_exit_alone_is_not_a_race():
    assert diagnose({'exit_code': 66})['kind'] == 'process_failure'

def test_transport_error_is_not_program_failure():
    assert diagnose({'metadata': {'error': 'OSError'}, 'exit_code': None})['kind'] == 'infrastructure_failure'
