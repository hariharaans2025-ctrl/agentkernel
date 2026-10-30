"""Journaled remote campaigns with fewer transport calls and unchanged acceptance gates."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter

from agentkernel.concurrency.campaign.manager import StressCampaignManager
from agentkernel.concurrency.campaign.models import CampaignResult
from agentkernel.concurrency.execution.models import ExecutionRun, RunClassification
from agentkernel.concurrency.analyzer.classifier import classify
from agentkernel.concurrency.sandbox.base import CommandResult
from agentkernel.concurrency.sandbox.nebius import REMOTE_RUNNER


REMOTE_BATCH = r'''
import json, subprocess, sys, datetime
payload = json.loads(sys.argv[1])
for index, spec in enumerate(payload['specs']):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    child = subprocess.run(['python3', '-c', payload['runner'], json.dumps(spec)], capture_output=True, text=True, timeout=spec['timeout'] + 1)
    if child.returncode != 0:
        raise RuntimeError('Command wrapper failed; no automatic replay')
    result = json.loads(child.stdout)
    print(json.dumps({'index':index,'start_time':started,'result':result}), flush=True)
'''


def batch_size(timeout, cap=40):
    if timeout <= 0:
        raise ValueError('Positive command timeout required')
    return max(1, min(cap, int(150 // (timeout + 1))))


async def remote_batch(box, specs):
    if not specs or len(specs) > 40:
        raise ValueError('A batch requires 1..40 commands')
    budget = sum(s['timeout'] + 1 for s in specs) + 15
    if budget > 170:
        raise ValueError('Batch exceeds bounded service operation deadline')
    started = perf_counter()
    image = await box.image.run('python3', args=['-c', REMOTE_BATCH, json.dumps({'runner':REMOTE_RUNNER,'specs':specs},separators=(',',':'))],
                                timeout=budget, disposable=False, truncate_output_at=262144)
    if image.exit_code != 0:
        raise RuntimeError('Remote batch incomplete; preserve unknown outcome without replay')
    rows = [json.loads(line) for line in image.stdout.splitlines()]
    if [r.get('index') for r in rows] != list(range(len(specs))):
        raise RuntimeError('Remote batch evidence incomplete; no replay')
    box.image = image
    wall = (perf_counter() - started) * 1000
    for row, spec in zip(rows, specs, strict=True):
        CommandResult(command=spec['command'], **row['result'])
        row['result']['metadata'].update(remote_image_id=str(image.uuid), batch_transport_wall_ms=wall)
    return rows


class ProductCampaign(StressCampaignManager):
    def __init__(self, out, *, batch_cap=40, stop_on_failure=False):
        super().__init__()
        self.out, self.number = Path(out), 0
        self.batch_cap, self.stop_on_failure = batch_cap, stop_on_failure

    def save(self, name, value):
        self.out.mkdir(parents=True, exist_ok=True)
        with (self.out/name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)

    async def run(self, task, sandbox, *, runs=None):
        count = task.stress_runs if runs is None else runs
        if type(count) is not int or not 1 <= count <= 10000:
            raise ValueError('Bounded execution count required')
        self.number += 1
        started, records = perf_counter(), []
        size = batch_size(task.max_runtime_seconds, self.batch_cap)
        for first in range(0, count, size):
            specs = [{'command':task.run_command,'timeout':task.max_runtime_seconds,
                      'environment':{**task.environment, **self.schedule.environment_for(i)},
                      'limit':sandbox.output_limit} for i in range(first,min(first+size,count))]
            self.save(f'campaign-{self.number}-batch-{first+1}-started.json',
                      {'first_run':first+1,'count':len(specs),'utc':datetime.now(timezone.utc).isoformat(),'automatic_replay':False})
            rows = await remote_batch(sandbox, specs)
            self.save(f'campaign-{self.number}-batch-{first+1}.json', rows)
            for i, row in enumerate(rows, first):
                result = CommandResult(command=task.run_command, **row['result'])
                kind = classify(result, task.expected_behavior)
                records.append(ExecutionRun(run_id=f'{task.task_id}:{i+1}',start_time=row['start_time'],
                    duration_ms=result.duration_ms,exit_code=result.exit_code,stdout=result.stdout,stderr=result.stderr,
                    timed_out=result.timed_out,crashed=kind==RunClassification.CRASH,
                    sanitizer_detected=kind in {RunClassification.RACE_DETECTED,RunClassification.SANITIZER_FAILURE},
                    classification=kind,metadata=result.metadata))
            print(f'Campaign {self.number}: {len(records)}/{count}; '+str(dict(Counter(r.classification.value for r in records))),flush=True)
            if self.stop_on_failure and any(r.classification!=RunClassification.PASS for r in records):
                break
        campaign = CampaignResult(task_id=task.task_id,runs=records,requested_runs=count,
                                  counts=dict(Counter(r.classification.value for r in records)),duration_ms=(perf_counter()-started)*1000)
        self.save(f'campaign-{self.number}.json',campaign.model_dump(mode='json'))
        return campaign
