"""Run in Nebius: Clang indexing and public-tokenizer counts, never inference."""
import hashlib
import json
from pathlib import Path
import subprocess
from time import perf_counter
from urllib.request import urlopen

from agentkernel.repository.context import index_functions, prepare_context
from agentkernel.concurrency.repair.prompts import repair_prompt, SYSTEM_PROMPT
from agentkernel.providers.nebius_token_factory import BOUNDARY

started = perf_counter()
payload = json.loads(Path('context-input.json').read_text())
contract = payload['contract']
sources = {name: Path(name).read_text(encoding='utf-8') for name in payload['files']}
index = []
for filename in sources:
    if not filename.endswith('.c'): continue
    parsed = subprocess.run(['clang', '-Iinclude', '-Xclang', '-ast-dump=json', '-fsyntax-only', filename], capture_output=True, text=True, timeout=20)
    if parsed.returncode: raise ValueError('Clang indexing failed: ' + filename)
    index.extend(index_functions(json.loads(parsed.stdout), filename, sources[filename]))
full, compact, audit = prepare_context(sources, index, payload['seeds'], contract['source_files'],
    payload['campaign'], payload['diagnostics'], payload['stacks'], contract)
preparation_ms = (perf_counter()-started)*1000
marker = '\nUNTRUSTED EVIDENCE:\n'
prefix = repair_prompt({}).rsplit(marker, 1)[0] + marker
prompts = {'full': repair_prompt(full),
           'minified_full': prefix + json.dumps(full, ensure_ascii=False, separators=(',', ':')),
           'selected_grouped': prefix + json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}
if any(p.split(marker, 1)[0] != prompts['full'].split(marker, 1)[0] for p in prompts.values()):
    raise ValueError('Repair instructions changed')
repo = 'nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16'
def fetch(url, limit):
    with urlopen(url, timeout=30) as response:
        data = response.read(limit + 1)
        if len(data) > limit: raise ValueError('Tokenizer asset exceeds limit')
        return data
metadata = json.loads(fetch('https://huggingface.co/api/models/' + repo, 2000000))
revision = metadata['sha']
assets = Path('public-tokenizer')
assets.mkdir(exist_ok=False)
asset_hashes = {}
available = {x['rfilename'] for x in metadata['siblings']}
for name in ['tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'chat_template.jinja', 'config.json']:
    if name not in available: continue
    data = fetch(f'https://huggingface.co/{repo}/resolve/{revision}/{name}', 40000000)
    (assets / name).write_bytes(data)
    asset_hashes[name] = hashlib.sha256(data).hexdigest()
from transformers import AutoTokenizer
import transformers
tokenizer = AutoTokenizer.from_pretrained(str(assets), local_files_only=True, trust_remote_code=False)
measurements = {}
for arm, prompt in prompts.items():
    messages = [{'role':'system','content':BOUNDARY + '\n' + SYSTEM_PROMPT}, {'role':'user','content':prompt}]
    tick = perf_counter()
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
    measurements[arm] = {'input_tokens':len(tokens), 'message_content_bytes':sum(len(m['content'].encode()) for m in messages),
                          'rendered_sha256':hashlib.sha256(rendered.encode()).hexdigest(),
                          'tokenization_ms':(perf_counter()-tick)*1000, 'messages':messages}
audit['repair_instructions_unchanged'] = True
result = {'model_calls':0, 'provider_billed_tokens':None,
          'measurement_scope':'NVIDIA public Super tokenizer plus chat template; Nebius equivalence unverified',
          'tokenizer':{'repository':repo,'revision':revision,'asset_sha256':asset_hashes,'transformers_version':transformers.__version__,
                       'enable_thinking':False,'add_generation_prompt':True,'trust_remote_code':False},
          'preparation_ms':preparation_ms, 'source_index':index,'audit':audit,'measurements':measurements,
          'compact_context':compact,'full_context':full}
Path('context-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({arm: {k:v for k,v in row.items() if k!='messages'} for arm,row in measurements.items()}, indent=2))
