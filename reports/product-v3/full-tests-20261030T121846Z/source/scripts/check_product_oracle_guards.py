"""Remote negative controls: correct locks plus a constant-true reader must fail."""
import asyncio
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from verify_saved_super_candidate import JournalCampaign

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/adaptive-v3/product-v2'


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)


async def main():
    load_env_file(ROOT/'.env');os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    out=ROOT/'reports/adaptive-v3'/('oracle-mutation-controls-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((DATA/'manifest.json').read_text());results=[]
    save(out/'plan.json',{'dataset':str(DATA.relative_to(ROOT)),'manifest_sha256':hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest(),
        'origin':'Manual adversarial oracle calibration, not a model output or model score','model_calls':0,'candidate':'Verified reference locks; deliberately replace consistency expression with constant true.'})
    for case in manifest['cases']:
        if case['family'] not in {'snapshot','aggregate'}:continue
        name=case['id'];folder=out/name;folder.mkdir();workspace=folder/'candidate';workspace.mkdir()
        data=DATA/'tasks'/name;task=ConcurrencyTask.model_validate({**json.loads((data/'task.json').read_text()),'workspace':workspace})
        reader='snapshot.c' if case['family']=='snapshot' else 'read.c'
        for filename in task.source_files:
            original=(DATA/'references'/name/filename).read_text(encoding='utf-8')
            if hashlib.sha256(original.encode()).hexdigest()!=case['reference_sha256'][filename]:raise ValueError('Reference changed')
            content=original
            if filename==reader:
                content,count=re.subn(r'\bint result=[^;]+;', 'int result=1;',original)
                if count!=1 or content.count('sched_yield(')!=original.count('sched_yield('):raise ValueError('Mutation must preserve scheduling hooks')
            (workspace/filename).write_text(content,encoding='utf-8',newline='')
        for filename in task.support_files:
            payload=(data/filename).read_bytes()
            if hashlib.sha256(payload).hexdigest()!=case['support_sha256'][filename]:raise ValueError('Oracle changed')
            (workspace/filename).write_bytes(payload)
        campaign=JournalCampaign(folder)
        print('MUTATION_CONTROL',name,flush=True)
        async with NebiusSandboxBackend(temporary_parent=folder) as box:
            await box.upload_project(workspace,task.source_files+task.support_files)
            build=await CCompiler().compile(task,box);save(folder/'build.json',build.model_dump(mode='json'))
            if not build.success:raise ValueError('Mutation should compile normally')
            runs=await campaign.run(task,box,runs=3);save(folder/'runs.json',runs.model_dump(mode='json'))
            if runs.infrastructure_failures or runs.failed_runs!=3:raise ValueError('Oracle accepted a constant-true repair')
            test=await box.run_command(['./app','--check'],timeout=task.max_runtime_seconds)
            save(folder/'semantic.json',test.model_dump(mode='json'))
            if test.exit_code==0 or test.timed_out or test.metadata.get('error'):raise ValueError('Required functional test did not reject mutation normally')
        result={'case':name,'mutation_rejected':True,'failed_runs':3,'semantic_rejected':True,'scheduling_hooks_preserved':True,'model_calls':0}
        results.append(result);save(folder/'result.json',result)
    save(out/'complete.json',{'cases':results,'model_calls':0,'all_mutations_rejected':len(results)==6})
    print('ORACLE_GUARDS_REPORT',out,flush=True)


if __name__=='__main__':asyncio.run(main())
