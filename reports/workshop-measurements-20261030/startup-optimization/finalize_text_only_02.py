"""Analyze a cleaned text-only pilot, verify MM removal and seal all evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[3]


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    assert run == ROOT / 'results/workshop-mx-startup-20261103-textonly02'
    cleanup = json.loads((run / 'cleanup-proof.json').read_text())
    assert cleanup['verified'] is True and cleanup['gpu_lease_absent'] is True
    assert not (ROOT / '.local/workshop-measurements-20261030.gpu-lease').exists()
    state = json.loads((run / 'state.json').read_text())
    frozen = json.loads((run / 'spec.json').read_text())
    assert state['model_lock'] == frozen['model_lock']
    assert state['checks']['text-only-pilot']['status'] == 'passed'
    for relative, expected in json.loads((run / 'inputs-sha256.json').read_text()).items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    analyzer = runpy.run_path(str(ROOT / 'reports/workshop-measurements-20261030/mx-startup/analyze_startup.py'))
    analyzer['extract'](run)
    proof = {}
    for arm in ('text-only-source-bootstrap', 'text-only-mx-artifacts'):
        folder = run / arm
        result = json.loads((folder / 'result.json').read_text())
        text = '\n'.join(p.read_text() for p in folder.glob(result['target_pod'] + '-*.log'))
        marker = [line for line in text.splitlines() if 'running in text-only mode' in line]
        processor = [line for line in text.splitlines() if 'Multi-modal warmup completed' in line]
        encoder = [line for line in text.splitlines() if 'Encoder cache will be initialized with a budget' in line]
        cache = [line for line in text.splitlines() if any(word in line for word in
                 ('Available KV cache memory:', 'GPU KV cache size:', 'GPU KV cache blocks:', 'Maximum concurrency for'))]
        adoption = re.findall(r'Adopted (\d+) hidden accelerator tensors as module buffers in ([0-9.]+)s', text)
        evidence = {'text_only_mode_lines': marker,
                    'unexpected_mm_processor_warmup_lines': processor,
                    'unexpected_mm_encoder_profile_lines': encoder,
                    'kv_cache_capacity_lines': cache,
                    'hidden_tensor_adoption': [{'count': int(n), 'seconds': float(s)} for n, s in adoption],
                    'same_text_serving_limits': True,
                    'scope': 'Log evidence of text-only execution; retained text limits do not imply identical KV allocation'}
        write(folder / 'text-only-evidence.json', evidence)
        assert marker and not processor and not encoder, 'MM-removal evidence failed: ' + arm
        proof[arm] = evidence
    write(run / 'text-only-qualification.json', {'passed': True, 'arms': proof,
          'finalizer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'scope': 'N=1 text-only startup pilot; historical full-MM reference is unpaired; not an AgentX throughput result'})
    inventory = {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in run.rglob('*') if p.is_file() and p.name != 'evidence-sha256.json'}
    write(run / 'evidence-sha256.json', inventory)
    print(json.dumps({'qualified': True, 'files_sealed': len(inventory), 'run': str(run)}))


if __name__ == '__main__':
    main()
