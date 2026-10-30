"""Matched base/LoRA/adaptive holdout comparison; no test labels in model requests."""
import asyncio
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import httpx
from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.repository.adaptive import AdaptiveRepair,route_quote
from agentkernel.repository.learning import evaluation_metrics
from verify_saved_super_candidate import JournalCampaign

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/adaptive-v2/holdout-v1'
MODEL_ROOT=ROOT/'models/adaptive-specialist-v1'


def save(path,data):Path(path).write_text(json.dumps(data,indent=2),encoding='utf-8')


async def main():
    load_env_file(ROOT/'.env');os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    async with httpx.AsyncClient(timeout=30) as client:
        r=await client.get('https://api.tokenfactory.nebius.com/v1/models',params={'verbose':'true'},headers={'Authorization':'Bearer '+os.environ['NEBIUS_API_KEY']})
        r.raise_for_status();models=r.json()['data']
    bound=route_quote(models)
    if bound*2>.25:raise ValueError('The two-case pilot exceeds its $0.25 aggregate inference reservation')
    out=ROOT/'reports/adaptive-v2'/('evaluation-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True,exist_ok=False)
    meta=json.loads((MODEL_ROOT/'training.json').read_text())
    freeze=json.loads((DATA/'manifest.json').read_text())
    save(out/'protocol.json',{'arms':['base','fine_tuned','adaptive'],'cases':[c['id'] for c in freeze['cases']],
        'base_model':meta['base_model'],'base_revision':meta['base_revision'],'adapter_sha256':meta['adapter_sha256'],
        'selected_epoch':meta['selected_epoch'],'checkpoint_selection':'development validation only',
        'max_total_remote_inference_usd':2*bound,'max_remote_calls':4,'model_output_cap':2048,
        'execution':'Nebius Sandbox','sandbox_billing':'Existing owner-confirmed free beta','all_stress_runs':100,'tsan_runs':3,
        'no_test_labels_in_prompts':True,'no_finetune_or_prompt_selection_from_test_outcomes':True,'no_auto_replays':True,
        'scope':'Small synthetic transfer pilot within familiar bug families; not a production-quality estimate.'})
    rows=[]
    # All local comparisons are frozen and executed before any adaptive fallback results.
    for mode in ('base','fine_tuned','adaptive'):
        for case in freeze['cases']:
            task=ConcurrencyTask.model_validate({**json.loads((DATA/case['id']/'task.json').read_text()),'workspace':DATA/case['id']})
            if hashlib.sha256((task.workspace/'solution.c').read_bytes()).hexdigest()!=case['source_sha256']:
                raise ValueError('Heldout source changed')
            print('Evaluating',mode,case['id'],flush=True)
            def progress(data):
                if 'stage' in data:print(data['stage'],flush=True)
            runner=AdaptiveRepair(ROOT,models,JournalCampaign,on_progress=progress,model_root=MODEL_ROOT)
            async with asyncio.timeout(1800):
                result=await runner.run(task,out/(mode+'-'+case['id']),mode=mode,max_cost_usd=bound if mode=='adaptive' else 0,
                    max_calls=3 if mode=='adaptive' else 1)
            result.update(case=case['id'],outcome=result['status'],arm=mode)
            rows.append(result)
            save(out/'results.json',{'rows':rows,'arms':{arm:evaluation_metrics([r for r in rows if r['arm']==arm]) for arm in ('base','fine_tuned','adaptive')}})
            print('Outcome',mode,case['id'],result['status'],'tokens',result['tokens'],'cost',result['cost_usd'],flush=True)
    save(out/'complete.json',{'completed':True,'jobs':len(rows),'remote_inference_cost_usd':sum(r['cost_usd'] or 0 for r in rows),
        'all_costs_known':all(r['cost_usd'] is not None for r in rows),'trained_adapter_sha256':meta['adapter_sha256']})
    print('Evaluation complete:',out,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,default=DATA);parser.add_argument('--model-root',type=Path,default=MODEL_ROOT)
    args=parser.parse_args();DATA=args.data.resolve();MODEL_ROOT=args.model_root.resolve()
    asyncio.run(main())
