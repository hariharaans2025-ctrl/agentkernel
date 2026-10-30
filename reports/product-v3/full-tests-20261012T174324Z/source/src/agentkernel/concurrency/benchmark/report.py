"""Framework-independent report and frontend data contract."""
import csv
import json
from pathlib import Path
from agentkernel.telemetry.redaction import redact
from .metrics import summarize, false_fix


def job_data(job, mode):
    attempts = job.metadata.get('model_attempts', [])
    def total(field):
        values = [a.get(field) for a in attempts]
        return sum(values) if values and all(v is not None for v in values) and job.inference_mode == 'real' else None
    verification = job.verification or {}
    return redact({'fixture':job.task, 'mode':mode, 'status':job.status,
        'baseline_status':'failed' if job.baseline.get('failed_runs') else 'clean' if job.baseline.get('build_passed') else 'unavailable',
        'baseline':job.baseline, 'fingerprints':job.baseline.get('fingerprints',[]), 'route':job.route,
        'model_attempts':attempts, 'repairs':job.repairs,
        'patches':[r.get('proposal',{}).get('patch') for r in job.repairs],
        'verification_progress':{'completed':verification.get('total_runs'), 'required':job.metadata.get('verification_configuration',{}).get('stress_runs')},
        'execution_passed':verification.get('execution_passed'), 'semantic_passed':verification.get('semantic_passed'),
        'sanitizer_passed':verification.get('sanitizer_passed'), 'semantic_checks':verification.get('evidence',{}).get('semantic'),
        'sanitizer_checks':verification.get('evidence',{}).get('sanitizer'),
        'patch_accepted':any(r.get('patch',{}).get('success') for r in job.repairs), 'build_passed':verification.get('build_passed'),
        'input_tokens':total('input_tokens'), 'output_tokens':total('output_tokens'), 'reasoning_tokens':total('reasoning_tokens'),
        'inference_latency_ms':job.inference_latency_ms if attempts else None, 'execution_latency_ms':job.execution_latency_ms,
        'end_to_end_latency_ms':job.total_time_ms, 'verification_runs':verification.get('total_runs'),
        'passes':verification.get('passed_runs'), 'deadlocks':verification.get('deadlock_count'),
        'races':verification.get('race_count') if verification.get('sanitizer_passed') is not None else None,
        'crashes':verification.get('crash_count'), 'infrastructure_failures':verification.get('infrastructure_failures'),
        'false_fix':any(false_fix(r) for r in job.repairs), 'final_tier':job.route[-1] if job.route else None,
        'format_rejections':job.metadata.get('format_rejections',0),
        'patch_rejections':sum(not r.get('patch',{}).get('success') for r in job.repairs),
        'nano_calls':job.model_calls.get('NANO',0), 'super_calls':job.model_calls.get('SUPER',0), 'ultra_calls':job.model_calls.get('ULTRA',0),
        'cost_usd':job.cost_usd if job.metadata.get('pricing_authoritative') and job.inference_mode=='real' else None,
        'grounding':job.metadata.get('grounding'), 'observability':job.metadata.get('observability'),
        'source_sha256':job.metadata.get('source_sha256'), 'inference_mode':job.inference_mode})


def write_reports(root, report):
    root = Path(root); root.mkdir(parents=True,exist_ok=True)
    data = redact(report)
    dest = root/'final-benchmark.json'
    temp = dest.with_suffix('.tmp'); temp.write_text(json.dumps(data,indent=2),encoding='utf-8'); temp.replace(dest)
    fields = ['fixture','mode','status','final_tier','input_tokens','output_tokens','reasoning_tokens','inference_latency_ms',
        'execution_latency_ms','end_to_end_latency_ms','patch_accepted','build_passed','execution_passed','semantic_passed',
        'sanitizer_passed','verification_runs','passes','deadlocks','races','crashes','infrastructure_failures','false_fix',
        'nano_calls','super_calls','ultra_calls','cost_usd']
    with (root/'final-benchmark.csv').open('w',encoding='utf-8',newline='') as out:
        writer = csv.DictWriter(out,fieldnames=fields,extrasaction='ignore'); writer.writeheader()
        for row in data['rows']:
            # Neutralize spreadsheet formula prefixes in untrusted text.
            writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()})
    lines = ['# Final benchmark', '', 'Status: '+data['status'], '',
        'Unknown values are null in JSON and blank in CSV. No model superiority claim is supported by this report.', '',
        '| Fixture | Mode | Status | Final tier | Semantic | Sanitizer |', '|---|---|---|---|---|---|']
    for row in data['rows']:
        lines.append('| '+' | '.join(str(row.get(k) if row.get(k) is not None else 'Not measured').replace('|','/') for k in ['fixture','mode','status','final_tier','semantic_passed','sanitizer_passed'])+' |')
    lines += ['', '## Aggregate metrics', '', '```json', json.dumps(data.get('aggregate',{}),indent=2),'```', '',
              '## Execution gate', '', '```json',json.dumps(data.get('plan',{}),indent=2),'```']
    (root/'final-benchmark.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
