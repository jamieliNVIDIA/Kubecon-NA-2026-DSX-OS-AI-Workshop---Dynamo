"""Owned-container supervision for the two-engine Guard qualification."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

HOLD = Path('/run/kvcr/hold-engine')


def environment():
    env = dict(os.environ)
    env['DYN_NAMESPACE'] = env['KVCR_DYNAMO_NAMESPACE']
    # The operator also injects a frontend discovery prefix. Keep it aligned
    # with the explicit namespace, rather than retaining the graph default.
    env['DYN_NAMESPACE_PREFIX'] = env['KVCR_DYNAMO_NAMESPACE']
    env.pop('DYN_NAMESPACE_WORKER_SUFFIX', None)
    env['DYN_KUBE_DISCOVERY_MODE'] = 'container'
    return env


def stop(child):
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=10)


def serve():
    env = environment()
    children = []
    try:
        command = [sys.executable, '-m', 'kvcr.service.server', '--socket-path', '/run/kvcr/memory.sock',
                   '--pool-dir', '/dev/shm/kvcr', '--guard-count', '1', '--pool-sizes-gb', '4',
                   '--startup-timeout-seconds', '180', '--compatibility-digest', env['KVCR_COMPATIBILITY_DIGEST'],
                   '--health-host', '0.0.0.0', '--health-port', '9092', '--log-level', 'DEBUG']
        if env['KVCR_PEER'] == 'a':
            agent_env = {**env, 'DYN_COMPONENT': 'kv_state_agent', 'DYN_SYSTEM_PORT': '9091',
                         'DYN_HEALTH_CHECK_ENABLED': 'false'}
            for name in ('DYN_SYSTEM_USE_ENDPOINT_HEALTH_STATUS', 'DYN_HEALTH_CHECK_TARGETS'):
                agent_env.pop(name, None)
            children.append(subprocess.Popen([sys.executable, '-m', 'dynamo.kv_state_agent', '--max-slots', '2'],
                                             env=agent_env, start_new_session=True))
            command += ['--health-dependency-url', 'http://127.0.0.1:9091/live']
        children.append(subprocess.Popen(command, env=env, start_new_session=True))
        while all(child.poll() is None for child in children):
            time.sleep(.2)
        raise RuntimeError('Guard or state-agent child exited; replacing a service under a live engine is not supported.')
    finally:
        for child in children:
            stop(child)


def engine_args(env):
    if env['KVCR_PEER'] not in ('a', 'b'):
        raise ValueError('Expected peer a or b.')
    slot = 0 if env['KVCR_PEER'] == 'a' else 1
    owner = '01010101010101010101010101010101:02020202020202020202020202020202/0303030303030303/' + f'{slot:032x}'
    config = {'kv_connector': 'OffloadingConnector', 'kv_role': 'kv_both', 'kv_connector_extra_config': {
        'spec_name': 'TieringOffloadingSpec', 'cpu_bytes_to_use': 4 * 1024 ** 3,
        'self_describing_kv_events': True,
        'dynamo_state_agent': {'raw_advertise_host': env['POD_IP'], 'cache_owner_ids': {'0': owner}},
        'secondary_tiers': [{'type': 'kvcr', 'router_capabilities': ['router_hint'],
            'kvcr_service_socket_path': '/run/kvcr/memory.sock',
            'compatibility_digest': env['KVCR_COMPATIBILITY_DIGEST'],
            'control_host': '0.0.0.0', 'control_ports': [23280], 'control_advertise_host': env['POD_IP'],
            'local_dram_backend': 'LIBFABRIC', 'remote_fw_dram_backend': 'LIBFABRIC',
            'operation_timeout_ms': 10000, 'abandon_timeout_ms': 20000, 'enable_telemetry': True}]}}
    # The Guard qualification keeps the 8K defaults; the speedup demo sets a long context explicitly.
    max_model_len = env.get('KVCR_MAX_MODEL_LEN', '8192')
    batched_tokens = env.get('KVCR_MAX_NUM_BATCHED_TOKENS', '8192')
    if not (max_model_len.isdigit() and batched_tokens.isdigit()):
        raise ValueError('KVCR context and batch limits must be positive integers.')
    return [sys.executable, '-m', 'dynamo.vllm', '--model', env['KVCR_MODEL'],
        '--revision', env['KVCR_MODEL_REVISION'], '--served-model-name', env['KVCR_MODEL'],
        '--trust-remote-code', '--tensor-parallel-size', '2', '--max-model-len', max_model_len,
        '--max-num-seqs', '4', '--max-num-batched-tokens', batched_tokens, '--gpu-memory-utilization', '0.85',
        '--enable-prefix-caching', '--block-size', '64', '--enforce-eager', '--language-model-only',
        '--mamba-backend', 'flashinfer', '--mamba-ssm-cache-dtype', 'float16', '--mamba-cache-mode', 'align',
        '--reasoning-parser', 'nemotron_v3', '--disaggregation-mode', 'agg',
        '--kv-events-config', json.dumps({'publisher': 'zmq', 'topic': 'kv-events', 'endpoint': 'tcp://*:20080',
                                        'enable_kv_cache_events': True}),
        '--kv-transfer-config', json.dumps(config)]


def engine():
    env = environment()
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:9092/ready', timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            pass
        time.sleep(1)
    else:
        raise TimeoutError('Guard/state agent did not become ready.')
    child = None
    try:
        while True:
            while HOLD.exists():
                time.sleep(.5)
            command = engine_args(env)
            print('KVCR_ENGINE_START=' + json.dumps({'peer': env['KVCR_PEER'], 'argv': command}), flush=True)
            child = subprocess.Popen(command, env=env, start_new_session=True)
            code = child.wait()
            print('KVCR_ENGINE_EXIT=' + json.dumps({'peer': env['KVCR_PEER'], 'returncode': code}), flush=True)
            if not HOLD.exists():
                raise RuntimeError('Unexpected engine exit outside the explicit fault hold.')
    finally:
        if child:
            stop(child)


def main():
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    if sys.argv[1] == 'service':
        serve()
    elif sys.argv[1] == 'engine':
        engine()
    elif sys.argv[1] == 'frontend':
        env = environment()
        command = [sys.executable, '-m', 'dynamo.frontend', '--router-mode', 'kv', '--trust-remote-code']
        os.execvpe(command[0], command, env)
    else:
        raise ValueError('Unknown runtime role.')


if __name__ == '__main__':
    main()
