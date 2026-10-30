"""Prospectively frozen paired cloud comparison; no cache, local model or reference repairs."""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.sandbox.local import safe_path
from agentkernel.repository.adaptive_v3 import ProductRepair, product_quote,remote_models,CAPS
from agentkernel.repository.budget import BudgetLedger
from run_cloud_adaptive import catalog

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/adaptive-v3/product-v1'
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,indent=2),encoding='utf-8')


def report(out,rows,complete):
    aggregates={}
    for arm in ('super_only','ultra_only','fast'):
        subset=[r for r in rows if r['arm']==arm]
        durations=[r['end_to_end_ms'] for r in subset if r.get('end_to_end_ms') is not None]
        solved=sum(r.get('status')=='verified' for r in subset)
        tokens=None if any(r.get('tokens') is None for r in subset) else sum(r['tokens'] for r in subset)
        aggregates[arm]={'completed':len(subset),'verified':solved,'tokens':tokens,
            'tokens_per_verified':tokens/solved if solved and tokens is not None else None,
            'cost_usd':None if any(r.get('cost_usd') is None for r in subset) else sum(r['cost_usd'] for r in subset),
            'calls':sum(r.get('model_calls',0) for r in subset),'ultra_calls':sum(a.get('stage')=='ultra' and a.get('model_calls',0) for r in subset for a in r.get('attempts',[])),
            'false_fix_candidates':sum(bool(a.get('false_fix')) for r in subset for a in r.get('attempts',[])),
            'median_e2e_ms':statistics.median(durations) if durations else None,
            'unknown':sum(r.get('status')=='unknown' for r in subset)}
    view={'complete':complete,'rows':rows,'aggregates':aggregates,
          'scope':'Eight existing synthetic test designs. Prospective matched comparison, not proof of pretraining novelty or production superiority.',
          'same_component_caps':True,'reference_repairs_sent':False,'new_local_model_calls':0,'cache_used':False}
    save(out/'comparison-view.json',view)
    lines=['# Frozen cloud routing comparison','',view['scope'],'',
        '| Route | Completed | Verified | Calls | Ultra calls | Tokens | USD | Median e2e (s) | False-fix candidates |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for arm,r in aggregates.items():
        lines.append(f"| {arm} | {r['completed']} | {r['verified']} | {r['calls']} | {r['ultra_calls']} | {r['tokens']} | {r['cost_usd']} | {r['median_e2e_ms']/1000 if r['median_e2e_ms'] else '—'} | {r['false_fix_candidates']} |")
    lines+=['','Unknowns are separate from failures. Failed candidates consume tokens/cost. Adaptive can cost more than Ultra-only when Super fails. Do not infer statistical superiority from this suite.',
        '',f'Complete: {complete}. No post-result prompt, fixture, cap or routing changes. Full raw evidence is under each case/arm.']
    (out/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')


async def main(args):
    load_env_file(ROOT/'.env');os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    live=await catalog();ledger=BudgetLedger(ROOT/'reports/product-v3/budget.json')
    if args.prepare:
        cases=[c for c in read(DATA/'manifest.json')['cases'] if c['split']=='test']
        bound=2*len(cases)*product_quote(live,max_input_tokens=12000)
        if bound>1 or ledger.snapshot()['committed_usd']+bound>10:raise ValueError('Comparison exceeds $1 incremental or $10 pilot limit')
        out=ROOT/'reports/cloud-comparison'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');out.mkdir(parents=True)
        jobs=[]
        for index,case in enumerate(cases):
            root=DATA/'tasks'/case['id'];task=ConcurrencyTask.model_validate({**read(root/'task.json'),'workspace':root})
            frozen=out/'inputs'/case['id'];hashes={}
            for name,h in {**case['source_sha256'],**case['support_sha256']}.items():
                source=safe_path(root,name)
                if sha(source)!=h:raise ValueError('Dataset changed before freeze')
                target=frozen/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes());hashes[name]=h
            task=task.model_copy(update={'workspace':frozen.resolve()})
            arms=['super_only','ultra_only','fast'];arms=arms[index%3:]+arms[:index%3]
            jobs += [{'case':case['id'],'arm':arm,'task':task.model_dump(mode='json'),'files':hashes} for arm in arms]
        plan={'jobs':jobs,'max_new_paid_calls':32,'maximum_incremental_usd':bound,'models':remote_models(live),
            'input_cap':12000,'caps':CAPS,'total_token_cap_per_job':36288,'concurrency':2,'no_retries':True,
            'script_sha256':sha(Path(__file__)),
            'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src/agentkernel').rglob('*.py')},
            'no_reference_repairs_in_prompts':True,'sample_selection':'all eight pre-existing product-v1 test cases; no cherry picking'}
        save(out/'protocol.json',plan)
        print(json.dumps({'protocol':str(out/'protocol.json'),'jobs':len(jobs),'max_paid_calls':32,'max_usd':bound},indent=2));return
    path=args.execute.resolve();out=path.parent;plan=read(path)
    if (out/'started.json').exists():raise ValueError('Do not replay an interrupted comparison')
    if sha(Path(__file__))!=plan['script_sha256']:raise ValueError('Runner changed')
    for name,h in plan['source_sha256'].items():
        if sha(ROOT/name)!=h:raise ValueError('Implementation changed after freeze')
    if remote_models(live)!=plan['models']:
        # Catalog ancillary fields can change; exact IDs, prices and context must not.
        for s,m in remote_models(live).items():
            if any(m[k]!=plan['models'][s][k] for k in ('id','pricing','context_length')):raise ValueError('Model pricing/configuration changed')
    if ledger.snapshot()['committed_usd']+plan['maximum_incremental_usd']>10:raise ValueError('Pilot ceiling exceeded')
    for j in plan['jobs']:
        for name,h in j['files'].items():
            if sha(Path(j['task']['workspace'])/name)!=h:raise ValueError('Frozen case changed')
    save(out/'started.json',{'utc':datetime.now(timezone.utc).isoformat(),'automatic_replay':False})
    rows=[];slots=asyncio.Semaphore(2)
    async def execute(job):
        async with slots:
            task=ConcurrencyTask.model_validate(job['task']);folder=out/(job['case']+'--'+job['arm'])
            print('START',job['case'],job['arm'],flush=True)
            runner=ProductRepair(ROOT,live,ledger=ledger)
            try:
                async with asyncio.timeout(900):
                    value=await runner.run(task,folder,profile=job['arm'],max_cost_usd=product_quote(live,max_input_tokens=12000),
                        max_input_tokens=12000,max_output_tokens=8192,max_total_tokens=36288)
            except Exception as e:
                value={'status':'unknown','error':type(e).__name__,'tokens':None,'cost_usd':None}
            row={'case':job['case'],'arm':job['arm'],**value};rows.append(row)
            save(out/(job['case']+'--'+job['arm']+'-summary.json'),row)
            report(out,rows,False)
            print('DONE',job['case'],job['arm'],value['status'],'tokens',value.get('tokens'),flush=True)
    await asyncio.gather(*(execute(j) for j in plan['jobs']))
    report(out,rows,True)
    save(out/'complete.json',{'jobs':len(rows),'automatic_replay':False})
    print('REPORT',str(out/'REPORT.md'),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--execute',type=Path)
    asyncio.run(main(p.parse_args()))
