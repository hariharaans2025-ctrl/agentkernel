"""Calibrate frozen holdout oracles with broken originals and manual reference repairs."""
import asyncio
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
from agentkernel.config import load_env_file
from agentkernel.repository.learning import require_verified
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.concurrency.instrumentation.sanitizer import instrumented_task, SanitizerConfig
from verify_saved_super_candidate import JournalCampaign

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'datasets/adaptive-v2/holdout-v1'
REFERENCES={'inventory_stock': '#include "state.h"\n#include <sched.h>\nint take_item(Inventory *stock) {\n    pthread_mutex_lock(&stock->mutex);\n    int old = stock->remaining;\n    if (old == 0) { pthread_mutex_unlock(&stock->mutex); return 0; }\n    sched_yield();\n    stock->remaining = old - 1;\n    pthread_mutex_unlock(&stock->mutex);\n    return 1;\n}\nint remaining_stock(Inventory *stock) {\n    pthread_mutex_lock(&stock->mutex);\n    int result = stock->remaining;\n    pthread_mutex_unlock(&stock->mutex);\n    return result;\n}\n', 'barrier_cache': '#include "state.h"\n#include <sched.h>\nvoid publish_cache(Cache *cache) {\n    meet(cache);\n    pthread_mutex_lock(&cache->mutex);\n    sched_yield();\n    cache->value = 42;\n    pthread_mutex_unlock(&cache->mutex);\n}\nvoid observe_cache(Cache *cache) {\n    meet(cache);\n    pthread_mutex_lock(&cache->mutex);\n    sched_yield();\n    cache->observed = cache->value;\n    pthread_mutex_unlock(&cache->mutex);\n}\n'}
REFERENCES.update({
'ticket_office':'''#include "state.h"
#include <sched.h>
int reserve_ticket(TicketOffice *office) {
    pthread_mutex_lock(&office->mutex);
    int ticket = office->next_ticket;
    sched_yield();
    office->next_ticket = ticket + 1;
    pthread_mutex_unlock(&office->mutex);
    return ticket;
}
int issued_count(TicketOffice *office) {
    pthread_mutex_lock(&office->mutex);
    int result = office->next_ticket;
    pthread_mutex_unlock(&office->mutex);
    return result;
}
''',
'version_stamp':'''#include "state.h"
#include <sched.h>
void publish_stamp(Stamp *stamp,int generation) {
    pthread_mutex_lock(&stamp->mutex);
    stamp->generation=generation;
    sched_yield();
    stamp->checksum=generation ^ 0x5a5a;
    pthread_mutex_unlock(&stamp->mutex);
}
void read_stamp(Stamp *stamp,int *generation,int *checksum) {
    pthread_mutex_lock(&stamp->mutex);
    *generation=stamp->generation;
    sched_yield();
    *checksum=stamp->checksum;
    pthread_mutex_unlock(&stamp->mutex);
}
''',
'account_delta':'''#include "state.h"
#include <sched.h>
void deposit(Account *account, int amount) {
    pthread_mutex_lock(&account->mutex);
    long observed = account->balance;
    sched_yield();
    account->balance = observed + amount;
    pthread_mutex_unlock(&account->mutex);
}
long read_balance(Account *account) {
    pthread_mutex_lock(&account->mutex);
    long value = account->balance;
    pthread_mutex_unlock(&account->mutex);
    return value;
}
''',
'range_window':'''#include "state.h"
#include <sched.h>
void set_window(Window *window, int lower, int upper) {
    pthread_mutex_lock(&window->mutex);
    window->lower = lower;
    sched_yield();
    window->upper = upper;
    pthread_mutex_unlock(&window->mutex);
}
void get_window(Window *window, int *lower, int *upper) {
    pthread_mutex_lock(&window->mutex);
    *lower = window->lower;
    sched_yield();
    *upper = window->upper;
    pthread_mutex_unlock(&window->mutex);
}
'''})


def save(path,value):Path(path).write_text(json.dumps(value,indent=2),encoding='utf-8')


async def main():
    load_env_file(ROOT/'.env');os.environ['AGENTKERNEL_SANDBOX_IMAGE']='agentkernel-clang:20261003122908'
    out=ROOT/'reports/adaptive-v2'/('holdout-validation-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True,exist_ok=False)
    records=[]
    for case in json.loads((DATA/'manifest.json').read_text())['cases']:
        name=case['id'];folder=out/name;folder.mkdir()
        task=ConcurrencyTask.model_validate({**json.loads((DATA/name/'task.json').read_text()),'workspace':DATA/name})
        campaign=JournalCampaign(folder)
        if hashlib.sha256((task.workspace/'solution.c').read_bytes()).hexdigest()!=case['source_sha256']:
            raise ValueError('Frozen holdout changed')
        print('Calibrating',name,flush=True)
        async with NebiusSandboxBackend() as box:
            await box.upload_project(task.workspace,task.source_files+task.support_files)
            build=await CCompiler().compile(task,box);save(folder/'original-build.json',build.model_dump(mode='json'))
            if not build.success:raise ValueError('Original does not compile')
            negative=await campaign.run(task,box,runs=3)
            save(folder/'original-stress.json',negative.model_dump(mode='json'))
            if negative.failed_runs!=3:raise ValueError('Broken original did not reliably trigger the oracle')
            instrumented=instrumented_task(task)
            instrumented.build_command[0]='clang'
            checked=await CCompiler().compile(instrumented,box,SanitizerConfig().flags)
            if not checked.success:raise ValueError('TSan calibration build unavailable')
            races=await campaign.run(instrumented,box,runs=3)
            save(folder/'original-tsan.json',races.model_dump(mode='json'))
            if races.infrastructure_failures:raise ValueError('Negative TSan control infrastructure failed')
            if case.get('negative_control')=='deadlock':
                if races.failed_runs!=3:raise ValueError('Deadlock control did not fail all TSan runs')
            elif not any(r.sanitizer_detected for r in races.runs):raise ValueError('Race control not detected by TSan')
        reference=folder/'reference';reference.mkdir()
        (reference/'solution.c').write_text(REFERENCES[name],encoding='utf-8',newline='')
        for filename in task.support_files:(reference/filename).write_bytes((task.workspace/filename).read_bytes())
        ref_task=task.model_copy(update={'workspace':reference})
        async with NebiusSandboxBackend() as box:
            await box.upload_project(reference,task.source_files+task.support_files)
            verified=await ConcurrencyVerifier(campaigns=campaign).verify_workspace(ref_task,box)
            save(folder/'reference-verification.json',verified.model_dump(mode='json'))
            require_verified(verified.model_dump(mode='json'),task.verification_config.model_dump())
        records.append({'case':name,'broken_rejected':True,'reference_verified':True,'model_calls':0})
        save(out/'results.json',records)
        print('Reference verified:',name,flush=True)
    save(out/'ready.json',{'cases':records,'origin':'manual verifier calibration, not model repair success','test_targets_in_training':False})
    print('Calibration complete:',out,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,default=DATA)
    DATA=parser.parse_args().data.resolve()
    asyncio.run(main())
