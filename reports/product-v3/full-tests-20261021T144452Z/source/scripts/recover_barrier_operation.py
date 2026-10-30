"""Read existing operation evidence only; never execute or replay workload."""
import asyncio
import base64
from datetime import datetime, timezone
import json
import os
from contree_sdk import Contree
from contree_sdk.auth import IAMAuth
from contree_sdk.config import ContreeConfig
from repository_live_ab import ROOT, save, read, load_env_file, digest


async def main():
    prior=ROOT/'reports/barrier-repair-live/20261010T092756Z'
    out=ROOT/'reports/barrier-repair-recovery'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    load_env_file(ROOT/'.env')
    client=Contree(ContreeConfig(auth=IAMAuth(token=os.environ['NEBIUS_API_KEY'],project_id=os.environ['NEBIUS_PROJECT_ID']),transport_timeout=20))
    operation='01a12525-b2a1-73fc-8f4c-80be9491690e'
    response=await client._api.get_operation_status(operation)
    record={'operation_id':operation,'status':str(response.status),'prior_metrics_sha256':digest(prior/'metrics.json')}
    result=response.metadata.result if response.metadata else None
    if result:
        for name in ('stdout','stderr'):
            stream=getattr(result,name)
            record[name]=base64.b64decode(stream.value).decode() if str(stream.encoding)=='base64' else stream.value
            record[name+'_truncated']=stream.truncated
        record.update(exit_code=result.state.exit_code,timed_out=result.state.timed_out)
    save(out/'recovered-operation.json',record)
    rows=[json.loads(line) for line in record.get('stdout','').splitlines()]
    passed=sum(row['result']['exit_code']==0 and not row['result']['timed_out'] and '\nPASS\n' in row['result']['stdout'] for row in rows)
    save(out/'assessment.json',{'recovered_executions':len(rows),'recovered_passes':passed,
        'complete_100_run_evidence':False,'verification_outcome':'UNKNOWN','additional_model_calls':0,
        'additional_workload_executions':0,'reason':'Earlier 90 results were in memory when transport failed; campaign file was not persisted. Semantic/TSan verification not reached.'})
    (out/'REPORT.md').write_text(f'''# Interrupted diagnostic-assisted repair

The single Super call completed: 5,022 input + 1,040 output = 6,062 tokens, 5.564 seconds provider latency. The candidate was applied in Nebius Sandbox.

DNS resolution failed while retrieving the last stress batch. A read-only fetch recovered {len(rows)} executions from that existing operation, with {passed} passing. The earlier 90 executions were reported as completed by progress output, but their detailed results were held in memory and not persisted before interruption. Do not claim 100/100 or even 90/100 passes.

Overall verification: **INTERRUPTED / UNKNOWN**. Semantic and TSan results are unavailable. No workload was replayed and no additional model call was made.

Source review: the model removed the barrier-with-held-lock pattern, but writes q->completed under queue_lock while the monitor reads it under stats_lock. These different mutexes do not synchronize the accesses. This is a suspected introduced data race, not a measured TSan result. The emitted HOLD/WAIT messages also no longer describe the actual lock state.

The candidate is not accepted or promoted. Original run evidence remains immutable. Completing evaluation requires a separately recorded verification-only campaign against the exact saved candidate, with no model call or source edits.
''',encoding='utf-8')
    print(json.dumps({'report':str(out/'REPORT.md'),'status':record['status'],'recovered':len(rows),'passed':passed}),flush=True)


if __name__=='__main__': asyncio.run(main())
