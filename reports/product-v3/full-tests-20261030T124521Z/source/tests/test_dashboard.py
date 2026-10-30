import asyncio
import json
import threading
import uuid

import httpx
import pytest

from agentkernel.concurrency.app import ConcurrencyJobResult
from agentkernel.dashboard.server import make_server
from agentkernel.dashboard.service import BusyError, DashboardService


@pytest.fixture
def root(tmp_path, monkeypatch):
    fixture = tmp_path/'benchmarks/deadlock_001'
    fixture.mkdir(parents=True)
    (fixture/'main.c').write_text('original')
    (fixture/'task.json').write_text(json.dumps({'task_id':'deadlock_001','source_files':['main.c'],
        'build_command':['gcc','main.c','-o','app'],'run_command':['./app'],
        'verification_config':{'stress_runs':100}}))
    monkeypatch.setenv('NEBIUS_API_KEY', 'secret-dashboard-test-key')
    monkeypatch.setenv('NEBIUS_PROJECT_ID', 'test-project')
    return tmp_path


def request(tiers=None):
    return {'fixture':'deadlock_001','tiers':tiers or ['NANO','SUPER'],'client_id':str(uuid.uuid4())}


def test_real_job_wiring_frozen_source_budget_history(root):
    seen = []
    async def runner(task,tier,provider):
        seen.append((tier,task.workspace,task.verification_config.stress_runs,provider.max_retries))
        assert (task.workspace/'main.c').read_text() == 'original'
        (root/'benchmarks/deadlock_001/main.c').write_text('modified after start')
        return ConcurrencyJobResult(task=task.task_id,status='unresolved',inference_mode='real')
    service=DashboardService(root,job_runner=runner)
    body=request()
    run=service.start(body)
    service.worker.join(5)
    assert not service.worker.is_alive()
    assert [x[0] for x in seen] == ['NANO','SUPER']
    assert all(x[1] != root/'benchmarks/deadlock_001' and x[2:] == (100,0) for x in seen)
    assert service.get(run['id'])['status']=='completed'
    service.start(body)
    assert len(seen)==2  # Idempotent: never replay paid work.
    assert DashboardService(root).get(run['id'])['status']=='completed'
    assert 'secret-dashboard-test-key' not in json.dumps(service.configuration())


def test_stop_after_current_model_and_busy_guard(root):
    entered, release=threading.Event(),threading.Event()
    seen=[]
    async def runner(task,tier,provider):
        seen.append(tier)
        entered.set()
        await asyncio.to_thread(release.wait,3)
        return ConcurrencyJobResult(task=task.task_id)
    s=DashboardService(root,job_runner=runner)
    first=s.start(request())
    assert entered.wait(3)
    with pytest.raises(BusyError): s.start(request())
    s.stop(first['id'])
    release.set();s.worker.join(5)
    assert seen==['NANO']
    assert s.get(first['id'])['results']['SUPER']['status']=='skipped'


@pytest.mark.parametrize('override',[{'fixture':'../.env'},{'tiers':['OTHER']},{'tiers':['SUPER','SUPER']},
    {'client_id':'../../escape'},{'tiers':[]},{'command':['whoami']}])
def test_invalid_requests_never_start(root,override):
    s=DashboardService(root)
    with pytest.raises(ValueError): s.start({**request(),**override})
    assert s.worker is None


def v4_case(root):
    data = root/'datasets/adaptive-v3/product-v1'
    (data/'tasks/audit_3').mkdir(parents=True)
    (data/'tasks/audit_3/commit.c').write_text('original')
    (data/'tasks/audit_3/task.json').write_text(json.dumps({'task_id':'audit_3','source_files':['commit.c'],
        'build_command':['gcc','commit.c','-o','app'],'run_command':['./app'],'verification_config':{'stress_runs':100}}))
    (data/'manifest.json').write_text(json.dumps({'cases':[{'id':'audit_3','split':'test'},{'id':'audit_1','split':'train'}]}))


@pytest.mark.parametrize('fixture,tiers', [('deadlock_001',['ADAPTIVE_V4']), ('audit_3',['NANO']), ('audit_3',['ADAPTIVE_V4','ULTRA'])])
def test_v4_only_runs_alone_on_complete_contract_cases(root, fixture, tiers):
    v4_case(root)
    s = DashboardService(root)
    assert {f['id']: f['v4'] for f in s.configuration()['fixtures']} == {'deadlock_001': False, 'audit_3': True}
    with pytest.raises(ValueError, match='Adaptive v4'):
        s.start({'fixture':fixture,'tiers':tiers,'client_id':str(uuid.uuid4())})
    assert s.worker is None


def test_v4_result_maps_onto_dashboard_job_without_inventing_values(root, monkeypatch):
    v4_case(root)
    from agentkernel.dashboard import service as module
    catalog = [{'id':'nvidia/nemotron-3-super-120b-a12b','context_length':262144,'pricing':{'prompt':'0.0000003','completion':'0.0000009'}},
               {'id':'nvidia/Nemotron-3-Ultra-550b-a55b','context_length':1048576,'pricing':{'prompt':'0.000001','completion':'0.000003'}}]
    async def fake_catalog(): return catalog
    seen = {}
    class FakeV4:
        def __init__(self, root, rows, on_progress): self.progress = on_progress
        async def run(self, task, folder, *, arm, max_cost_usd):
            seen.update(arm=arm, cap=max_cost_usd, source=(task.workspace/'commit.c').read_text()); self.progress({'stage':'Call 1: ultra'})
            summary = {'build_passed':True,'original_tests_passed':True,'passed_runs':100,'total_runs':100,'semantic_passed':True,'tsan_passed':True,'scheduling_hooks_preserved':True}
            first = {**summary, 'passed_runs':92, 'tsan_passed':False}
            return {'status':'verified','cost_usd':0.0079,'model_calls':2,'verification':summary,'recoveries':{'format':0,'verifier':1},
                    'attempts':[{'stage':'ultra','outcome':'rejected','model_calls':1,'patch':'--- a','input_tokens':900,'output_tokens':300,'tokens':1200,'inference_ms':5000,'response':'@@ A','verification':first,'false_fix':True},
                                {'stage':'ultra','outcome':'verified','recovery':'verifier','model_calls':1,'patch':'--- b','input_tokens':5000,'output_tokens':1200,'tokens':6200,'inference_ms':9000,'response':'@@ B','verification':summary}]}
    monkeypatch.setattr(module, 'live_catalog', fake_catalog); monkeypatch.setattr(module, 'AdaptiveV4', FakeV4)
    s = DashboardService(root)
    run = s.start({'fixture':'audit_3','tiers':['ADAPTIVE_V4'],'client_id':str(uuid.uuid4())})
    s.worker.join(5)
    item = s.get(run['id'])['results']['ADAPTIVE_V4']
    assert seen == {'arm':'v4','cap':round(2*(0.000001*36000+0.000003*8192),6),'source':'original'}
    assert module.os.environ['AGENTKERNEL_SANDBOX_IMAGE'] == 'agentkernel-clang:20261003122908'  # TSan-capable image
    assert item['status']=='completed' and item['job']['status']=='verified' and item['response']=='@@ B'
    assert item['job']['route'] == ['ULTRA', 'ULTRA (evidence correction)'] and item['job']['model_calls']['ULTRA'] == 2
    metrics = s.get(run['id'])['benchmark']['individual']['ADAPTIVE_V4']
    assert (metrics['input_tokens'], metrics['output_tokens'], metrics['verification_passes'], metrics['sanitizer_passed']) == (5900, 1500, 100, True)
    assert metrics['false_fix'] is True  # the rejected first candidate stays visible


def test_restart_marks_interrupted_without_rerunning(root):
    s=DashboardService(root)
    ident=str(uuid.uuid4())
    s._save({'id':ident,'status':'running','results':{'SUPER':{'status':'running'}},'created_at':'2026-01-01'})
    restored=DashboardService(root)
    assert restored.get(ident)['status']=='interrupted'
    assert restored.worker is None


def test_loopback_http_csrf_static_and_no_secrets(root):
    s=DashboardService(root)
    server=make_server(s,0)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}',trust_env=False) as client:
            config=client.get('/api/config')
            assert config.status_code==200
            assert 'secret-dashboard-test-key' not in config.text
            assert client.get('/').status_code==200
            assert client.get('/api/benchmark').json()=={'status':'not_run','rows':[]}
            assert config.json()['api_version']==2
            assert 'ADAPTIVE' in config.json()['models']
            assert client.get('/app.js').headers['content-type'].startswith('text/javascript')
            assert client.get('/../.env').status_code==404
            assert client.get('/api/config',headers={'Host':'evil.example'}).status_code==403
            assert client.post('/api/runs',json=request()).status_code==403
            assert client.post('/api/runs',json=request(),headers={'X-CSRF-Token':config.json()['csrf'],
                'Origin':'https://evil.example'}).status_code==403
            assert client.post('/api/runs',json={'bad':1},headers={'X-CSRF-Token':config.json()['csrf']}).status_code==400
    finally:
        server.shutdown();server.server_close();worker.join(3)
