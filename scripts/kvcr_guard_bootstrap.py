"""Stage a frozen KVCR/vLLM Python overlay inside an owned disposable container."""
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import urllib.request


CHECK = '''import ctypes,importlib.metadata as md,importlib.util,inspect,json,platform
from packaging.version import Version
import kvcr
import dynamo.vllm.main
from kvcr import KVCRClient
from kvcr.config import KVCRGuardConfig,KeyAdapter
from vllm.v1.kv_offload.tiering.kvcr import manager
from vllm.v1.kv_offload.tiering.factory import SecondaryTierFactory
from vllm.v1.kv_offload.tiering.base import TransferJob
from vllm.distributed.kv_transfer.kv_connector.v1.offloading.metrics import OffloadingConnectorStats
from types import SimpleNamespace
assert md.version('kvcr')=='0.2.0'
assert md.version('nixl')=='1.5.0'
expected_dynamo=__import__('os').environ.get('KVCR_EXPECT_DYNAMO_VERSION')
if expected_dynamo:
 assert md.version('ai-dynamo')==expected_dynamo
 assert md.version('ai-dynamo-runtime')==expected_dynamo
assert Version(md.version('msgspec'))>=Version('0.21.0')
assert Version('25.0.0')<=Version(md.version('pyzmq'))<Version('28')
ctypes.CDLL('libatomic.so.1')
assert hasattr(manager._VllmKeyAdapter,'decode_from_framework')
assert hasattr(manager._VllmKeyAdapter,'encode_to_router')
assert 'kvcr_service_socket_path' in inspect.signature(manager.KVCRSecondaryTierManager.__init__).parameters
assert 'chunk_ids' in TransferJob.__dataclass_fields__
assert SecondaryTierFactory.get_tier_class({'type':'kvcr'}) is manager.KVCRSecondaryTierManager
stats=OffloadingConnectorStats()
stats.increase_counter('kvcr_transfer_blocks',3,('remote_deliver',))
stats.set_gauge('kvcr_state',2,('blocks',))
stats.observe_histogram('kvcr_duration_seconds',0.5,('remote_deliver','success'))
tier=object.__new__(manager.KVCRSecondaryTierManager)
tier._kvcr=SimpleNamespace(get_stats=lambda:stats)
translated=tier.get_stats()
assert translated is stats
assert 'vllm:kvcr_transfer_blocks' in translated.metric_sections()[1]
assert translated.reduce()["vllm:kvcr_transfer_blocks:('remote_deliver',)"]==3
print(json.dumps({'status':'passed','scope':'CPU import and API compatibility only; no inference or Guard recovery proof',
 'packages':{p:md.version(p) for p in ('kvcr','nixl','vllm','ai-dynamo','ai-dynamo-runtime')},
 'kvcr_path':kvcr.__file__,'adapter_path':manager.__file__,'kernel':platform.release(),
 'has_pidfd_open':hasattr(__import__('os'),'pidfd_open'),
 'adapter_telemetry_roundtrip':True,
 'state_agent_available':importlib.util.find_spec('dynamo.kv_state_agent') is not None}))
'''


def fetch(record, attempts=5):
    """Download one pinned wheel. A cut-off or corrupted transfer is retried here, so it cannot restart the container."""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(record['url'], timeout=120) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() == record['sha256']:
                return data
            error = 'hash mismatch after ' + str(len(data)) + ' bytes'
        except (OSError, http.client.HTTPException) as caught:
            error = type(caught).__name__ + ': ' + str(caught)
        print('KVCR_DOWNLOAD_FAILED ' + json.dumps({'filename': record['filename'], 'attempt': attempt,
                                                    'attempts': attempts, 'error': error[:300]}), flush=True)
        if attempt < attempts:
            time.sleep(2 ** attempt)
    raise ValueError('Nightly wheel ' + record['filename'] + ' failed ' + str(attempts) + ' downloads; last: ' + error)


def main():
    bundle = Path('/candidate/bundle.tar.gz')
    expected = os.environ['KVCR_BUNDLE_SHA256']
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != expected:
        raise ValueError('Frozen source bundle changed.')
    root = Path('/tmp/kvcr-guard-candidate')
    root.mkdir(exist_ok=False)
    with tarfile.open(bundle, 'r:gz') as archive:
        for member in archive.getmembers():
            destination = root / member.name
            if (not member.isfile() or Path(member.name).is_absolute() or
                    '..' in Path(member.name).parts):
                raise ValueError('Unsafe source bundle member.')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.extractfile(member).read())
    target = root / 'installed'
    build_dependencies = root / 'build-dependencies'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                    '--target', str(build_dependencies),
                    *map(str, sorted((root / 'build-wheels').glob('*.whl')))], check=True)
    build_environment = dict(os.environ)
    build_environment['PYTHONPATH'] = str(build_dependencies) + os.pathsep + build_environment.get('PYTHONPATH', '')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                    '--no-build-isolation', '--target', str(target), str(root / 'kvcr')],
                   check=True, env=build_environment)
    nightly_manifest = root / 'runtime-meta/runtime-sources.json'
    if nightly_manifest.exists():
        nightly = json.loads(nightly_manifest.read_text())
        wheel_directory = root / 'runtime-wheels'
        wheel_directory.mkdir()
        wheels = []
        for record in nightly['wheels']:
            if Path(record['filename']).name != record['filename']:
                raise ValueError('Unsafe nightly wheel filename.')
            data = fetch(record)
            wheel = wheel_directory / record['filename']
            wheel.write_bytes(data)
            wheels.append(str(wheel))
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                        '--target', str(target), *wheels], check=True)
        os.environ['KVCR_EXPECT_DYNAMO_VERSION'] = nightly['version']
        print('KVCR_DYNAMO_NIGHTLY=' + json.dumps(nightly), flush=True)
    vllm_root = Path(importlib.util.find_spec('vllm').origin).parent.parent
    records = []
    for source in sorted((root / 'adapter').rglob('*.py')):
        relative = source.relative_to(root / 'adapter')
        destination = vllm_root / relative
        before = hashlib.sha256(destination.read_bytes()).hexdigest() if destination.exists() else None
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        records.append({'path': str(relative), 'base_sha256': before,
                        'candidate_sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    print('KVCR_OVERLAY=' + json.dumps({'bundle_sha256': expected, 'files': records}), flush=True)
    # Spawned EngineCore interpreters inherit PYTHONPATH; keep KVCR diagnostics
    # visible independently of vLLM's logging configuration in every process.
    (target / 'sitecustomize.py').write_text(
        "import logging\n"
        "logger=logging.getLogger('kvcr')\n"
        "logger.setLevel(logging.DEBUG)\n"
        "handler=logging.StreamHandler()\n"
        "handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))\n"
        "logger.addHandler(handler)\n"
        "logger.propagate=False\n")
    environment = dict(os.environ)
    environment['PYTHONPATH'] = str(target) + os.pathsep + environment.get('PYTHONPATH', '')
    environment['KVCR_SOURCE_ROOT'] = str(root / 'kvcr')
    if sys.argv[1:] == ['check']:
        command = [sys.executable, '-c', CHECK]
    else:
        command = sys.argv[1:]
        if not command:
            raise ValueError('Expected check or a child command.')
    os.execvpe(command[0], command, environment)


if __name__ == '__main__':
    main()
