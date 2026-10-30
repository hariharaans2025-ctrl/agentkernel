import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

from agentkernel.concurrency.app import ConcurrencyBugHunter, ConcurrencyPolicy, ConcurrencyJobResult
from agentkernel.concurrency.models import ConcurrencyTask, VerificationConfig, SemanticCheck
from agentkernel.concurrency.mock_inference import mock_concurrency_response
from agentkernel.concurrency.verification.semantics import check_semantics
from agentkernel.concurrency.sandbox.base import CommandResult
from agentkernel.concurrency.instrumentation.sanitizer import parse_sanitizer, runtime_unavailable
from agentkernel.concurrency.benchmark.metrics import false_fix, summarize
from agentkernel.concurrency.benchmark.report import job_data, write_reports
from agentkernel.concurrency.benchmark.loader import discover_tasks, load_task
from agentkernel.concurrency.final_benchmark import execution_plan
from agentkernel.concurrency.human_review import review_package, ReviewScores, PendingTolokaAdapter
from agentkernel.knowledge import ConditionalGrounding, TavilyKnowledgeTool
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.observability.noop import NoOpObserver


def task_at(root):
    (root/'main.c').write_text("print('FAIL')\n")
    return ConcurrencyTask(task_id='semantic-demo',workspace=root,source_files=['main.c'],
        build_command=[sys.executable,'-c','pass'],run_command=[sys.executable,'main.c'],stress_runs=1,
        verification_config=VerificationConfig(stress_runs=2,semantic_checks=[SemanticCheck(name='retained work',
            build_command=[sys.executable,'-c','pass'],run_command=[sys.executable,'-c',
                "from pathlib import Path; print('SEMANTIC_PASS' if '# fixed' in Path('main.c').read_text() else 'SEMANTIC_FAIL')"])]))


@pytest.mark.parametrize('super_success',[False,True])
def test_adaptive_semantics_escalation_context_and_success_gate(tmp_path, super_success):
    seen=[]
    def response(request, route):
        seen.append((request,route.selected_tier.value))
        if request.metadata['phase']=='triage': return mock_concurrency_response(request,route)
        source=request.metadata['concurrency_context']['sources']['main.c']
        replacement="print('PASS') # fixed\n" if route.selected_tier.value=='ULTRA' or super_success else "print('PASS') # broken\n"
        return json.dumps({'diagnosis':'repair','root_cause':'test','confidence':0.8,'edits':[{'file':'main.c','search':source,'replacement':replacement}],
                          'reasoning_summary':'test','expected_effect':'retain work','risk_notes':[]})
    job=asyncio.run(ConcurrencyBugHunter(MockNebiusProvider(response)).run(task_at(tmp_path)))
    assert job.status=='verified'
    assert job.route==(['NANO','SUPER'] if super_success else ['NANO','SUPER','ULTRA'])
    assert all(j.metadata['max_output_tokens']==(768 if j.metadata['phase']=='triage' else 2048) for j,_ in seen)
    assert job.verification['execution_passed'] and job.verification['semantic_passed']
    assert job.verification['sanitizer_passed'] is None
    assert job.verification['race_count'] is None
    if not super_success:
        assert job.repairs[0]['false_fix']
        assert job.repairs[0]['verification']['semantic_regression']
        stronger=seen[-1][0]
        for required in ['original_task','sources','fingerprints','nano_summary']:
            assert required in stronger.metadata['concurrency_context']
        evidence=stronger.metadata['failure_evidence']['verification_evidence']
        assert '# broken' in evidence['candidate_sources']['main.c']
        assert evidence['patch_application']['success']
        assert evidence['verification']['evidence']['build']['exit_code']==0
        assert not evidence['verification']['semantic_passed']
        assert summarize([job])['false_fixes']==1
    assert (tmp_path/'main.c').read_text()=="print('FAIL')\n"
    data=job_data(job,'adaptive')
    assert data['semantic_passed'] is True and data['races'] is None
    assert data['route']==job.route and data['source_sha256']


def test_invalid_repair_does_not_spend_ultra(tmp_path):
    def response(request,route):
        return mock_concurrency_response(request,route) if request.metadata['phase']=='triage' else 'invalid'
    result=asyncio.run(ConcurrencyBugHunter(MockNebiusProvider(response)).run(task_at(tmp_path)))
    assert result.route==['NANO','SUPER']
    assert not result.repairs


@pytest.mark.parametrize('passed,infrastructure',[(True,False),(False,False),(False,True)])
def test_semantic_pass_fail_and_infrastructure(tmp_path,passed,infrastructure):
    task=task_at(tmp_path)
    class Box:
        calls=0
        async def run_command(self,command,**kw):
            self.calls+=1
            return CommandResult(command=command,exit_code=0 if not infrastructure else None,
                stdout='SEMANTIC_PASS' if passed else 'SEMANTIC_FAIL',stderr='',duration_ms=1,
                metadata={'error':'remote_transport'} if infrastructure else {})
    result=asyncio.run(check_semantics(task,Box()))
    assert result['required_passed']==passed
    assert result['regression']==(not passed and not infrastructure)
    assert bool(result['infrastructure_failures'])==infrastructure


@pytest.mark.parametrize('patch,verification,expected',[
    (False,{'passed':False},False),
    (True,{'passed':False,'build_passed':False},True),
    (True,{'passed':False,'semantic_regression':True},True),
    (True,{'passed':False,'infrastructure_failures':1},False),
    (True,{'passed':False,'evidence':{'execution_blocked':True}},False),
    (True,{'passed':True},False)])
def test_false_fix_definition(patch,verification,expected):
    assert false_fix({'patch':{'success':patch},'verification':verification}) is expected


def test_tsan_race_and_environment_failure_are_distinct():
    findings=parse_sanitizer('WARNING: ThreadSanitizer: data race\n Write of size 4 at 0x1234 by thread T1:\n f main.c:12\n Previous read by thread T2:\n g main.c:13')
    assert findings[0].type=='data_race' and findings[0].file=='main.c' and findings[0].line==12
    assert runtime_unavailable('FATAL: ThreadSanitizer: unexpected memory mapping 0x1234')
    assert not runtime_unavailable('WARNING: ThreadSanitizer: data race')


def test_grounding_only_explicit_reason_and_one_call(monkeypatch):
    calls=[]
    class Search:
        async def search_documentation(self,query): calls.append(query); return [{'title':'docs','content':'untrusted'}]
    async def run():
        g=ConditionalGrounding(Search(),enabled=True)
        assert not (await g.lookup(None))['used']
        assert not (await g.lookup('ordinary_deadlock'))['used']
        assert (await g.lookup('toolchain_issue'))['used']
        assert (await g.lookup('unknown_compiler_error'))['status']=='budget_exhausted'
        assert (await ConditionalGrounding(Search(),enabled=False).lookup('unfamiliar_api'))['status']=='disabled'
    asyncio.run(run()); assert len(calls)==1


def test_tavily_http_is_bounded_and_excludes_source(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','test-key')
    def handler(request):
        payload=json.loads(request.content)
        assert payload['max_results']==3 and payload['search_depth']=='basic'
        assert not payload['include_raw_content']
        return httpx.Response(200,json={'results':[{'title':'docs','url':'https://clang.llvm.org/docs/ThreadSanitizer.html','content':'safe'}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ConditionalGrounding(TavilyKnowledgeTool(client),enabled=True).lookup('unknown_sanitizer_behavior')
    assert asyncio.run(run())['status']=='retrieved'


def test_observer_errors_never_abort_job(tmp_path):
    class Broken(NoOpObserver):
        async def start_span(self,*args,**kw): raise OSError('trace transport')
        async def end_span(self,*args,**kw): raise OSError('trace transport')
        async def record_feedback(self,*args,**kw): raise OSError('trace transport')
        async def flush(self): raise OSError('trace transport')
    job=asyncio.run(ConcurrencyBugHunter(MockNebiusProvider(lambda task,route:'bad'),observer=Broken()).run(task_at(tmp_path)))
    assert job.status=='unresolved'
    assert job.metadata['observability']['status']=='unavailable'


def test_plan_outputs_and_human_review_gate(tmp_path):
    tasks=[load_task(p) for p in discover_tasks(Path(__file__).parents[1]/'benchmarks')]
    plan=execution_plan(tasks)
    assert plan['paid_calls_max']==60 and plan['verification_stress_executions_max']==5000
    assert plan['semantic_executions_max']==50 and plan['sanitizer_verification_executions_max']==75
    assert len(plan['required_tsan'])==5
    assert plan['max_output_tokens']==110080
    report={'status':'not_run','rows':[],'aggregate':summarize([]),'plan':plan}
    write_reports(tmp_path,report)
    assert len(list(tmp_path.glob('final-benchmark.*')))==3
    assert json.loads((tmp_path/'final-benchmark.json').read_text())['aggregate']['cost_usd'] is None
    with pytest.raises(ValueError): review_package(ConcurrencyJobResult(task='x'))
    package=review_package(ConcurrencyJobResult(task='x',status='verified',verification={'passed':True}))
    assert asyncio.run(PendingTolokaAdapter().submit(package))['submitted'] is False
    with pytest.raises(ValueError): ReviewScores(readability=6,unnecessary_serialization=1,concurrency_preservation=1,maintainability=1,diagnosis_clarity=1)


def test_report_redacts_secrets_and_preserves_unknowns(tmp_path,monkeypatch):
    monkeypatch.setenv('NEBIUS_API_KEY','private-example-secret')
    row={'fixture':'x','mode':'adaptive','status':'unresolved','final_tier':None,'input_tokens':None,
         'note':'private-example-secret','authorization':'Bearer private-example-secret'}
    write_reports(tmp_path,{'status':'completed','rows':[row],'aggregate':summarize([]),'plan':{}})
    text=(tmp_path/'final-benchmark.json').read_text()
    assert 'private-example-secret' not in text
    assert json.loads(text)['rows'][0]['input_tokens'] is None


def test_all_trusted_oracles_compile_inside_remote_test_host():
    if os.getenv('AK_REMOTE_TEST_HOST')!='1': pytest.skip('Native fixture checks are remote-only')
    from agentkernel.concurrency.sandbox.local import LocalSandboxBackend
    async def run():
        for folder in discover_tasks(Path(__file__).parents[1]/'benchmarks'):
            task=load_task(folder)
            assert 'oracle.c' not in task.source_files and 'oracle.c' in task.support_files
            async with LocalSandboxBackend() as box:
                await box.upload_project(task.workspace,task.source_files+task.support_files)
                result=await box.run_command(task.verification_config.semantic_checks[0].build_command,timeout=20)
                assert result.exit_code==0, (task.task_id,result.stderr)
    asyncio.run(run())


@pytest.mark.parametrize('name',['race_001','race_002','race_003','race_004','race_005'])
def test_clang_tsan_detects_original_race_and_accepts_known_repair(name):
    if os.getenv('AK_REMOTE_TEST_HOST')!='1': pytest.skip('TSan probes are remote-only')
    import shutil
    if not shutil.which('clang'): pytest.skip('Use prepared Clang sandbox image for these probes')
    from agentkernel.concurrency.sandbox.local import LocalSandboxBackend
    from agentkernel.concurrency.compile.compiler import CCompiler
    from agentkernel.concurrency.instrumentation.sanitizer import instrumented_task, SanitizerConfig
    async def run():
        task=load_task(Path(__file__).parents[1]/'benchmarks'/name)
        async with LocalSandboxBackend() as box:
            await box.upload_project(task.workspace,task.source_files+task.support_files)
            instrumented=instrumented_task(task)
            original=(task.workspace/'main.c').read_text()
            for repaired in (False,True):
                (box.workspace/'main.c').write_text(fixed_fixture(name,original) if repaired else original)
                build=await CCompiler().compile(instrumented,box,SanitizerConfig().flags)
                assert build.success, build.stderr
                result=await box.run_command(task.run_command,timeout=10,environment=instrumented.environment)
                assert not runtime_unavailable(result.stderr), result.stderr
                if repaired:
                    assert result.exit_code==0 and not result.timed_out, result.stderr
                    assert not parse_sanitizer(result.stderr)
                else:
                    assert any(f.type=='data_race' for f in parse_sanitizer(result.stderr)), (name,result.model_dump())
    asyncio.run(run())


def fixed_fixture(name, source):
    if name == 'deadlock_001':
        return source.replace('pthread_mutex_t *first = id == 1 ? &a : &b;', 'pthread_mutex_t *first = &a;').replace('pthread_mutex_t *second = id == 1 ? &b : &a;', 'pthread_mutex_t *second = &b;').replace('    pthread_barrier_wait(&ready);\n','').replace('    pthread_mutex_lock(first);','    pthread_barrier_wait(&ready);\n    pthread_mutex_lock(first);')
    if name == 'deadlock_002':
        return source.replace('    pthread_barrier_wait(&ready);\n','').replace('    pthread_mutex_lock(&locks[from]);','    pthread_barrier_wait(&ready);\n    pthread_mutex_lock(&locks[0]);').replace('pthread_mutex_lock(&locks[to]);','pthread_mutex_lock(&locks[1]);').replace('pthread_mutex_unlock(&locks[to]); pthread_mutex_unlock(&locks[from]);','pthread_mutex_unlock(&locks[1]); pthread_mutex_unlock(&locks[0]);')
    if name == 'deadlock_003':
        return source.replace('pthread_barrier_wait(&ready); pthread_mutex_lock(&state);','pthread_mutex_unlock(&delivery); pthread_barrier_wait(&ready); pthread_mutex_lock(&state);').replace('received=value; consumed++; pthread_mutex_unlock(&state);\n    pthread_mutex_unlock(&delivery);','received=value; consumed++; pthread_mutex_unlock(&state);')
    if name == 'deadlock_004':
        return source.replace('pthread_barrier_wait(&ready); puts(', 'puts(').replace('(void)unused; pthread_mutex_lock(&cache_lock);','(void)unused; pthread_barrier_wait(&ready); pthread_mutex_lock(&cache_lock);').replace('(void)unused; pthread_mutex_lock(&log_lock);','(void)unused; pthread_barrier_wait(&ready); pthread_mutex_lock(&cache_lock);').replace('puts("T2 WAIT cache"); pthread_mutex_lock(&cache_lock);','puts("T2 WAIT cache"); pthread_mutex_lock(&log_lock);')
    if name == 'deadlock_005':
        return source.replace('pthread_join(t,NULL); pthread_mutex_unlock(&state);','pthread_mutex_unlock(&state); pthread_join(t,NULL);')
    if name == 'race_001':
        return source.replace('counter++;','pthread_mutex_lock(&counter_lock); counter++; pthread_mutex_unlock(&counter_lock);')
    if name == 'race_002':
        return source.replace('long old=balance;', 'pthread_mutex_lock(&balance_lock); long old=balance;').replace('completed[id]++;','completed[id]++; pthread_mutex_unlock(&balance_lock);')
    if name == 'race_003':
        return source.replace('if(!initialized)', 'pthread_mutex_lock(&cache_lock); if(!initialized)').replace('observed[id]=cache_value;', 'observed[id]=cache_value; pthread_mutex_unlock(&cache_lock);')
    if name == 'race_004':
        return source.replace('int slot=tail;', 'pthread_mutex_lock(&queue_lock); int slot=tail;').replace('tail=slot+1;', 'tail=slot+1; pthread_mutex_unlock(&queue_lock);')
    if name == 'race_005':
        return source.replace('config.version=i;', 'pthread_mutex_lock(&config_lock); config.version=i;').replace('config.inverse=~i;', 'config.inverse=~i; pthread_mutex_unlock(&config_lock);').replace('do { int v=', 'do { pthread_mutex_lock(&config_lock); int v=').replace('bad_reads++; }', 'bad_reads++; pthread_mutex_unlock(&config_lock); }')
    raise ValueError(name)


@pytest.mark.parametrize('name',['deadlock_001','deadlock_002','deadlock_003','deadlock_004','deadlock_005','race_001','race_002','race_003','race_004','race_005'])
def test_semantic_oracle_accepts_working_repair_rejects_deleted_work(name):
    if os.getenv('AK_REMOTE_TEST_HOST')!='1': pytest.skip('Native fixture checks are remote-only')
    from agentkernel.concurrency.sandbox.local import LocalSandboxBackend
    async def run():
        task=load_task(Path(__file__).parents[1]/'benchmarks'/name)
        async with LocalSandboxBackend() as box:
            await box.upload_project(task.workspace,task.source_files+task.support_files)
            source=fixed_fixture(name,(task.workspace/'main.c').read_text())
            (box.workspace/'main.c').write_text(source)
            result=await check_semantics(task,box)
            assert result['passed'], (name,result)
            # Keep global state declarations, but replace the complete program entry
            # with a termination-only no-op. The immutable oracle must reject it.
            before=source.split('int main(void)')[0]
            (box.workspace/'main.c').write_text(before+'int main(void) { puts("PASS"); return 0; }\n')
            rejected=await check_semantics(task,box)
            assert not rejected['passed'], name
    asyncio.run(run())
