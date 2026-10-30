import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.repository import candidate_reuse as reuse


def fixture(tmp_path):
    sample=Path(__file__).parent/'fixtures/sites-seed'
    task=json.loads((sample/'task.json').read_text())
    workspace=tmp_path/'source';workspace.mkdir()
    for path in (sample/'pair_snapshot').iterdir():
        (workspace/path.name).write_bytes(path.read_bytes())
    return ConcurrencyTask.model_validate({**task,'task_id':'cache-fixture','workspace':workspace})


def verified(task):
    return {'passed':True,'build_passed':True,'total_runs':100,'passed_runs':100,'failed_runs':0,
            'infrastructure_failures':0,'regressions':[],'semantic_passed':True,'false_fix':False,
            'sanitizer_passed':True,'evidence':{'original_tests':{'passed':True},
                'sanitizer':{'campaign':{'total_runs':3,'counts':{'PASS':3}}}}}


def test_identity_invalidates_for_source_protected_file_policy_and_config(tmp_path):
    task=fixture(tmp_path);cache=reuse.VerifiedCandidateCache(tmp_path/'cache')
    key,_=cache.identity(task,{'version':1})
    assert cache.identity(task,{'version':2})[0]!=key
    changed=task.model_copy(update={'environment':{'MODE':'other'}})
    assert cache.identity(changed,{'version':1})[0]!=key
    for name in (task.source_files[0],task.support_files[0]):
        p=task.workspace/name;old=p.read_bytes();p.write_bytes(old+b'\n')
        assert cache.identity(task,{'version':1})[0]!=key
        p.write_bytes(old)
    assert cache.identity(task,{'version':1})[0]==key


def test_only_fully_verified_entries_are_admitted(tmp_path):
    task=fixture(tmp_path);cache=reuse.VerifiedCandidateCache(tmp_path/'cache')
    key,identity=cache.identity(task,{})
    for field,value in [('passed',False),('passed_runs',99),('sanitizer_passed',False)]:
        data=verified(task);data[field]=value
        with pytest.raises(ValueError):cache.admit(key,identity,'patch',data,'old-run')
    data=verified(task);data['evidence']['original_tests']['passed']=False
    with pytest.raises(ValueError):cache.admit(key,identity,'patch',data,'old-run')


def test_ttl_and_tampered_patch_are_misses(tmp_path):
    now=[1000];task=fixture(tmp_path);cache=reuse.VerifiedCandidateCache(tmp_path/'cache',ttl_seconds=10,clock=lambda:now[0])
    key,identity=cache.identity(task,{})
    cache.admit(key,identity,'patch',verified(task),'old-run')
    assert cache.lookup(key,identity)
    now[0]+=11;assert cache.lookup(key,identity) is None
    now[0]=1000
    path=cache.root/(key+'.json');data=json.loads(path.read_text());data['patch']='tampered'
    path.write_text(json.dumps(data));assert cache.lookup(key,identity) is None


def test_weak_verification_is_rejected_before_cache_access(tmp_path):
    task=fixture(tmp_path)
    task.verification_config.stress_runs=10
    with pytest.raises(ValueError):reuse.VerifiedCandidateCache(tmp_path/'cache').identity(task,{})


@pytest.mark.parametrize('passed,infrastructure,expected',[(True,0,'verified'),(False,0,'rejected'),(False,1,'unknown')])
def test_cache_hit_runs_fresh_full_verifier_without_model(tmp_path,monkeypatch,passed,infrastructure,expected):
    task=fixture(tmp_path);cache=reuse.VerifiedCandidateCache(tmp_path/'cache')
    key,identity=cache.identity(task,{})
    cache.admit(key,identity,'canonical patch',verified(task),'old-run')
    calls=[]
    class Box:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def upload_project(self,root,files):self.root=root
        async def apply_patch(self,patch,allowed):return SimpleNamespace(success=True)
        async def read_file(self,name):return (self.root/name).read_bytes().decode()
    class Verifier:
        def __init__(self,**kwargs):pass
        async def verify_workspace(self,t,box):
            calls.append((t.verification_config.stress_runs,t.verification_config.sanitizer_runs))
            raw=verified(t);raw.update(passed=passed,infrastructure_failures=infrastructure)
            return SimpleNamespace(passed=passed,infrastructure_failures=infrastructure,build_passed=True,
                passed_runs=100,total_runs=100,semantic_passed=True,sanitizer_passed=True,duration_ms=20,
                model_dump=lambda **kwargs:raw)
    monkeypatch.setattr(reuse,'NebiusSandboxBackend',Box)
    monkeypatch.setattr(reuse,'ConcurrencyVerifier',Verifier)
    async def forbidden(*args):raise AssertionError('No model route may execute on a cache hit')
    result=asyncio.run(reuse.run_with_candidate_reuse(task,tmp_path/'run',cache=cache,policy={},
        run_fresh=forbidden,campaign_factory=lambda path:None))
    assert calls==[(100,3)]
    assert result['status']==expected and result['model_calls']==0 and result['tokens']==0
    assert result['candidate_reuse']['verdict_reused'] is False


def test_cache_miss_runs_the_original_route_once(tmp_path):
    task=fixture(tmp_path);called=[]
    async def fresh(t,out):
        called.append(t);out.mkdir();return {'status':'rejected','model_calls':1}
    result=asyncio.run(reuse.run_with_candidate_reuse(task,tmp_path/'run',cache=reuse.VerifiedCandidateCache(tmp_path/'cache'),
        policy={},run_fresh=fresh,campaign_factory=lambda path:None))
    assert len(called)==1 and result['candidate_reuse']['hit'] is False
