"""Remote diagnostic tests and saved-candidate analysis; no model calls."""
import asyncio
from datetime import datetime, timezone
import json
import os

from repository_live_ab import ROOT, read, save, digest, check_hashes, CONTEXT
from agentkernel.config import load_env_file
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend

REMOTE = '''import json, subprocess
from pathlib import Path
from agentkernel.repository.barrier_diagnostics import analyze_barriers
sources = json.loads(Path('variants.json').read_text())
results = {}
for name, source in sources.items():
    Path('src/queue.c').write_text(source)
    parsed = subprocess.run(['clang','-Iinclude','-Xclang','-ast-dump=json','-fsyntax-only','src/queue.c'], capture_output=True, text=True, timeout=20)
    if parsed.returncode: raise RuntimeError(parsed.stderr)
    results[name] = analyze_barriers(json.loads(parsed.stdout), 'src/queue.c', source)
assert len(results['original']['findings']) == 2
assert len(results['failed_full']['findings']) == 2
assert len(results['failed_compact']['findings']) == 2
assert not results['verified_manual']['findings']
assert all(f['possible_other_participant_acquisitions'] for f in results['failed_compact']['findings'])
Path('diagnostic-results.json').write_text(json.dumps(results, indent=2))
print(json.dumps({name:len(r['findings']) for name,r in results.items()}))
'''


async def main():
    previous = ROOT / 'reports/repository-manual-repair/20261009T110123Z'
    check_hashes(read(previous/'preserved-sha256.json'))
    ab = ROOT / 'reports/repository-live-ab/20261007T121122Z'
    variants = {'original':(ROOT/'examples/job-queue-service/src/queue.c').read_text(),
        'failed_full':read(ab/'full/candidate-sources.json')['src/queue.c'],
        'failed_compact':read(ab/'selected_grouped/candidate-sources.json')['src/queue.c'],
        'verified_manual':(previous/'repaired-project/src/queue.c').read_text()}
    out = ROOT/'reports/barrier-diagnostics'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True, exist_ok=False)
    print('Evidence: '+str(out), flush=True)
    protected = {p.relative_to(ROOT).as_posix():digest(p) for folder in ('src','examples','benchmarks','reports')
        for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents}
    save(out/'preserved-sha256.json', protected)
    save(out/'variants.json', variants)
    staging = out/'staging'
    staging.mkdir()
    load_env_file(ROOT/'.env')
    os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-project:20261004t054834z'
    try:
        async with NebiusSandboxBackend(temporary_parent=staging) as box:
            await box.upload_project(ROOT, ['src/agentkernel/repository/__init__.py',
                'src/agentkernel/repository/barrier_diagnostics.py','tests/test_barrier_diagnostics.py'])
            tests = await box.run_command(['python3','-m','pytest','-q','tests/test_barrier_diagnostics.py'],
                timeout=60, environment={'PYTHONPATH':'/workspace/src'})
            save(out/'tests.json', tests.model_dump())
            print(tests.stdout, flush=True)
            if tests.exit_code != 0 or tests.timed_out: raise RuntimeError('Diagnostic tests failed')
            await box.upload_project(ROOT/'examples/job-queue-service', ['src/queue.c','include/queue.h'])
            await box._upload({'/workspace/variants.json':json.dumps(variants).encode(),
                               '/workspace/analyze_variants.py':REMOTE.encode()})
            result = await box.run_command(['python3','analyze_variants.py'], timeout=60,
                                          environment={'PYTHONPATH':'/workspace/src'})
            save(out/'analysis-execution.json', result.model_dump())
            print(result.stdout, flush=True)
            if result.exit_code != 0 or result.timed_out: raise RuntimeError('Saved-candidate diagnostic gates failed')
            results = json.loads(await box.read_file('diagnostic-results.json'))
            save(out/'diagnostic-results.json', results)
        # New context only: old prompts/evidence are never rewritten. No repaired
        # candidate or known-good answer enters the next original-source prompt.
        compact = read(CONTEXT)['compact_context']
        compact['static_barrier_diagnostics'] = results['original']
        save(out/'repair-context.json', compact)
        save(out/'plan.json', {'model_calls':0,'tokens':0,'step':'barrier_diagnostic_validation',
             'source_context_sha256':digest(CONTEXT),'diagnostic_context_sha256':digest(out/'repair-context.json'),
             'integration':'Additive diagnostic field in a new experimental repair context; frozen runtime and prompts unchanged.'})
        lines = ['# Barrier diagnostic validation', '',
                 'Eight Clang-based regression tests passed in Nebius Sandbox. Zero model calls and inference tokens.', '',
                 '| Source | Barrier-with-held-mutex warnings |','|---|---:|']
        for name,r in results.items(): lines.append(f"| {name} | {len(r['findings'])} |")
        lines += ['', 'Source locations and deterministic fingerprints are in diagnostic-results.json.',
            'repair-context.json extends the prior compact context using only the original buggy source analysis. No known-good answer or failed candidate source is added.',
            'The warnings are intraprocedural possible-path evidence. Aliasing, actual concurrent participants, lock return values and branch feasibility are not proved. Unsupported constructs are listed as coverage gaps. No warnings is not a safety claim.',
            'This step adds diagnostics, not a verified model repair. The separately verified manual repair remains 100/100 stress plus semantics and 3/3 TSan; no native workload was rerun here.',
            'Next: a new bounded Super experiment with this context, unchanged output cap and full verification. No inference was started by this validation.']
        (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    finally:
        changed = [name for name,value in protected.items() if digest(ROOT/name) != value]
        save(out/'integrity.json', {'unchanged':not changed, 'protected_files':len(protected),'changed':changed})
        if changed: raise RuntimeError('Preserved files changed')


if __name__ == '__main__': asyncio.run(main())
