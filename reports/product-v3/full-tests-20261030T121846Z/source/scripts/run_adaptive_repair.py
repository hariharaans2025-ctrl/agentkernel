"""Run the installed specialist or bounded adaptive route against an explicit reviewed case."""
import argparse,asyncio,json,os
from datetime import datetime,timezone
from pathlib import Path
import httpx
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.repository.adaptive import AdaptiveRepair,route_quote
from agentkernel.repository.specialist import active_root,artifact_ready
from agentkernel.repository.candidate_reuse import VerifiedCandidateCache,run_with_candidate_reuse
from verify_saved_super_candidate import JournalCampaign
ROOT=Path(__file__).resolve().parents[1]
async def main(args):
    load_env_file(ROOT/'.env');os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    model=active_root(ROOT)
    if not artifact_ready(model):raise ValueError('Install or train the specialist before running.')
    started=json.loads((model/'started.json').read_text());dataset=Path(started['dataset']);dataset=dataset if dataset.is_absolute() else ROOT/dataset
    data=ROOT/json.loads((dataset/'manifest.json').read_text())['test_source']
    allowed={c['id'] for c in json.loads((data/'manifest.json').read_text())['cases']}
    if args.case not in allowed:raise ValueError('Choose one of the installed cases: '+', '.join(sorted(allowed)))
    task=ConcurrencyTask.model_validate({**json.loads((data/args.case/'task.json').read_text()),'workspace':data/args.case})
    models=[];ceiling=0
    if args.mode=='adaptive':
        async with httpx.AsyncClient(timeout=30) as client:
            response=await client.get('https://api.tokenfactory.nebius.com/v1/models',params={'verbose':'true'},headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
            response.raise_for_status();models=response.json()['data']
        ceiling=route_quote(models)
        if ceiling>args.max_cost_usd:raise ValueError('Live route exceeds the specified charge cap')
    out=ROOT/'reports/adaptive-v2'/('single-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    print('Running',args.case,args.mode,'maximum hosted inference charge',ceiling,flush=True)
    runner=AdaptiveRepair(ROOT,models,JournalCampaign,on_progress=lambda d:print(d['stage'],flush=True) if 'stage' in d else None)
    async with asyncio.timeout(1800):
        async def fresh(frozen, output):
            return await runner.run(frozen,output,mode=args.mode,max_cost_usd=ceiling,max_calls=3 if args.mode=='adaptive' else 1)
        if args.reuse_verified_candidate:
            policy={'route':'adaptive-v2','mode':args.mode,'model_catalog':[m['id'] for m in models],
                    'adapter_sha256':json.loads((model/'training.json').read_text())['adapter_sha256'],
                    'controller_sha256':__import__('hashlib').sha256((ROOT/'src/agentkernel/repository/adaptive.py').read_bytes()).hexdigest()}
            result=await run_with_candidate_reuse(task,out,cache=VerifiedCandidateCache(ROOT/'work/verified-candidates'),
                policy=policy,run_fresh=fresh,campaign_factory=JournalCampaign)
        else:
            result=await fresh(task,out)
    print(json.dumps({'status':result['status'],'model_calls':result['model_calls'],'tokens':result['tokens'],'cost_usd':result['cost_usd'],'evidence':str(out)},indent=2))
    return 0 if result['status']=='verified' else 1
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',default='inventory_stock')
    parser.add_argument('--mode',choices=['base','fine_tuned','adaptive'],default='fine_tuned')
    parser.add_argument('--max-cost-usd',type=float,default=.25)
    parser.add_argument('--reuse-verified-candidate',action='store_true',help='Reuse an identical-input proposal; always run full fresh sandbox verification')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
