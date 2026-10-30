"""Controller: all tests/indexing/tokenization in Nebius; no inference calls."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from agentkernel.config import load_env_file
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend

ROOT = Path(__file__).resolve().parents[1]
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, value):
    with path.open('x', encoding='utf-8') as f: json.dump(value, f, indent=2)

async def main():
    out = ROOT / 'reports/repository-context' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    staging = out / 'staging'
    staging.mkdir()
    print('Evidence: ' + str(out), flush=True)
    diag = ROOT / 'reports/repository-diagnostics/20261007T114433Z'
    previous = read(diag / 'preserved-sha256.json')
    for name, value in previous.items():
        if sha(ROOT / name) != value: raise ValueError('Protected file changed: ' + name)
    before = {p.relative_to(ROOT).as_posix(): sha(p) for folder in ('src','benchmarks','examples','reports')
              for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out / 'preserved-sha256.json', before)
    plan = read(ROOT / 'reports/repository-onboarding/20261007T110957Z/plan/plan.json')
    example = ROOT / 'examples/job-queue-service'
    for name, info in plan['files'].items():
        if sha(example / name) != info['sha256']: raise ValueError('Example changed')
    input_data = {'contract':plan['contract'],'files':list(plan['files']),
                  'seeds':['queue_process_one','queue_inspect'],
                  'campaign':read(diag/'queue-campaign.json'), 'diagnostics':read(diag/'queue-diagnoses.json'),
                  'stacks':read(diag/'thread-stacks.json')}
    save(out / 'context-input.json', input_data)
    load_env_file(ROOT / '.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-project:20261004t054834z'
    result = None
    try:
        async with NebiusSandboxBackend(temporary_parent=staging) as box:
            files = ['src/agentkernel/repository/__init__.py','src/agentkernel/repository/context.py',
                     'tests/test_repository_context.py','scripts/prepare_context_remote.py']
            save(out/'implementation-sha256.json',{name:sha(ROOT/name) for name in files})
            await box.upload_project(ROOT, files)
            tests = await box.run_command(['python3','-m','pytest','-q','tests/test_repository_context.py'],timeout=60,
                                         environment={'PYTHONPATH':'/workspace/src'})
            save(out/'tests.json',tests.model_dump())
            print(tests.stdout,flush=True)
            if tests.exit_code != 0 or tests.timed_out: raise ValueError('Context tests failed')
            install = await box.run_command(['python3','-m','pip','install','transformers==4.57.1','jinja2==3.1.6'],timeout=110)
            save(out/'tokenizer-install.json',install.model_dump())
            if install.exit_code != 0 or install.timed_out: raise ValueError('Tokenizer dependency unavailable')
            await box.upload_project(example,list(plan['files']))
            await box._upload({'/workspace/context-input.json':json.dumps(input_data).encode()})
            preparation = await box.run_command(['python3','scripts/prepare_context_remote.py'], timeout=110,
                                               environment={'PYTHONPATH':'/workspace/src','HF_HOME':'/workspace/hf-cache'})
            save(out/'preparation.json',preparation.model_dump())
            print(preparation.stdout,flush=True)
            if preparation.exit_code != 0 or preparation.timed_out: raise ValueError('Context/tokenizer preparation failed')
            result = json.loads(await box.read_file('context-result.json'))
            save(out/'context-result.json',result)
    finally:
        changed = [name for name,value in before.items() if sha(ROOT/name) != value]
        save(out/'integrity.json',{'protected_files':len(before),'unchanged':not changed,'changed':changed})
        if changed: raise ValueError('Protected files changed')
    if result:
        measures = result['measurements']
        base = measures['full']['input_tokens']
        lines = ['# Step 3: context preparation', '',
                 'Synthetic queue example only. No inference calls or repair-quality claim.',
                 'Counts measured with the public NVIDIA Super tokenizer and chat template. These are not confirmed Nebius billing counts.', '',
                 '| Context | Input tokens | Reduction vs full |', '|---|---:|---:|']
        for arm,m in measures.items(): lines.append(f"| {arm} | {m['input_tokens']} | {100*(1-m['input_tokens']/base):.2f}% |")
        lines += ['', 'Retained: complete editable source, protected caller source and header, every execution outcome and metadata, every diagnostic, complete captured stacks, verification requirements and repair instructions.',
                  'Only identical execution outcomes/diagnostics are grouped. README and Makefile text omitted from selected context; explicit build argv remains.',
                  'Full/minified/grouped prompts are saved verbatim for a future bounded A/B repair experiment. This comparison is newly constructed, not a reconstruction of prior live benchmark prompts.',
                  'Clang indexes project function definitions, references (including function pointers) and members. Retrieval conservatively follows callers/references and includes all project headers and editable files.',
                  'No claim of generic C++ dependency completeness; this sample uses known include flags. Unresolved seeds/includes fail instead of silent truncation.',
                  f"Selected files: {', '.join(result['audit']['selected_files'])}.",
                  f"Clang indexing/context preparation: {result['preparation_ms']:.2f} ms in sandbox (single observation, excludes setup/download).",
                  f"Tokenizer: {result['tokenizer']['repository']} at {result['tokenizer']['revision']}.",
                  'No Nano/Ultra tokenizer counts, output tokens, inference latency or verified repair improvements measured. Frozen prompts and routing are unchanged.']
        (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(out/'REPORT.md',flush=True)

if __name__ == '__main__': asyncio.run(main())
