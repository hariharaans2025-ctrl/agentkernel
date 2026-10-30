"""Package the verified pilot and holdout without submitting paid jobs."""
import hashlib
import json
from datetime import datetime,timezone
from repository_live_ab import ROOT,read,save,digest
from agentkernel.concurrency.repair.prompts import SYSTEM_PROMPT,repair_prompt


def main():
    train=ROOT/'datasets/verified-repairs/20261011T050956Z'
    evidence=ROOT/'reports/unseen-dataset-validation/20261011T051103Z'
    ready=read(evidence/'ready.json')
    if len(ready['cases'])!=2 or not all(r['verified_reference'] for r in ready['cases']): raise ValueError('Holdout reference not ready')
    out=ROOT/'datasets/learning-pilot'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    for n in ('train.jsonl','validation.jsonl'):
        (out/n).write_bytes((train/n).read_bytes())
    tests=[]
    for case in ready['cases']:
        name=case['id'];task=read(evidence/name/'task.json');base=ROOT/'datasets/unseen-v1'/name
        sources={n:(base/n).read_text() for n in task['source_files']+task['support_files']}
        context={'original_task':'Repair the concurrency bug while preserving all protected workload invariants.',
                 'editable_files':task['source_files'],'sources':sources,'verification_requirements':task['verification_config']}
        tests.append({'id':name,'task':task,'messages':[{'role':'system','content':SYSTEM_PROMPT},
            {'role':'user','content':repair_prompt(context)}],
            'source_sha256':{n:digest(base/n) for n in sources},'reference_evidence':str((evidence/name/'reference/verification.json').relative_to(ROOT))})
    # No reference patch/target is placed in inference messages or upload files.
    (out/'test.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in tests),encoding='utf-8')
    original_hashes={h for row in read(train/'manifest.json')['examples'] for h in row['original_sha256'].values()}
    if any(row['source_sha256']['solution.c'] in original_hashes for row in tests): raise ValueError('Train/test overlap')
    proposed={'model':'Qwen/Qwen3-30B-A3B-Instruct-2507','suffix':'agentkernel-verified-pilot',
        'hyperparameters':{'batch_size':1,'learning_rate':0.00001,'n_epochs':1,'lora':True,
                          'lora_r':8,'lora_alpha':8,'lora_dropout':0.05,'packing':True,'context_length':8192},'seed':42}
    save(out/'training-plan.json',{'request_template':proposed,'upload_only':['train.jsonl','validation.jsonl'],
        'never_upload_for_training':['test.jsonl','reference.patch'],'max_pilot_spend_usd':10,
        'submitted':False,'job_id':None,'blocking_reason':'No verified training + dedicated deployment cost bound within $10. Training tokenizer limits also require preflight before upload.'})
    save(out/'evaluation-protocol.json',{'arms':['base','fine_tuned'],'pairs':[r['id'] for r in tests],
        'attempts_per_case_per_arm':1,'max_output_tokens':2048,'temperature':0,'correction_calls':0,'escalation':False,
        'execution_backend':'nebius','image':'agentkernel-clang:20261003122908','mandatory_verifier':True,
        'required_checks':['fresh build','protected original tests','100 stress executions','semantic oracle','3 TSan executions'],
        'holdout_policy':'Freeze before training; never use test answers or test outcomes for checkpoint selection. Changes after inspection require a new unseen test set.',
        'metrics':{'verified_repairs':'count of complete verifier passes','false_fixes':'applied candidates rejected by real program verification, excluding infrastructure interruptions',
            'tokens_per_verified_repair':'all evaluation input+output tokens, including failed attempts, divided by verified repairs; null when zero or usage missing',
            'latency':'record inference, verification and end-to-end separately; report each case and median; setup/training/deployment separate',
            'unknown':'report separately, never convert infrastructure errors into successes or program failures'},
        'promotion':'A tuned response never bypasses strict patch application, protected-file checks or real execution verification.'})
    save(out/'evaluation-results.json',{'status':'NOT_RUN','reason':'Training/deployment budget feasibility unresolved',
        'base':None,'fine_tuned':None,'verified_repairs':None,'false_fixes':None,'tokens_per_verified_repair':None,'latency':None})
    save(out/'manifest.json',{'training_source':str(train.relative_to(ROOT)),'reference_validation':str(evidence.relative_to(ROOT)),
        'train':6,'development_validation':1,'unseen_test':2,'test_target_model_exposures':0,
        'test_original_source_exact_overlap':False,'split_unit':'whole original program; no variants split across train/test',
        'limitations':['Only 6 training programs and 2 held-out programs: pipeline pilot, no robust generalization claim.',
            'Unseen means not used in this project training/target-model requests, not guaranteed absent from base pretraining.',
            'No automated semantic-clone proof; held-out tasks use newly authored rwlock-mode and multi-waiter notification structures.',
            'Original deadlock training labels retain their historical non-TSan contract; all held-out evaluations require TSan.']})
    (out/'README.md').write_text('''# Verified repair learning pilot

Prepared: 6 deduplicated verified training targets, 1 development-validation target,
and 2 newly authored held-out programs. Every training target is linked to its
original source and recorded verification evidence. Reconstructed edit outputs
were applied locally as text and checked against the saved verified candidate.
Faulty or unreplayable model attempts were excluded rather than trained as successes.

Both held-out reference repairs passed 100 stress executions, protected original
tests, semantic checks, and 3 TSan executions in Nebius Sandbox. References are
not included in inference messages or training upload files. These are verifier
calibration results, not model-repair results. No target-model evaluation has run.

The training corpus is a small seed pilot, not evidence that fine-tuning will help.
The proposed model is Qwen/Qwen3-30B-A3B-Instruct-2507, documented for LoRA and
present in the live catalog. Fine-tuning access returned HTTP 200.

Training is NOT submitted. The user authorized a US$10 pilot; current documentation
says tuned models deploy through dedicated endpoints. No bounded training-plus-
hosting quote was available, so no unpriced training or deployment job was started.
Before submission, obtain a quote or enforceable spending cap for training and
evaluation hosting, and measure sequences with the selected model's tokenizer.
Do not silently truncate long examples, increase the budget, or upload the test set.

Evaluation metrics remain null until real runs exist. Use evaluation-protocol.json
for matched base/tuned comparisons. Failed-attempt tokens count toward tokens per
verified repair. Zero verified repairs makes that metric undefined, not zero.
The verifier remains mandatory after training, regardless of model confidence.

Provider sources:
- https://docs.tokenfactory.nebius.com/post-training/models
- https://docs.tokenfactory.nebius.com/post-training/datasets
- https://docs.tokenfactory.nebius.com/post-training/how-to-fine-tune

Existing benchmark and prior evidence files are unchanged.
''',encoding='utf-8')
    save(out/'sha256.json',{p.relative_to(out).as_posix():digest(p) for p in out.iterdir() if p.is_file()})
    print(out)


if __name__=='__main__':main()
