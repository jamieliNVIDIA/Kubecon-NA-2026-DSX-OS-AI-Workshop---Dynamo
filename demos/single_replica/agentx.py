"""AIPerf AgentX steps for the intro: one short trace slice at concurrency 1, then 8.

Offstage, prepare-aiperf installs the pinned AIPerf, fetches the AgentX corpus and tokenizer, and runs both
commands against AIPerf's mock server. That smoke builds the dataset cache, so on stage AIPerf starts in a
few seconds and needs no network. The run itself streams to the presenter's terminal.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
# The AgentX source of the workshop measurements: AIPerf 0.13.0 at e2c149ee plus the dataset-revision pin
# (reports/workshop-measurements-20261030/agentx-workload/README.md).
ARCHIVE = ROOT / 'results/20261030-agentx-workload-prep-000329/aiperf-agentx-pinned-source.tar.gz'
ARCHIVE_SHA256 = '4e7f3a2ed15276a5252200e4d4772bf4d10e182edf2cbff4a9606794822d4699'
VERSION = '0.13.0'
HF_DATASET = 'semianalysisai/cc-traces-weka-062126'
DATASET_REVISION = '23f152f6f0f9399a85901b89a6458def0ef16729'
HOME = ROOT / '.local/aiperf'
SOURCE = HOME / ('source-' + ARCHIVE_SHA256[:12])
AIPERF = SOURCE / '.venv/bin/aiperf'
PYTHON = SOURCE / '.venv/bin/python'
RECEIPT = HOME / 'staged.json'
CACHE = HOME / 'dataset-cache'
CONCURRENCY = (1, 8)
TIMEOUT = 240  # one on-stage run takes about 35 s: start-up, 20 s of load, up to 10 s of grace, the report
SMOKE_TIMEOUT = 1800  # the first smoke run builds the dataset cache

# A short slice of the AgentX scenario: the first eight sessions that fit in 128K tokens, each from its first
# request (so there are no warmup primers), answers capped at 128 tokens, 20 s of load. The grace period is
# short because a session waiting on its subagents holds the phase open until it expires; answers still
# streaming then are left out of the report, not counted as errors. The scenario itself runs at least 900 s
# on all 393 sessions, so AIPerf needs --unsafe-override and stamps the result invalid.
SLICE = (
    ('--scenario', 'inferencex-agentx-mvp', '--unsafe-override'),
    ('--public-dataset', 'semianalysis_cc_traces_weka_062126'),
    ('--num-dataset-entries', '8', '--max-context-length', '131072'),
    ('--trajectory-start-min-ratio', '0', '--trajectory-start-max-ratio', '0'),
    ('--synthesis-max-osl', '128', '--random-seed', '20261030'),
    ('--benchmark-duration', '20', '--benchmark-grace-period', '10'),
)

IDENTITY = '''import json, platform
from importlib.metadata import version
from aiperf.dataset.loader.semianalysis_cc_traces_weka import SemiAnalysisCCTracesWekaLoader as loader
print(json.dumps({'aiperf': version('aiperf'), 'dataset_revision': loader.hf_revision,
                  'python': platform.python_version()}))'''

PREFETCH = '''import sys
from datasets import load_dataset
from transformers import AutoTokenizer
dataset, revision, model, model_revision = sys.argv[1:]
print('AgentX traces:', len(load_dataset(dataset, split='train', revision=revision)), flush=True)
AutoTokenizer.from_pretrained(model, revision=model_revision)
print('Tokenizer cached:', model, model_revision, flush=True)'''


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def settings():
    """Environment for every AIPerf run: offline, with the dataset cache that staging warmed."""
    return {
        'HF_HOME': str(HOME / 'hf'), 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'AIPERF_DATASET_MMAP_CACHE_DIR': str(CACHE), 'AIPERF_DATASET_MMAP_BASE_PATH': str(HOME / 'mmap'),
        'AIPERF_DATASET_WEKA_PARALLEL_WORKERS': '1',
    }


def environment(*, online=False):
    env = {k: v for k, v in os.environ.items() if k not in ('VIRTUAL_ENV', 'PYTHONHOME', 'PYTHONPATH')}
    env.update(settings())
    if online:
        for name in ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE'):
            env.pop(name)
    return env


def groups(lock, url, concurrency, artifacts):
    """The command as projected, one related group of flags per line."""
    return (('aiperf', 'profile'),) + SLICE + (
        ('--model', lock['model']),
        ('--tokenizer-revision', lock['revision']),
        ('--url', url, '--streaming', '--use-server-token-count'),
        ('--log-level', 'warning', '--no-gpu-telemetry', '--ui', 'simple'),
        ('--artifact-dir', artifacts, '--concurrency', str(concurrency)),
    )


def projected(command):
    return ' \\\n    '.join(' '.join(shlex.quote(str(word)) for word in group) for group in command)


def arguments(command):
    """The executed argv: the projected words, with the pinned environment's aiperf."""
    words = [str(word) for group in command for word in group]
    return [str(AIPERF)] + words[1:]


def artifact_name(path, concurrency):
    """A fresh artifact folder per attempt, so a resumed walkthrough keeps the earlier evidence."""
    name, attempt = f'aiperf-c{concurrency}', 1
    while (Path(path) / name).exists() or (Path(path) / (name + '.json')).exists():
        attempt += 1
        name = f'aiperf-c{concurrency}-{attempt}'
    return name


def fingerprint(lock):
    value = {'archive_sha256': ARCHIVE_SHA256, 'dataset_revision': DATASET_REVISION, 'model': lock['model'],
             'revision': lock['revision'], 'slice': SLICE}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def staged(lock):
    """The staging receipt when this host can run the slice offline from a warm cache, otherwise None."""
    try:
        receipt = json.loads(RECEIPT.read_text())
    except (OSError, ValueError):
        return None
    if receipt.get('fingerprint') != fingerprint(lock) or not AIPERF.is_file():
        return None
    if not (CACHE / str(receipt.get('cache_key')) / 'manifest.json').is_file():
        return None
    return receipt


def stop(process):
    process.send_signal(signal.SIGINT)
    try:
        return process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()


def run(command, cwd):
    """Run AIPerf on this terminal, so its progress bars and tables appear live; return the receipt."""
    args, started = arguments(command), now()
    (HOME / 'mmap').mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(args, cwd=str(cwd), env=environment())
    timed_out = False
    try:
        code = process.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        timed_out = True
        code = stop(process)
    except KeyboardInterrupt:
        stop(process)
        raise
    return {'args': args, 'cwd': str(cwd), 'environment': settings(), 'started_at': started, 'ended_at': now(),
            'exit_code': code, 'timed_out': timed_out}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            value.update(block)
    return value.hexdigest()


def unpack(archive, target):
    temporary = target.with_name(f'.{target.name}.{os.getpid()}.tmp')
    shutil.rmtree(temporary, ignore_errors=True)
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        for member in members:
            name = os.path.normpath(member.name)
            link = os.path.normpath(os.path.join(os.path.dirname(name), member.linkname)) if member.issym() else ''
            if (os.path.isabs(name) or name.startswith('..') or member.islnk() or member.isdev() or
                    os.path.isabs(member.linkname) or link.startswith('..')):
                raise RuntimeError('Unexpected entry in the pinned AIPerf archive: ' + member.name)
        bundle.extractall(temporary, members=members, **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))
    temporary.rename(target)


def step(log, args, **kwargs):
    with log.open('a') as output:
        output.write(f'\n$ {shlex.join(map(str, args))}\n')
        output.flush()
        result = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE, stderr=output, stdin=subprocess.DEVNULL,
                                text=True, **kwargs)
        output.write(result.stdout)
    if result.returncode:
        raise RuntimeError(f'Failed ({result.returncode}): {shlex.join(map(str, args))}\nSee {log}')
    return result.stdout


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def cache_entries():
    return {p.name for p in CACHE.iterdir() if (p / 'manifest.json').is_file()} if CACHE.is_dir() else set()


def smoke(lock, folder, log):
    """Both commands against AIPerf's mock server: the first builds the dataset cache, the second must reuse it."""
    port = free_port()
    url = f'http://127.0.0.1:{port}'
    (HOME / 'mmap').mkdir(parents=True, exist_ok=True)
    server_env = environment()
    server_env['PYTHONPATH'] = str(SOURCE / 'tests')  # the mock server ships with the pinned source
    with log.open('a') as output:
        server = subprocess.Popen([str(PYTHON), '-m', 'aiperf_mock_server', '--port', str(port), '--no-tokenizer'],
                                  env=server_env, stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    try:
        for _ in range(120):
            if server.poll() is not None:
                raise RuntimeError(f'AIPerf mock server stopped; see {log}')
            try:
                urllib.request.urlopen(url + '/v1/models', timeout=2).close()
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError(f'AIPerf mock server did not start; see {log}')
        results, keys = {}, set()
        for concurrency in CONCURRENCY:
            before, started = cache_entries(), time.monotonic()
            command = groups(lock, url, concurrency, f'aiperf-c{concurrency}')
            with (folder / f'aiperf-c{concurrency}.log').open('w') as output:
                code = subprocess.run(arguments(command), cwd=str(folder), env=environment(), stdout=output,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=SMOKE_TIMEOUT).returncode
            export = folder / f'aiperf-c{concurrency}' / 'profile_export_aiperf.json'
            data = json.loads(export.read_text()) if export.is_file() else {}
            requests = (data.get('request_count') or {}).get('avg') or 0
            if code or not requests or data.get('error_summary'):
                raise RuntimeError(f'AIPerf smoke at concurrency {concurrency} failed; see '
                                   f'{folder / f"aiperf-c{concurrency}.log"}')
            created = cache_entries() - before
            keys |= created
            results[str(concurrency)] = {'seconds': round(time.monotonic() - started, 1), 'requests': requests,
                                         'cache_entries_created': sorted(created)}
            print(f'  concurrency {concurrency}: {requests:.0f} requests against the mock server in '
                  f'{results[str(concurrency)]["seconds"]:.0f} s', flush=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
    if results[str(CONCURRENCY[-1])]['cache_entries_created']:
        raise RuntimeError('The second smoke run built its own dataset cache; the two runs no longer share one.')
    entries = cache_entries()
    keys = keys or (entries if len(entries) == 1 else set())
    if len(keys) != 1:
        raise RuntimeError(f'Cannot identify the dataset cache entry; remove {CACHE} and stage again.')
    return results, keys.pop()


def stage(lock):
    """Install the pinned AIPerf, fetch the corpus and tokenizer, then warm the dataset cache with a smoke."""
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    HOME.mkdir(parents=True, exist_ok=True)
    log = HOME / f'stage-{stamp}.log'
    print(f'Staging AIPerf for the AgentX steps. Takes a few minutes once per host. Log: {log}', flush=True)
    if not ARCHIVE.is_file() or digest(ARCHIVE) != ARCHIVE_SHA256:
        raise RuntimeError(f'The pinned AIPerf source is missing or changed: {ARCHIVE}\n'
                           f'Copy it from the laptop checkout; its sha256 is {ARCHIVE_SHA256}.')
    if not (SOURCE / 'pyproject.toml').is_file():
        unpack(ARCHIVE, SOURCE)
    uv = shutil.which('uv')
    if not uv:
        raise RuntimeError('uv is not on PATH. Source the workshop environment script first.')
    print('1/3 Pinned AIPerf environment (uv sync --frozen)', flush=True)
    step(log, [uv, 'sync', '--project', SOURCE, '--frozen', '--no-dev', '--no-editable', '--python', '3.12'],
         env=environment(online=True))
    identity = json.loads(step(log, [PYTHON, '-I', '-c', IDENTITY], env=environment()).strip().splitlines()[-1])
    if identity['aiperf'] != VERSION or identity['dataset_revision'] != DATASET_REVISION:
        raise RuntimeError(f'Unexpected AIPerf environment: {identity}')
    print(f'2/3 AgentX corpus {HF_DATASET}@{DATASET_REVISION[:8]} and the tokenizer', flush=True)
    step(log, [PYTHON, '-I', '-c', PREFETCH, HF_DATASET, DATASET_REVISION, lock['model'], lock['revision']],
         env=environment(online=True))
    print('3/3 Smoke against AIPerf\'s mock server, offline', flush=True)
    folder = HOME / 'smoke' / stamp
    folder.mkdir(parents=True)
    results, key = smoke(lock, folder, log)
    receipt = {'schema': 1, 'staged_at': now(), 'fingerprint': fingerprint(lock), 'archive_sha256': ARCHIVE_SHA256,
               'identity': identity, 'dataset': HF_DATASET, 'dataset_revision': DATASET_REVISION,
               'tokenizer': lock['model'], 'tokenizer_revision': lock['revision'], 'slice': SLICE,
               'cache_key': key, 'smoke': results, 'smoke_folder': str(folder), 'log': str(log)}
    temporary = RECEIPT.with_name(RECEIPT.name + '.tmp')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(RECEIPT)
    print(f'AIPerf staged: aiperf {identity["aiperf"]}, dataset cache {key}. Receipt: {RECEIPT}', flush=True)
    return receipt
