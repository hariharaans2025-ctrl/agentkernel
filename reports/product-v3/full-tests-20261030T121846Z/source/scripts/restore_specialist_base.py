"""Download the pinned base weights for the optional adapter; never trains or calls inference."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    from huggingface_hub import snapshot_download
    metadata = json.loads((ROOT / 'models/adaptive-specialist-v3/training.json').read_text())
    target = ROOT / 'models/adaptive-specialist-v2/base'
    snapshot_download(repo_id=metadata['base_model'], revision=metadata['base_revision'],
                      local_dir=target, allow_patterns=['*.json', '*.safetensors', '*.txt', '*.model', '*.jinja', 'LICENSE', 'README.md'])
    print('Pinned base model downloaded. No training or inference was started.')
