"""Reverify one preserved model proposal; zero inference requests. No reference repair inputs."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from agentkernel.config import load_env_file
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.repair.patch_applier import UnifiedDiffApplier
from agentkernel.repository.candidate_reuse import VerifiedCandidateCache, run_with_candidate_reuse
from verify_saved_super_candidate import JournalCampaign

ROOT=Path(__file__).resolve().parents[1]
ORIGIN=ROOT/'reports/sites-console/runs/2c402840-71de-4ce2-a684-0e67dc7a9d75'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


async def main():
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    out=ROOT/'reports/candidate-reuse'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    preserved={str(p):sha(p) for p in ORIGIN.rglob('*') if p.is_file()}
    plan=read(ORIGIN/'plan/plan.json')
    task=ConcurrencyTask.model_validate({**plan['task'],'workspace':ORIGIN/'original'})
    for name,entry in plan['files'].items():
        if sha(task.workspace/name)!=entry['sha256']:raise ValueError('Original capture changed')
    previous=read(ORIGIN/'result.json')
    candidate=read(ORIGIN/'route/fine_tuned/candidate-sources.json')
    # Link the canonical patch to the exact saved model candidate before admission.
    with tempfile.TemporaryDirectory() as directory:
        stage=Path(directory)
        for name in task.source_files:
            (stage/name).parent.mkdir(parents=True,exist_ok=True)
            (stage/name).write_bytes((task.workspace/name).read_bytes())
        applied=UnifiedDiffApplier().apply(stage,previous['patch'],task.source_files)
        if not applied.success or any((stage/n).read_text()!=candidate[n] for n in candidate):
            raise ValueError('Saved patch does not reproduce the saved model candidate')
    cache=VerifiedCandidateCache(out/'cache')
    policy={'experiment':'exact saved model candidate; fresh verdict','adapter_sha256':previous['adapter_sha256']}
    key,identity=cache.identity(task,policy)
    cache.admit(key,identity,previous['patch'],read(ORIGIN/'route/fine_tuned/verification.json'),ORIGIN)
    async def forbidden(*args):raise AssertionError('This verification-only experiment must never call a model')
    async with asyncio.timeout(600):
        result=await run_with_candidate_reuse(task,out/'reverified',cache=cache,policy=policy,
            run_fresh=forbidden,campaign_factory=JournalCampaign)
    unchanged=all(p.is_file() and sha(p)==value for name,value in preserved.items() for p in [Path(name)])
    summary={'scope':'Repeated-input proposal reuse, not unseen evaluation or matched latency benchmark',
             'historical':{k:previous.get(k) for k in ('status','tokens','model_calls','cost_usd','end_to_end_ms')},
             'reuse':result,'original_evidence_unchanged':unchanged,'new_paid_model_calls':0,
             'latency_caveat':'Historical runs differ in time/network conditions. No statistical or causal speedup claim.'}
    (out/'comparison.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(out),'status':result['status'],'tokens':result['tokens'],
        'model_calls':result['model_calls'],'end_to_end_ms':result['end_to_end_ms'],
        'original_evidence_unchanged':unchanged},indent=2))


if __name__=='__main__':asyncio.run(main())
