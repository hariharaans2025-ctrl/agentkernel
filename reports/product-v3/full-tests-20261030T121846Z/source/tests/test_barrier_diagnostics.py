import json
import subprocess

from agentkernel.repository.barrier_diagnostics import analyze_barriers


def analyze(tmp_path, body):
    source = '#include <pthread.h>\npthread_mutex_t m; pthread_barrier_t b;\n' + body
    path = tmp_path / 'sample.c'
    path.write_text(source)
    parsed = subprocess.run(['clang', '-Xclang', '-ast-dump=json', '-fsyntax-only', str(path)],
                            capture_output=True, text=True, check=True)
    return analyze_barriers(json.loads(parsed.stdout), str(path), source)


def test_lock_at_barrier_has_locations_and_partner(tmp_path):
    r = analyze(tmp_path, 'void a(){pthread_mutex_lock(&m); pthread_barrier_wait(&b);}\n'
                'void z(){pthread_mutex_lock(&m); pthread_barrier_wait(&b);}')
    assert len(r['findings']) == 2
    assert r['findings'][0]['wait']['line'] == 3
    assert r['findings'][0]['possible_other_participant_acquisitions'][0]['function'] == 'z'


def test_release_before_barrier(tmp_path):
    r = analyze(tmp_path, 'void a(){pthread_mutex_lock(&m);pthread_mutex_unlock(&m);pthread_barrier_wait(&b);}')
    assert r['findings'] == []


def test_barrier_before_lock(tmp_path):
    assert not analyze(tmp_path, 'void a(){pthread_barrier_wait(&b);pthread_mutex_lock(&m);}')['findings']


def test_conditional_unlock_does_not_hide_risk(tmp_path):
    r = analyze(tmp_path, 'void a(int x){pthread_mutex_lock(&m);if(x)pthread_mutex_unlock(&m);pthread_barrier_wait(&b);}')
    assert len(r['findings']) == 1


def test_mutually_exclusive_branch_no_false_held_lock(tmp_path):
    r = analyze(tmp_path, 'void a(int x){if(x){pthread_mutex_lock(&m);}else{pthread_barrier_wait(&b);}}')
    assert not r['findings']


def test_comments_strings_are_not_calls(tmp_path):
    r = analyze(tmp_path, 'void a(){/* pthread_mutex_lock(&m); */ char *s="pthread_mutex_lock(&m)";pthread_barrier_wait(&b);}')
    assert not r['findings']


def test_unsupported_loop_is_explicit(tmp_path):
    assert analyze(tmp_path, 'void a(int x){while(x){pthread_mutex_lock(&m);}}')['coverage_gaps']


def test_indirect_object_is_explicit(tmp_path):
    assert analyze(tmp_path, 'void a(pthread_mutex_t *p){pthread_mutex_lock(p);pthread_barrier_wait(&b);}')['coverage_gaps']
