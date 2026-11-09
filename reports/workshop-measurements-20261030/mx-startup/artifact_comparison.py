#!/usr/bin/env python3
"""Isolated central-metadata MX weight/artifact startup comparison."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import time
import measure_startup as base

ORIGINAL_MANIFESTS = base.manifests
ORIGINAL_GET_PODS = base.get_pods
REFERENCE_SPEC = base.ROOT / 'results/workshop-mx-startup-20261030-pair04/spec.json'
RR_MANIFEST = base.ROOT / 'results/workshop-rr-20261030-prep-1705/rr-1-replica.yaml'
COMPILE_DIGEST = 'supervl-tp2-native1048576-seqs4-batch8192-e98d074e'
MODE = 'weights'


def artifact_spec(run):
    original = json.loads(REFERENCE_SPEC.read_text())
    original.update({
        'schema': 2,
        'reference_spec_sha256': base.digest(REFERENCE_SPEC),
        'script_sha256': base.digest(__file__),
        'shared_helper_sha256': base.digest(base.__file__),
        'serving_profile_reference': str(RR_MANIFEST),
        'serving_profile_reference_sha256': base.digest(RR_MANIFEST),
        'context_length': 1048576,
        'max_model_len_override': None,
        'frontend_router_mode': 'round-robin',
        'sequence': ['central-source-artifacts-bootstrap', 'target-native-storage',
                     'target-mx-p2p-weights-only', 'target-mx-p2p-weights-and-artifacts'],
        'comparison_group': 'Matched central metadata path; one paired trial per target arm',
        'metadata_backend': 'redis through isolated MX server',
        'metadata_client_env': 'MX_SERVER_ADDRESS only; legacy MODEL_EXPRESS_URL absent to avoid Dynamo Rust model-download routing',
        'coordinator_model_downloads': 'HF_HUB_OFFLINE=1; central service supplies metadata only',
        'coordinator_images': json.loads((base.REPORT / 'artifact-coordinator-images.json').read_text()),
        'artifact_transfer': {'source': True, 'native_target': False,
                              'weight_target': False, 'artifact_target': True},
        'artifact_publication_wait_seconds': 180,
        'artifact_effectiveness_wait_seconds': 60,
        'compile_config_digest': COMPILE_DIGEST,
        'artifact_backend': 'NIXL; installed MX 0.6.0 does not expose newer Mooncake selection',
    })
    path = run.path / 'spec.json'
    content = json.dumps(original, indent=2, sort_keys=True) + '\n'
    if path.exists() and path.read_text() != content:
        raise ValueError('Frozen artifact spec changed; create a fresh run')
    path.write_text(content)
    (run.path / 'spec.sha256').write_text(base.digest(path) + '\n')
    return original


def central_manifests(run, role, native=False):
    items = ORIGINAL_MANIFESTS(run, role, native)
    for item in items:
        if item['kind'] != 'DynamoGraphDeployment':
            continue
        for component in item['spec']['components']:
            c = component['podTemplate']['spec']['containers'][0]
            if component['type'] != 'worker':
                if '--router-mode' in c['args']:
                    c['args'][c['args'].index('--router-mode') + 1] = 'round-robin'
                continue
            # Mirror the separately qualified AgentX profile: use model-native
            # context, retaining TP2, seq/batch limits, memory fraction and image.
            idx = c['args'].index('--max-model-len')
            del c['args'][idx:idx + 2]
            additions = {
                'MX_METADATA_BACKEND': 'redis',
                'MX_SERVER_ADDRESS': 'mx-coordinator:8001',
                'MX_P2P_METADATA': '1',
                'MX_ARTIFACT_TRANSFER': '1' if role == 'source' or MODE == 'artifacts' else '0',
                'MX_ARTIFACT_COMPILE_CONFIG_DIGEST': COMPILE_DIGEST,
                'MX_ARTIFACT_BUNDLE_ROOT': '/tmp/workshop-mx-artifact-bundles',
            }
            c['env'] = [e for e in c['env'] if e['name'] not in additions and e['name'] not in ('MX_K8S_SERVICE_PATTERN', 'MODEL_EXPRESS_URL')]
            c['env'] += [{'name': k, 'value': v} for k, v in additions.items()]
    return items


def coordinator_objects(run):
    images = artifact_spec(run)['coordinator_images']
    service = lambda name, port: {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name},
        'spec': {'selector': {'mx-startup-service': name}, 'ports': [{'name': 'service', 'port': port, 'targetPort': port}]}}
    redis = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'mx-redis', 'labels': {'mx-startup-service': 'mx-redis'}},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 21600,
            'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0942'},
            'containers': [{'name': 'redis', 'image': images['redis']['image'],
                'command': ['redis-server'], 'args': ['--save', '', '--appendonly', 'no'],
                'resources': {'requests': {'cpu': '100m', 'memory': '128Mi'}, 'limits': {'cpu': '1', 'memory': '512Mi'}},
                'readinessProbe': {'tcpSocket': {'port': 6379}, 'periodSeconds': 2}}]}}
    server = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'mx-coordinator', 'labels': {'mx-startup-service': 'mx-coordinator'}},
        'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 21600,
            'automountServiceAccountToken': False,
            'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0942'},
            'imagePullSecrets': [{'name': 'common-runtime-pull'}],
            'containers': [{'name': 'server', 'image': images['mx_server']['image'],
                'env': [{'name': k, 'value': v} for k, v in {
                    'MX_METADATA_BACKEND': 'redis', 'REDIS_URL': 'redis://mx-redis:6379',
                    'MODEL_EXPRESS_SERVER_PORT': '8001', 'MODEL_EXPRESS_CACHE_DIRECTORY': '/cache',
                    'MODEL_EXPRESS_LOG_LEVEL': 'info', 'HF_HUB_OFFLINE': '1',
                    'NVIDIA_VISIBLE_DEVICES': 'void'}.items()],
                'resources': {'requests': {'cpu': '200m', 'memory': '256Mi'}, 'limits': {'cpu': '2', 'memory': '1Gi'}},
                'volumeMounts': [{'name': 'cache', 'mountPath': '/cache'}],
                'readinessProbe': {'tcpSocket': {'port': 8001}, 'periodSeconds': 2}}],
            'volumes': [{'name': 'cache', 'emptyDir': {'sizeLimit': '2Gi'}}]}}
    return [service('mx-redis', 6379), service('mx-coordinator', 8001), redis, server]


def prepare(run):
    global MODE
    MODE = 'weights'
    base.prepare(run)
    objects = coordinator_objects(run)
    (run.path / 'coordinator.json').write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects}, indent=2) + '\n')
    run.apply(objects)
    try:
        for name in ['mx-redis', 'mx-coordinator']:
            base.status(f'Waiting for isolated CPU service {name}')
            run.wait_pod(name, timeout=300)
        program = '''import hashlib,importlib.metadata as m,json,os
from pathlib import Path
from google.protobuf.json_format import MessageToDict
from modelexpress.client import MxClient
assert 'MODEL_EXPRESS_URL' not in os.environ
c=MxClient()
assert c.server_url=='mx-coordinator:8001',c.server_url
sources=MessageToDict(c.list_sources(),preserving_proto_field_name=True)
root=Path(m.distribution('vllm').locate_file('vllm/compilation'))
compiler={name:{'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),'text':(root/name).read_text()} for name in ['decorators.py','backends.py']}
print('MX_COORDINATOR_RESULT='+json.dumps({'sources':sources,'resolved_server_url':c.server_url,'legacy_url_absent':'MODEL_EXPRESS_URL' not in os.environ,'vllm_version':m.version('vllm'),'compiler_sources':compiler}))
c.close()
'''
        pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'mx-coordinator-client-check'},
            'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 180,
                'automountServiceAccountToken': False,
                'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0942'},
                'imagePullSecrets': [{'name': 'common-runtime-pull'}],
                'containers': [{'name': 'check', 'image': run.state['model_lock']['runtime_image'],
                    'command': ['python3', '-c', program],
                    'env': [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                            {'name': 'MX_SERVER_ADDRESS', 'value': 'mx-coordinator:8001'},
                            {'name': 'MX_METADATA_BACKEND', 'value': 'redis'}],
                    'resources': {'requests': {'cpu': '100m', 'memory': '1Gi'}, 'limits': {'memory': '2Gi'}}}]}}
        run.apply([pod])
        run.wait_pod('mx-coordinator-client-check', completed=True, timeout=240)
        output = run.k('logs', 'mx-coordinator-client-check', '-n', run.ns).stdout
        (run.path / 'coordinator-client-check.json').write_text(output)
        result = json.loads(next(line.removeprefix('MX_COORDINATOR_RESULT=') for line in output.splitlines() if line.startswith('MX_COORDINATOR_RESULT=')))
        assert result['vllm_version'] == run.state['checks']['mx-startup-preparation']['packages']['vllm']
        (run.path / 'compiler-cache-capabilities.json').write_text(json.dumps(result, indent=2) + '\n')
        run.k('delete', 'pod', 'mx-coordinator-client-check', '-n', run.ns, '--wait=true', '--timeout=60s')
        run.result('mx-artifact-coordinator', 'passed', images=artifact_spec(run)['coordinator_images'],
            scope='CPU-only version-matched central metadata service; ListSources RPC from exact workload image passed')
    except Exception:
        base.collect(run, 'coordinator-preparation-failure')
        raise
    MODE = 'artifacts'
    path = run.path / 'target-artifacts.json'
    path.write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': central_manifests(run, 'target')}, indent=2) + '\n')
    run.k('apply', '--dry-run=client', '-f', str(path))
    run.k('apply', '--dry-run=server', '-f', str(path))
    MODE = 'weights'
    base.status(f'Isolated artifact coordinator ready for {run.path.name}; no GPU workloads launched')


def logs_for(run, directory, role):
    pods = json.loads((directory / 'pods.json').read_text())['items']
    worker = next(p for p in pods if p['metadata'].get('labels', {}).get('mx-role') == role)
    return '\n'.join(p.read_text() for p in directory.glob('*.log') if worker['metadata']['name'] in p.name)


def coordinator_healthy_get_pods(run, graph):
    all_pods = run.get('get', 'pods', '-n', run.ns)['items']
    for name in ['mx-redis', 'mx-coordinator']:
        pod = next((pod for pod in all_pods if pod['metadata']['name'] == name), None)
        if pod is None or pod.get('status', {}).get('phase') in ('Failed', 'Succeeded'):
            raise RuntimeError(f'Isolated coordinator prerequisite failed: {name}: {None if pod is None else pod.get("status")}')
        if any(container.get('restartCount', 0) for container in pod.get('status', {}).get('containerStatuses', [])):
            raise RuntimeError(f'Isolated coordinator prerequisite restarted: {name}')
    return [pod for pod in all_pods if pod['metadata'].get('labels', {}).get('nvidia.com/dynamo-graph-deployment-name') == graph and not pod['metadata'].get('deletionTimestamp')]


def run_arm(run, tag, role, native=False):
    result = base.run_arm(run, tag, role, native)
    logs = logs_for(run, run.path / tag, role)
    routed_downloads = [line for line in logs.splitlines() if 'dynamo_llm::hub' in line and 'Successfully connected to ModelExpress server' in line]
    if routed_downloads:
        raise RuntimeError('Unexpected Rust model-download routing to metadata-only coordinator: ' + '\n'.join(routed_downloads))
    if result['models']['data'][0].get('context_window') != 1048576:
        raise RuntimeError(f'Native context not established: {result["models"]}')
    return result


def await_artifact_publication(run):
    end = time.monotonic() + artifact_spec(run)['artifact_publication_wait_seconds']
    seen = ''
    while time.monotonic() < end:
        for pod in run.get('get', 'pods', '-n', run.ns)['items']:
            if pod['metadata'].get('labels', {}).get('mx-role') != 'source':
                continue
            text = run.k('logs', pod['metadata']['name'], '-n', run.ns, '-c', 'main', '--timestamps=true').stdout
            seen = text
            # Each rank publishes its own ready compiler-cache source. The
            # exact manifest and transfer identity are preserved in the logs.
            matches = [line for line in text.splitlines() if 'artifact publish complete:' in line]
            if len(matches) >= 2 and any('torch_compile' in line or 'flashinfer' in line for line in matches):
                (run.path / 'source-artifact-publication.log').write_text(text)
                return
        time.sleep(5)
    (run.path / 'source-artifact-publication.log').write_text(seen)
    raise TimeoutError('No compiler-cache artifact publication was observable within the fixed bound')


def batch(run):
    global MODE
    if run.state.get('checks', {}).get('mx-artifact-coordinator', {}).get('status') != 'passed':
        raise ValueError('Prepare and verify the isolated coordinator first')
    base.acquire(run)
    try:
        MODE = 'weights'
        run_arm(run, 'central-source-bootstrap', 'source')
        await_artifact_publication(run)
        native = run_arm(run, 'central-native-storage', 'target', native=True)
        base.stop_graph(run, 'ft-mx-target')
        weights = run_arm(run, 'central-mx-weights', 'target')
        base.stop_graph(run, 'ft-mx-target')
        MODE = 'artifacts'
        artifacts = run_arm(run, 'central-mx-artifacts', 'target')
        deadline = time.monotonic() + artifact_spec(run)['artifact_effectiveness_wait_seconds']
        logs = logs_for(run, run.path / 'central-mx-artifacts', 'target')
        while time.monotonic() < deadline:
            if logs.count('which ModelExpress installed') >= 2 or 'transferred cache was not reused' in logs:
                break
            time.sleep(5)
            directory = base.collect(run, 'central-mx-artifacts')
            logs = logs_for(run, directory, 'target')
        installs = [line for line in logs.splitlines() if 'artifact install complete:' in line]
        unused = [line for line in logs.splitlines() if 'installed' in line.lower() and any(s in line.lower() for s in ['not used', 'unused', 'not reused'])]
        selected = [line for line in logs.splitlines() if 'vLLM selected torch.compile cache directory' in line and 'which ModelExpress installed' in line]
        cache_hits = [line for line in logs.splitlines() if any(marker in line for marker in ['Directly load AOT compilation from path', 'Directly load the compiled graph(s)'])]
        cache_hit_ranks = sorted(set(re.findall(r'Worker_TP(\d+)', '\n'.join(cache_hits))))
        load_failures = [line for line in logs.splitlines() if 'Compiling model again due to a load failure' in line]
        if not installs or unused or len(selected) < 2 or cache_hit_ranks != ['0', '1'] or load_failures:
            (run.path / 'artifact-cache-check-failure.json').write_text(json.dumps({'installs': installs, 'selected': selected, 'cache_hits': cache_hits, 'unused': unused, 'load_failures': load_failures}, indent=2) + '\n')
            raise RuntimeError(f'Artifact transfer/reuse not established: installs={len(installs)}, selected_installed_cache={len(selected)}, actual_cache_hit_ranks={cache_hit_ranks}, unused={unused[:3]}, load_failures={load_failures[:3]}')
        proof = {'artifact_install_lines': installs, 'selected_installed_cache_lines': selected, 'unused_cache_warning_lines': unused,
            'actual_engine_cache_hit_lines': cache_hits, 'actual_engine_cache_hit_ranks': cache_hit_ranks,
            'engine_cache_lines': [line for line in logs.splitlines() if any(s in line.lower() for s in ['compile cache', 'compiled graph', 'loaded from cache', 'torch.compile'])]}
        (run.path / 'artifact-reuse-evidence.json').write_text(json.dumps(proof, indent=2) + '\n')
        result = {'storage': native, 'weights': weights, 'artifacts': artifacts,
            'weight_ready_speedup': native['apply_to_ready_observed_seconds'] / weights['apply_to_ready_observed_seconds'],
            'artifact_ready_speedup_vs_weights': weights['apply_to_ready_observed_seconds'] / artifacts['apply_to_ready_observed_seconds'],
            'scope': 'One matched trial per arm; API readiness/correct inference verified; inspect engine cache evidence separately from artifact-transfer success'}
        (run.path / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
        run.result('mx-artifact-startup-comparison', 'passed',
            weight_ready_speedup=result['weight_ready_speedup'], artifact_ready_speedup_vs_weights=result['artifact_ready_speedup_vs_weights'])
    except Exception as error:
        base.collect(run, 'failed-attempt')
        run.result('mx-artifact-batch', 'blocked', error=str(error))
        raise
    finally:
        base.stop_graph(run, 'ft-mx-target')
        base.stop_graph(run, 'ft-mx')
        base.collect(run, 'after-cleanup')
        base.release(run)
        hashes = {str(p.relative_to(run.path)): base.digest(p) for p in run.path.rglob('*') if p.is_file() and p.name != 'evidence-sha256.json'}
        (run.path / 'evidence-sha256.json').write_text(json.dumps(hashes, indent=2, sort_keys=True) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'batch', 'cleanup'])
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    base.frozen_spec = artifact_spec
    base.manifests = central_manifests
    base.get_pods = coordinator_healthy_get_pods
    run = base.setup_run(args.run)
    if args.action == 'prepare': prepare(run)
    elif args.action == 'batch': batch(run)
    else:
        base.stop_graph(run, 'ft-mx-target'); base.stop_graph(run, 'ft-mx')
        for pod in ['mx-coordinator', 'mx-redis']:
            run.k('delete', 'pod', pod, '-n', run.ns, '--ignore-not-found', '--wait=true', '--timeout=60s')
        if base.LEASE.exists(): base.release(run)


if __name__ == '__main__':
    main()
