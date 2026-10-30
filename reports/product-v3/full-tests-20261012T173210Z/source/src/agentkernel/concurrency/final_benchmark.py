"""Explicit live gate. Default invocation only generates an unexecuted plan."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from agentkernel.config import load_env_file
from agentkernel.providers.nebius_token_factory import NebiusTokenFactoryProvider
from agentkernel.telemetry.recorder import TelemetryRecorder
from .app import ConcurrencyBugHunter, ConcurrencyPolicy
from .benchmark.loader import discover_tasks, load_task
from .benchmark.metrics import summarize
from .benchmark.report import job_data, write_reports

MODES = ('nano_only','super_only','ultra_only','adaptive')


def execution_plan(tasks, modes=MODES):
    candidate_multiplier = sum(2 if m=='adaptive' else 1 for m in modes)
    calls = {m:len(tasks)*(3 if m=='adaptive' else 1) for m in modes}
    return {'fixtures':len(tasks),'modes':list(modes),'paid_calls_max_by_mode':calls,
        'paid_calls_max':sum(calls.values()),'repair_attempts_max':candidate_multiplier*len(tasks),
        'verification_stress_executions_max':sum(t.verification_config.stress_runs for t in tasks)*candidate_multiplier,
        'semantic_executions_max':sum(len(t.verification_config.semantic_checks) for t in tasks)*candidate_multiplier,
        'sanitizer_verification_executions_max':sum(t.verification_config.sanitizer_runs for t in tasks if t.verification_config.sanitizer_required)*candidate_multiplier,
        'baseline_executions_max':len(modes)*sum(t.stress_runs+(t.verification_config.sanitizer_runs if t.verification_config.sanitizer_required else 0) for t in tasks),
        'required_tsan':[t.task_id for t in tasks if t.verification_config.sanitizer_required],
        'repair_output_token_cap':2048,'triage_output_token_cap':768,
        'max_output_tokens':sum(len(tasks)*(2*2048+768 if m=='adaptive' else 2048) for m in modes),
        'retries':0, 'semantic_conditions_required':True,
        'note':'Upper bounds, not forecasts. Build failures, missing tools or successful Super verification reduce calls/executions.'}


async def execute(tasks, modes, report, root):
    provider = NebiusTokenFactoryProvider(max_retries=0)
    catalog = await provider.check_models()
    if not catalog.available:
        raise ValueError('Model catalog check failed; no substitution or inference permitted')
    jobs=[]
    for mode in modes:
        for task in tasks:
            report['status']='running'
            report['in_progress']={'fixture':task.task_id,'mode':mode}
            write_reports(root,report)  # Durable before any paid work.
            recorder=TelemetryRecorder()
            try:
                job=await ConcurrencyBugHunter(provider,recorder,ConcurrencyPolicy(mode=mode.replace('_','-'))).run(task)
            finally:
                recorder.export_jsonl(root/(task.task_id+'-'+mode+'.jsonl'))
            jobs.append(job); report['rows'].append(job_data(job,mode)); report['aggregate']=summarize(jobs)
            report['in_progress']=None; write_reports(root,report)
            if job.status in ('tooling_unavailable','execution_blocked','execution_unavailable'):
                report['status']='blocked'; write_reports(root,report); return
    report['status']='completed'; write_reports(root,report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,default=Path('benchmarks'))
    parser.add_argument('--output',type=Path,default=Path('reports'))
    parser.add_argument('--env-file',type=Path,default=Path('.env'))
    parser.add_argument('--modes',nargs='+',choices=MODES,default=list(MODES))
    parser.add_argument('--live',action='store_true',help='Explicitly authorize paid bounded inference')
    parser.add_argument('--sandbox-image')
    args=parser.parse_args()
    if len(set(args.modes))!=len(args.modes): parser.error('Duplicate modes are not permitted')
    tasks=[load_task(p) for p in discover_tasks(args.fixtures)]
    if not tasks: parser.error('No fixtures')
    path=args.output/'final-benchmark.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('status')!='not_run':
        parser.error('Output contains started benchmark evidence; use a new output directory. Never automatically replay paid work.')
    plan=execution_plan(tasks, args.modes)
    report={'schema_version':2,'status':'not_run','plan':plan,'rows':[],'aggregate':summarize([])}
    if not args.live:
        write_reports(args.output,report); print(json.dumps(plan,indent=2)); return
    load_env_file(args.env_file)
    if not args.sandbox_image: parser.error('--sandbox-image requires the prepared, probed toolchain image')
    readiness=Path('reports/toolchain.json')
    if not readiness.exists(): parser.error('Run scripts/prepare_sandbox_toolchain.py first')
    probe=json.loads(readiness.read_text(encoding='utf-8'))
    if probe.get('status')!='ready' or probe.get('image')!=args.sandbox_image:
        parser.error('Required TSan toolchain is not verified ready; no security-control workaround is allowed')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE']=args.sandbox_image
    asyncio.run(execute(tasks,args.modes,report,args.output))


if __name__=='__main__': main()
