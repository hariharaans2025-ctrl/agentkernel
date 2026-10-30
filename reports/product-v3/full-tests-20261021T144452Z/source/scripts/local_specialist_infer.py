"""Bounded local weight inference over stdin JSON; never executes candidate programs."""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('TOKENIZERS_PARALLELISM','false')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-root',type=Path,default=ROOT/'models/adaptive-specialist-v1')
    parser.add_argument('--base',action='store_true')
    args=parser.parse_args()
    request=json.loads(sys.stdin.read(200000))
    if not isinstance(request.get('messages'),list) or not 1<=request.get('max_tokens',0)<=2048:
        raise ValueError('Invalid bounded inference input')
    from transformers import AutoModelForCausalLM,AutoTokenizer
    import torch
    from peft import PeftModel
    meta=json.loads((args.model_root/'training.json').read_text())
    if meta['status']!='trained':raise ValueError('Adapter is not trained')
    if hashlib.sha256((args.model_root/'adapter/adapter_model.safetensors').read_bytes()).hexdigest()!=meta['adapter_sha256']:
        raise ValueError('Adapter changed after training')
    if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
    started=time.perf_counter()
    base_path=(args.model_root/meta.get('base_path','base').replace('\\', '/')).resolve()
    if not base_path.is_relative_to((ROOT/'models').resolve()):raise ValueError('Base model path escaped the project')
    tokenizer=AutoTokenizer.from_pretrained(base_path,local_files_only=True,trust_remote_code=False)
    encoded=tokenizer.apply_chat_template(request['messages'],tokenize=True,add_generation_prompt=True,
        return_dict=True,return_tensors='pt').to('cuda')
    count=encoded['input_ids'].shape[-1]
    if count+request['max_tokens']>8192:raise ValueError('Specialist context cap exceeded; no truncation')
    model=AutoModelForCausalLM.from_pretrained(base_path,local_files_only=True,trust_remote_code=False,
        dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda')
    if not args.base:model=PeftModel.from_pretrained(model,args.model_root/'adapter',local_files_only=True)
    model.eval();torch.cuda.synchronize();generation_started=time.perf_counter()
    with torch.inference_mode():
        output=model.generate(**encoded,max_new_tokens=request['max_tokens'],do_sample=False,
            pad_token_id=tokenizer.eos_token_id,use_cache=True)
    torch.cuda.synchronize()
    generated=output[0,count:];terminated=int(generated[-1])==tokenizer.eos_token_id
    result={'text':tokenizer.decode(generated,skip_special_tokens=True),'input_tokens':count,'output_tokens':len(generated),
        'finish_reason':'stop' if terminated else 'length','generation_ms':(time.perf_counter()-generation_started)*1000,
        'latency_ms':(time.perf_counter()-started)*1000,'model':meta['base_model']+(' [base]' if args.base else ' + AgentKernel LoRA'),
        'base_revision':meta['base_revision'],'adapter_sha256':None if args.base else meta['adapter_sha256'],
        'cost_usd':0,'cost_basis':'No hosted inference charge; local electricity not measured.'}
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
