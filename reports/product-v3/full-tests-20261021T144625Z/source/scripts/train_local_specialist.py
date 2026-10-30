"""Real CUDA LoRA SFT. Loss is calculated only on assistant targets, never test data."""
import argparse
import hashlib
import json
import math
import os
import random
import shutil
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
os.environ.setdefault('TOKENIZERS_PARALLELISM','false')


def write(path,data):
    Path(path).write_text(json.dumps(data,indent=2),encoding='utf-8')


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',type=Path,default=ROOT/'datasets/adaptive-v2/pilot-v1')
    parser.add_argument('--out',type=Path,default=ROOT/'models/adaptive-specialist-v1')
    parser.add_argument('--epochs',type=int,default=8)
    parser.add_argument('--resume-preflight',action='store_true')
    parser.add_argument('--base-cache',type=Path)
    args=parser.parse_args()
    import torch
    import torch.nn.functional as F
    from huggingface_hub import HfApi,snapshot_download
    from transformers import AutoModelForCausalLM,AutoTokenizer
    from peft import LoraConfig,get_peft_model,TaskType
    if not torch.cuda.is_available(): raise RuntimeError('CUDA is required for this training configuration')
    if not 1<=args.epochs<=20: raise ValueError('Unsupported epoch bound')
    args.out.mkdir(parents=True,exist_ok=args.resume_preflight)
    if (args.out/'adapter').exists() or (args.out/'training.json').exists():
        raise ValueError('Preserve existing training checkpoints; use a new output directory')
    manifest=json.loads((args.dataset/'manifest.json').read_text())
    for name,expected in manifest['file_sha256'].items():
        if sha(args.dataset/name)!=expected: raise ValueError('Frozen training data changed')
    started=time.perf_counter()
    seed=42;random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
    model_id=manifest['base_model']
    revision=HfApi().model_info(model_id).sha
    write(args.out/'started.json',{'model':model_id,'revision':revision,'dataset':str(args.dataset),
        'dataset_manifest_sha256':sha(args.dataset/'manifest.json'),'seed':seed,'epochs':args.epochs,
        'test_data_loaded':False,'paid_training_job':False,'gpu':torch.cuda.get_device_name(0)})
    print('Downloading pinned base model:',model_id,revision,flush=True)
    base_path=args.base_cache.resolve() if args.base_cache else args.out/'base'
    if args.base_cache:
        provenance=json.loads((base_path.parent/'training.json').read_text(encoding='utf-8'))
        if provenance['base_model']!=model_id or provenance['base_revision']!=revision:
            raise ValueError('Cached base does not match the pinned model revision')
    if not args.base_cache:
        snapshot_download(model_id,revision=revision,local_dir=base_path,
            allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken'])
    tokenizer=AutoTokenizer.from_pretrained(base_path,local_files_only=True,trust_remote_code=False)
    tokenizer.pad_token=tokenizer.eos_token
    splits={}
    for split in ('train','validation'):
        samples=[]
        for line in (args.dataset/(split+'.jsonl')).read_text().splitlines():
            row=json.loads(line)
            prefix=tokenizer.apply_chat_template(row['messages'][:-1],tokenize=True,add_generation_prompt=True,return_dict=False)
            full=tokenizer.apply_chat_template(row['messages'],tokenize=True,add_generation_prompt=False,return_dict=False)
            if full[:len(prefix)]!=prefix: raise ValueError('Chat template prefix mismatch')
            if len(full)>8192: raise ValueError('Training example exceeds 8192 tokens; no silent truncation')
            samples.append({'id':row['id'],'ids':full,'prefix':len(prefix)})
        splits[split]=samples
    write(args.out/'sequence-lengths.json',{k:[{'id':s['id'],'total_tokens':len(s['ids']),
        'target_tokens':len(s['ids'])-s['prefix']} for s in v] for k,v in splits.items()})
    print('Sequence lengths:',{k:[len(s['ids']) for s in v] for k,v in splits.items()},flush=True)
    base=AutoModelForCausalLM.from_pretrained(base_path,local_files_only=True,trust_remote_code=False,
        dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda')
    base.config.use_cache=False
    model=get_peft_model(base,LoraConfig(task_type=TaskType.CAUSAL_LM,r=16,lora_alpha=32,lora_dropout=.05,
        target_modules=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj'],bias='none'))
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    model.enable_input_require_grads()
    params=[p for p in model.parameters() if p.requires_grad]
    counts={'trainable_parameters':sum(p.numel() for p in params),'total_parameters':sum(p.numel() for p in model.parameters())}
    print('Training LoRA parameters:',counts,flush=True)
    optimizer=torch.optim.AdamW(params,lr=3e-4,weight_decay=.01)
    history=[];best=math.inf;best_epoch=None
    def loss(sample):
        ids=torch.tensor([sample['ids']],device='cuda',dtype=torch.long)
        # Avoid allocating vocabulary logits for thousands of masked prompt tokens.
        hidden=model.base_model.model.model(input_ids=ids,use_cache=False,return_dict=True).last_hidden_state
        begin=sample['prefix']-1
        target=ids[:,begin+1:]
        logits=model.get_output_embeddings()(hidden[:,begin:-1,:])
        return F.cross_entropy(logits.reshape(-1,logits.shape[-1]).float(),target.reshape(-1))
    model.eval()
    with torch.no_grad(): initial=sum(loss(s).item() for s in splits['validation'])/len(splits['validation'])
    write(args.out/'initial-validation.json',{'assistant_token_loss':initial})
    for epoch in range(1,args.epochs+1):
        model.train();order=list(splits['train']);random.Random(seed+epoch).shuffle(order);total=0
        for sample in order:
            optimizer.zero_grad(set_to_none=True)
            value=loss(sample)
            if not torch.isfinite(value):raise RuntimeError('Non-finite training loss')
            value.backward();torch.nn.utils.clip_grad_norm_(params,1.0);optimizer.step()
            total+=value.item()
        model.eval()
        with torch.no_grad(): validation=sum(loss(s).item() for s in splits['validation'])/len(splits['validation'])
        row={'epoch':epoch,'train_assistant_loss':total/len(order),'validation_assistant_loss':validation}
        history.append(row);write(args.out/'loss-history.json',history);print(row,flush=True)
        if validation<best:
            best=validation;best_epoch=epoch
            model.save_pretrained(args.out/'adapter',safe_serialization=True)
            tokenizer.save_pretrained(args.out/'adapter')
    adapter=args.out/'adapter/adapter_model.safetensors'
    write(args.out/'training.json',{'schema_version':1,'status':'trained','training_kind':'LoRA supervised fine-tuning',
        'base_model':model_id,'base_revision':revision,'adapter_path':'adapter','base_path':os.path.relpath(base_path,args.out),
        'output_format':manifest.get('output_format','json_files'),
        'adapter_sha256':sha(adapter),'selected_epoch':best_epoch,'selection_basis':'development validation only',
        'initial_validation_loss':initial,'best_validation_loss':best,'epochs_completed':args.epochs,
        **counts,'training_seconds':time.perf_counter()-started,'max_gpu_allocated_bytes':torch.cuda.max_memory_allocated(),
        'gpu':torch.cuda.get_device_name(0),'torch':torch.__version__,'cuda':torch.version.cuda,
        'dataset_manifest_sha256':sha(args.dataset/'manifest.json'),'test_data_loaded':False,'hosted_training_cost_usd':0,
        'local_electricity_cost_measured':False,'promotion':'Every output still requires strict independent verification.'})
    print('Training complete. Adapter:',adapter,flush=True)


if __name__=='__main__': main()
