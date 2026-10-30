"""Build a small evidence-backed seed corpus; never relabel old data as unseen."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from repository_live_ab import ROOT,read,save,digest
from agentkernel.repository.learning import require_verified
from agentkernel.concurrency.repair.prompts import SYSTEM_PROMPT,repair_prompt
from agentkernel.concurrency.repair.patch_parser import parse_repair
from agentkernel.concurrency.repair.patch_applier import UnifiedDiffApplier


def main():
    out=ROOT/'datasets/verified-repairs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    accepted,excluded={},[]
    paths=sorted((ROOT/'reports/final-benchmark-jobs').rglob('events.jsonl'))+sorted((ROOT/'reports/continuation-20261004T104857Z').glob('*.jsonl'))
    for path in paths:
        for line in path.read_text().splitlines():
            event=json.loads(line)
            if event.get('event_type')!='concurrency_job': continue
            summary=event['summary']; name=summary['task']
            for attempt in summary.get('metadata',{}).get('attempt_details',[]):
                evidence=attempt.get('verification_evidence',{}); verification=evidence.get('verification',{})
                config=summary['metadata']['verification_configuration']
                try: require_verified(verification,config)
                except ValueError:
                    excluded.append({'fixture':name,'reason':'not fully verified under original contract','evidence':str(path.relative_to(ROOT))})
                    continue
                if name in accepted: continue
                fixture=ROOT/'benchmarks'/name
                task=read(fixture/'task.json')
                originals={n:(fixture/n).read_bytes().decode() for n in task['source_files']}
                for n,s in originals.items():
                    if hashlib.sha256(s.encode()).hexdigest()!=summary['metadata']['source_sha256'][n]: raise ValueError('Source provenance mismatch')
                try:
                    proposal=parse_repair(attempt['output_text'],originals)
                except ValueError:
                    excluded.append({'fixture':name,'reason':'saved response cannot replay against original source','evidence':str(path.relative_to(ROOT))})
                    continue
                if hashlib.sha256(proposal.patch.encode()).hexdigest()!=evidence['patch_hash']:
                    excluded.append({'fixture':name,'reason':'canonical patch hash differs from verified patch','evidence':str(path.relative_to(ROOT))})
                    continue
                candidate=evidence['candidate_sources']
                accepted[name]=(task,originals,candidate,config,verification,{'file':str(path.relative_to(ROOT)),'sha256':digest(path),'patch_sha256':evidence['patch_hash']})
    manual=ROOT/'reports/repository-manual-repair/20261009T110123Z'
    plan=read(ROOT/'reports/repository-onboarding/20261007T110957Z/plan/plan.json')
    config=plan['contract']['verification'];v=read(manual/'verification.json');require_verified(v,config)
    accepted['job_queue']=(plan['task'],{'src/queue.c':(ROOT/'examples/job-queue-service/src/queue.c').read_text()},
        {'src/queue.c':(manual/'repaired-project/src/queue.c').read_text()},config,v,
        {'file':str((manual/'verification.json').relative_to(ROOT)),'sha256':digest(manual/'verification.json'),'origin':'manual'})
    metadata=[];splits={'train':[],'validation':[]}
    for name,(task,original,candidate,config,v,provenance) in accepted.items():
        # Conservative grouping: all old race fixtures stay together in train.
        # One distinct old deadlock fixture is development validation, never test.
        split='validation' if name=='deadlock_005' else 'train'
        fixture=ROOT/'examples/job-queue-service' if name=='job_queue' else ROOT/'benchmarks'/name
        support={n:(fixture/n).read_text() for n in task.get('support_files',[])}
        context={'original_task':task.get('metadata',{}).get('fixture_description','Repair the concurrency bug without weakening the workload.'),
            'editable_files':list(original),'sources':{**original,**support},'verification_requirements':config}
        target={'diagnosis':'Synchronization repair validated by execution.', 'root_cause':'Shared-state synchronization or lock dependencies require repair.',
            'confidence':0.5,'reasoning_summary':'','expected_effect':'Preserve required workload invariants and pass mandatory verification.',
            'risk_notes':['Finite verification is not a proof of correctness.'],
            'edits':[{'file':n,'search':s,'replacement':candidate[n]} for n,s in original.items() if candidate[n]!=s]}
        canonical=parse_repair(json.dumps(target),original)
        staging=out/'audit'/name;staging.mkdir(parents=True)
        for n,s in original.items():
            p=staging/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s,encoding='utf-8',newline='')
        applied=UnifiedDiffApplier().apply(staging,canonical.patch,list(original))
        if not applied.success or any((staging/n).read_bytes().decode()!=candidate[n] for n in original): raise ValueError('Target mismatch')
        splits[split].append({'messages':[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':repair_prompt(context)},
                                          {'role':'assistant','content':json.dumps(target,separators=(',',':'))}]})
        metadata.append({'id':name,'split':split,'group':name,'provenance':provenance,'verification':v,
            'original_sha256':{n:hashlib.sha256(s.encode()).hexdigest() for n,s in original.items()},
            'target_sha256':{n:hashlib.sha256(s.encode()).hexdigest() for n,s in candidate.items()}})
    for split,rows in splits.items():
        (out/(split+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
    save(out/'manifest.json',{'examples':metadata,'excluded_attempts':excluded,'train_count':len(splits['train']),
        'validation_count':len(splits['validation']),'test_count':0,'status':'seed corpus; unseen evaluation built separately',
        'budget_usd':10,'training_submitted':False,'deduplication':'One target per original fixture; variants from a fixture never cross splits.',
        'limitations':['Small synthetic seed corpus, not a production training dataset.','All old fixtures are development-seen; none are labeled unseen.',
            'Deadlock targets preserve their original contract, which did not require TSan. Race and job-queue targets require TSan.',
            'Teacher explanations are replaced with neutral descriptions to avoid training unsupported causal claims.']})
    save(out/'file-sha256.json',{p.relative_to(out).as_posix():digest(p) for p in out.rglob('*') if p.is_file()})
    print(json.dumps({'dataset':str(out),'train':len(splits['train']),'validation':len(splits['validation'])}))


if __name__=='__main__':main()
