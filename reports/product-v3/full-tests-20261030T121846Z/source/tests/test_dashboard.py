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
