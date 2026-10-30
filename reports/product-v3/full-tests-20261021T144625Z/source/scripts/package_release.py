"""Create local source, evidence, and adapter archives without secrets or runtime state."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile
from agentkernel.config import load_env_file

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', 'node_modules', '.venv', '.training-venv', '__pycache__', '.pytest_cache', '.sites-runtime', '.wrangler', '.next', '.vinext', 'dist', 'work', 'staging', 'evaluation-staging', 'verification-staging'}
TEXT_TYPES = {'.py', '.json', '.jsonl', '.md', '.txt', '.toml', '.yaml', '.yml', '.html', '.css', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.c', '.cpp', '.cc', '.h', '.hpp', '.patch', '.csv', '.xml', '.sql', '.ps1', '.cmd', '.sh', '.example', '.jinja'}


def eligible(path):
    relative = path.relative_to(ROOT)
    return (path.is_file() and not path.is_symlink() and not any(p in IGNORED or p.endswith('.egg-info') for p in relative.parts)
            and not (path.name.startswith('.env') and path.name != '.env.example')
            and path.suffix.lower() not in {'.key', '.pem', '.p12', '.pfx', '.pyc', '.log', '.lock'})


def files_under(folder):
    for current, directories, files in os.walk(ROOT / folder):
        directories[:] = [n for n in directories if n not in IGNORED and not n.endswith('.egg-info') and not (Path(current)/n).is_symlink()]
        for name in files:
            path = Path(current) / name
            if eligible(path):
                yield path


def pack(destination, paths, secrets):
    entries = []
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(set(paths)):
            data = path.read_bytes()
            if any(value in data for value in secrets):
                raise ValueError('Credential detected in a release input; no artifact is approved for sharing.')
            name = 'agentkernel/' + path.relative_to(ROOT).as_posix()
            archive.writestr(name, data)
            entries.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        archive.writestr('FILE-MANIFEST.json', json.dumps(entries, indent=2))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive verification failed')
        for entry in entries:
            if hashlib.sha256(archive.read(entry['path'])).hexdigest() != entry['sha256']:
                raise ValueError('Archive content hash mismatch')
    return {'file': destination.name, 'files': len(entries), 'bytes': destination.stat().st_size,
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    load_env_file(ROOT / '.env')
    secrets = [v.encode() for k, v in os.environ.items() if re.search(r'(API_KEY|TOKEN|SECRET|PASSWORD)', k) and len(v) >= 12]
    source = [p for folder in ('src', 'scripts', 'tests', 'benchmarks', 'datasets', 'examples', 'sites/agentkernel-console') for p in files_under(folder)
              if p.suffix in TEXT_TYPES or p.name in ('Makefile', '.gitignore', 'LICENSE', '.npmrc')]
    source += [p for p in ROOT.iterdir() if eligible(p) and (p.suffix in TEXT_TYPES or p.name == '.gitignore')]
    evidence = [p for p in files_under('reports') if p.suffix in TEXT_TYPES and p.name != 'state.json'
                and 'repositories' not in p.relative_to(ROOT).parts and 'checkouts' not in p.relative_to(ROOT).parts]
    adapter = list(files_under('models/adaptive-specialist-v3')) + [ROOT/'models/active-specialist.json']
    records = [pack(out/'AgentKernel-source.zip', source, secrets), pack(out/'AgentKernel-evidence.zip', evidence, secrets), pack(out/'AgentKernel-trained-adapter.zip', adapter, secrets)]
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(), 'private_site': 'https://agentkernel-control.abuzzleaf32.chatgpt.site/',
                'archives': records, 'validation': json.loads(args.validation.read_text()), 'credentials_included': False,
                'installed_dependencies_included': False, 'base_model_weights_included': False, 'historical_evidence_rewritten': False,
                'integrity': 'ZIP CRC plus SHA-256 checked for every archived file; active credential values excluded.'}
    (out/'release-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (out/'START_HERE.md').write_bytes((ROOT/'START_HERE.md').read_bytes())
    print(json.dumps({'folder': str(out), 'archives': records}, indent=2))


if __name__ == '__main__':
    main()
