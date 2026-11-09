"""Populate only the owned run's HF cache from the locked model revision."""
import importlib.metadata as metadata
import json
import os
from pathlib import Path
from huggingface_hub import snapshot_download

lock = json.loads(Path('/tests/model-lock.json').read_text())
cache = Path('/efs/feature-tests') / os.environ['TEST_RUN'] / 'hf' / 'hub'
cache.mkdir(parents=True, exist_ok=True)
path = Path(snapshot_download(repo_id=lock['model'], revision=lock['revision'],
    cache_dir=str(cache), max_workers=4,
    allow_patterns=['*.json', '*.safetensors', '*.jinja', '*.py', '*.txt', '*.model', '*.tiktoken', 'LICENSE']))
index_file = path / 'model.safetensors.index.json'
if index_file.is_file():
    index = json.loads(index_file.read_text())
    weights = sorted(set(index['weight_map'].values()))
else:
    weights = sorted(p.name for p in path.glob('*.safetensors'))
assert weights, 'No safetensors weights downloaded'
for name in weights:
    assert (path / name).is_file() and (path / name).stat().st_size > 0, name
print(json.dumps({'model': lock['model'], 'revision': lock['revision'],
                  'huggingface_hub': metadata.version('huggingface-hub'),
                  'snapshot_path': str(path), 'weight_files': len(weights),
                  'weight_bytes': sum((path / name).stat().st_size for name in weights)}))
