"""Freeze a compact, verified SFT dataset and separate new evaluation programs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'datasets/verified-repairs/20261011T050956Z'
OUT = ROOT / 'datasets/adaptive-v2/pilot-v1'
SPECIALIST_SYSTEM = ('Repair C/pthreads synchronization while preserving all original work, '
    'scheduling hooks, interfaces and protected tests. Return ONLY a JSON object with one key '
    '"files": an object mapping each editable filename to its complete corrected source. '
    'Do not include Markdown, explanations, commands, tests, or new files.')


def prompt(context):
    return [{'role': 'system', 'content': SPECIALIST_SYSTEM}, {'role': 'user', 'content': json.dumps({
        'task': context.get('original_task', context.get('task', 'Repair the concurrency bug.')),
        'editable_files': list(context.get('editable_files', context['sources'])),
        'sources': context['sources'], 'headers': context.get('headers', {}),
        'requirements': context.get('requirements', []),
    }, ensure_ascii=False)}]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    metadata = json.loads((SOURCE/'manifest.json').read_text())
    records = []
    for split in ('train', 'validation'):
        entries = [e for e in metadata['examples'] if e['split'] == split]
        rows = [json.loads(s) for s in (SOURCE/(split+'.jsonl')).read_text().splitlines()]
        result = []
        for row, entry in zip(rows, entries, strict=True):
            v = entry['verification']
            if not (v['passed'] and v['passed_runs'] == v['total_runs'] == 100 and not v['false_fix']):
                raise ValueError('Training target lacks its recorded verification')
            ctx = json.loads(row['messages'][1]['content'].rsplit('UNTRUSTED EVIDENCE:\n', 1)[1])
            original = {n: ctx['sources'][n] for n in ctx['editable_files']}
            if any(hashlib.sha256(s.encode()).hexdigest() != entry['original_sha256'][n] for n,s in original.items()):
                raise ValueError('Original source hash mismatch')
            candidate = dict(original)
            proposal = json.loads(row['messages'][2]['content'])
            for edit in proposal['edits']:
                if original[edit['file']].count(edit['search']) != 1: raise ValueError('Target edit is ambiguous')
                candidate[edit['file']] = candidate[edit['file']].replace(edit['search'],edit['replacement'],1)
            if any(hashlib.sha256(s.encode()).hexdigest() != entry['target_sha256'][n] for n,s in candidate.items()):
                raise ValueError('Training target hash mismatch')
            compact = {'original_task': ctx['original_task'], 'editable_files': list(original), 'sources': original,
                'headers': {n:s for n,s in ctx['sources'].items() if n.endswith('.h')},
                'requirements': [check['name'] for check in ctx.get('verification_requirements', {}).get('semantic_checks', [])]}
            messages = prompt(compact) + [{'role':'assistant','content':json.dumps({'files':candidate},ensure_ascii=False,separators=(',',':'))}]
            result.append({'id':entry['id'],'messages':messages})
            records.append({'id':entry['id'],'split':split,'source_hashes':entry['original_sha256'],
                'target_hashes':entry['target_sha256'],'verification_provenance':entry['provenance']})
        (OUT/(split+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in result),encoding='utf-8')
    # Test implementations and oracles are stored separately; no test answers enter SFT.
    manifest = {'schema_version':1,'base_model':'Qwen/Qwen2.5-Coder-0.5B-Instruct','train_programs':6,
        'validation_programs':1,'split_unit':'whole original program','records':records,
        'source_dataset_sha256':digest(SOURCE/'manifest.json'),'training_files':['train.jsonl','validation.jsonl'],
        'test_source':'datasets/adaptive-v2/holdout-v1','test_targets_in_training':False,
        'limitations':['Small synthetic pilot; not production generalization evidence.',
            'Historical training examples retain their original verification contracts; held-out evaluation requires TSan.']}
    manifest['file_sha256']={name:digest(OUT/name) for name in manifest['training_files']}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Frozen 6 verified training programs and 1 development-validation program:',OUT)


if __name__=='__main__': main()
