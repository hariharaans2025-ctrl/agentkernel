"""Fresh Nemotron Super -> Ultra repair on Token Factory; target code runs in Nebius Sandbox."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import httpx
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.sandbox.local import safe_path
from agentkernel.repository.adaptive_v3 import ProductRepair, product_quote, remote_models, CAPS
from agentkernel.repository.budget import BudgetLedger

ROOT=Path(__file__).resolve().parents[1]
IMAGE='agentkernel-clang:20261003122908'
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)


async def catalog():
    async with httpx.AsyncClient(timeout=30) as client:
        r=await client.get('https://api.tokenfactory.nebius.com/v1/models',params={'verbose':'true'},
            headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
        r.raise_for_status();return r.json()['data']


async def main(args):
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']=IMAGE
    live=await catalog()
    ledger=BudgetLedger(ROOT/'reports/product-v3/budget.json')
    if args.prepare:
        if not math.isfinite(args.max_cost_usd) or not 0<args.max_cost_usd<=.25:
            raise ValueError('Maximum route charge must be within $0.25')
        raw=read(args.prepare);task=ConcurrencyTask.model_validate(raw.get('task',raw))
        bound=product_quote(live,max_input_tokens=12000)
        budget=ledger.snapshot()
        if bound>args.max_cost_usd or bound>budget['remaining_usd'] or budget['committed_usd']+bound>10:
            raise ValueError('Route exceeds its approved limit or the conservative $10 pilot ceiling')
        out=ROOT/'reports/cloud-adaptive'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out.mkdir(parents=True,exist_ok=False)
        workspace=out/'input'
        hashes={}
        for name in task.source_files+task.support_files:
            source=safe_path(task.workspace.resolve(),name)
            data=source.read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
            target=workspace/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        task=task.model_copy(update={'workspace':workspace.resolve()})
        plan={'task':task.model_dump(mode='json'),'files':hashes,'image':IMAGE,'max_input_tokens':12000,
            'max_output_tokens':8192,'max_total_tokens':36288,'caps':CAPS,'max_calls':2,
            'max_cost_usd':bound,'models':remote_models(live),
            'controllers':{str(p.relative_to(ROOT)):digest(p) for folder in ('src/agentkernel/repository','src/agentkernel/concurrency') for p in (ROOT/folder).rglob('*.py')},
            'script_sha256':digest(Path(__file__)),'cache':False,'local_specialist':False,
            'scope':'Fresh cloud repair of a previously observed program; not unseen evaluation',
            'authorization':'User requested real cloud model calls and tokens; one bounded route, no retry or automatic replay.'}
        save(out/'plan.json',plan)
        print(json.dumps({'prepared':str(out/'plan.json'),'route':[m['id'] for m in plan['models'].values()],
                          'max_calls':2,'max_inference_usd':bound,'input_cap_per_call':12000,'output_caps':CAPS,
                          'paid_calls_started':0},indent=2))
        return
    path=args.execute.resolve();plan=read(path);out=path.parent
    if (out/'execution-started.json').exists():raise ValueError('An executed or interrupted route must never be replayed')
    if digest(Path(__file__))!=plan['script_sha256']:raise ValueError('Prepared controller changed')
    for name,h in plan['controllers'].items():
        if digest(ROOT/name)!=h:raise ValueError('Implementation changed after preparation')
    for stage,old in plan['models'].items():
        current=remote_models(live)[stage]
        if current['id']!=old['id'] or current['pricing']!=old['pricing'] or current['context_length']!=old['context_length']:
            raise ValueError('Re-establish the cost bound; model configuration changed')
    budget=ledger.snapshot()
    if budget['committed_usd']+plan['max_cost_usd']>10:raise ValueError('Conservative pilot ceiling exceeded')
    task=ConcurrencyTask.model_validate(plan['task'])
    for name,h in plan['files'].items():
        if digest(task.workspace/name)!=h:raise ValueError('Frozen input changed')
    save(out/'execution-started.json',{'utc':datetime.now(timezone.utc).isoformat(),'automatic_replay':False})
    runner=ProductRepair(ROOT,live,ledger=ledger,on_progress=lambda p:print(p['stage'],flush=True) if p.get('stage') else None)
    async with asyncio.timeout(900):
        result=await runner.run(task,out/'run',profile='fast',max_cost_usd=plan['max_cost_usd'],
            max_calls=2,max_input_tokens=12000,max_output_tokens=8192,max_total_tokens=36288)
    # Historical comparisons remain separate and are not matched experiments.
    summary={k:result.get(k) for k in ('status','model_calls','remote_model_calls','tokens','cost_usd','inference_ms','verification_ms','end_to_end_ms','false_fix')}
    summary.update(cache_used=False,local_specialist_used=False,origin='Fresh Nebius Token Factory model output')
    save(out/'summary.json',summary)
    print(json.dumps({'evidence':str(out),**summary},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',type=Path,help='ConcurrencyTask JSON or an onboarding plan containing task')
    group.add_argument('--execute',type=Path,help='Prepared plan; no automatic replay')
    parser.add_argument('--max-cost-usd',type=float,default=.25)
    asyncio.run(main(parser.parse_args()))
