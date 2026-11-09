#!/usr/bin/env python3
"""Qualify a private common-image candidate in a fresh owned namespace."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
from common_runtime_build import ngc_credential
from serving_tests import lock_model, smoke
from testlib import OWNER, ROOT, Run

SECRET = 'common-runtime-pull'


def configured_pull_secret_source():
    """Use the host's saved secret reference even without shell activation."""
    source = os.environ.get('WORKSHOP_PULL_SECRET_SOURCE', '').strip()
    if not source:
        reference = ROOT / '.local/pull-secret-source'
        if not reference.exists():
            return None
        try:
            source = reference.read_text().strip()
        except OSError:
            raise RuntimeError('Cannot read the saved workshop pull-secret reference') from None
    parts = source.split('/')
    label = r'[a-z0-9](?:[-a-z0-9]*[a-z0-9])?'
    if (len(parts) != 2 or len(parts[0]) > 63 or not re.fullmatch(label, parts[0]) or
            len(parts[1]) > 253 or not all(len(piece) <= 63 and re.fullmatch(label, piece)
                                         for piece in parts[1].split('.'))):
        raise ValueError('WORKSHOP_PULL_SECRET_SOURCE or .local/pull-secret-source must be namespace/name')
    return parts


def pull_secret(run):
    namespace = run.get('get', 'namespace', run.ns)
    if namespace['metadata'].get('labels', {}).get('app.kubernetes.io/managed-by') != OWNER:
        raise ValueError('Namespace is not owned')
    # Metadata only: do not put registry credentials in saved command outputs.
    found = run.k('get', 'secret', SECRET, '-n', run.ns, '-o',
                  'jsonpath={.metadata.labels.feature-test-run}', check=False)
    if found.returncode == 0 and found.stdout != run.ns:
        raise ValueError('Pull secret name is already unowned')
    source = configured_pull_secret_source()
    if source is not None:
        parts = source
        # Bypass Run.command: its receipts must never contain source credentials.
        result = subprocess.run(run.kbase + ['get', 'secret', parts[1], '-n', parts[0], '-o', 'json'],
                                capture_output=True, text=True, timeout=40)
        if result.returncode:
            raise RuntimeError('Cannot read the configured workshop pull secret')
        secret = json.loads(result.stdout)
        if secret.get('type') != 'kubernetes.io/dockerconfigjson':
            raise ValueError('Workshop pull secret must have type kubernetes.io/dockerconfigjson')
        encoded = secret.get('data', {}).get('.dockerconfigjson')
        config = json.loads(base64.b64decode(encoded or '', validate=True))
        if not config.get('auths', {}).get('nvcr.io', {}).get('auth'):
            raise ValueError('Workshop pull secret has no nvcr.io credential')
    else:
        credential = ngc_credential()
        config = {'auths': {'nvcr.io': {'auth': base64.b64encode(
            (credential['Username'] + ':' + credential['Secret']).encode()).decode()}}}
    obj = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': SECRET, 'namespace': run.ns,
           'labels': run.labels()}, 'type': 'kubernetes.io/dockerconfigjson',
           'data': {'.dockerconfigjson': base64.b64encode(json.dumps(config).encode()).decode()}}
    # Run.apply persists manifests. Use audited commands without persisting the
    # secret body; stdin is not recorded by Run.command.
    content = json.dumps(obj)
    run.k('apply', '--dry-run=server', '-f', '-', input_text=content)
    run.k('apply', '-f', '-', input_text=content)


def prepare(run, build_run):
    candidate = json.loads((build_run / 'common-runtime-candidate.json').read_text())
    if candidate['status'] not in ('candidate', 'qualified') or candidate['architecture'] != 'amd64':
        raise ValueError('Requires a published AMD64 candidate')
    lock = json.loads((ROOT / 'configs/model-lock.json').read_text())
    lock.update(runtime_image=candidate['image'], runtime_release='1.6.0', runtime_version_override='1.6.0',
                common_runtime=True, image_pull_secret=SECRET, runtime_source_revision=candidate['dynamo_source'])
    path = run.path / 'model-lock.json'
    content = json.dumps(lock, indent=2) + '\n'
    if path.exists() and path.read_text() != content:
        raise ValueError('Candidate lock changed; use a fresh qualification run')
    path.write_text(content)
    run.state['common_build_run'] = str(build_run.resolve())
    run.save()
    from upgrade_retests import cache
    cache(run, ROOT / 'results/20261013t023201z-features')
    pull_secret(run)
    efa(run)
    run.result('common-runtime-preparation', 'passed', image=candidate['image'],
               scope='Fresh model/wheel cache validation and owned pull secret; no feature qualification')


def efa(run):
    code = (ROOT / 'configs/upstream/recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh').read_text()
    wrapper = '''#!/usr/bin/env bash
set -euo pipefail
export PATH=/opt/amazon/efa/bin:$PATH
export LD_LIBRARY_PATH=/opt/amazon/efa/lib:/opt/amazon/efa/lib64:/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}
test -x /opt/amazon/efa/bin/fi_info
fi_info -p efa -t FI_EP_RDM >/tmp/efa-provider.txt
exec "$@"
'''
    run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'efa-userspace'},
                'data': {'entrypoint.sh': wrapper, 'check-efa-userspace.sh': code}}])


def probe(run):
    lock = lock_model(run)
    tp = lock.get('tensor_parallel_size', 1)
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'common-runtime-probe'},
           'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 600,
                    'automountServiceAccountToken': False, 'imagePullSecrets': [{'name': SECRET}],
                    'nodeSelector': {'kubernetes.io/hostname': 'kubecon-nke-site-cp-0124'},
                    'containers': [{'name': 'probe', 'image': lock['runtime_image'],
                                    'command': ['python3', '/opt/common-runtime-probe.py'],
                                    'resources': {'requests': {'cpu': '2', 'memory': '8Gi', 'nvidia.com/gpu': str(tp), 'vpc.amazonaws.com/efa': str(4 * tp)},
                                                  'limits': {'memory': '16Gi', 'nvidia.com/gpu': str(tp), 'vpc.amazonaws.com/efa': str(4 * tp)}},
                                    'securityContext': {'runAsUser': 0, 'capabilities': {'add': ['IPC_LOCK']}}}]}}
    if tp > 1:
        # Mount the current probe; the immutable image retains its original TP1 probe.
        run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'tp-runtime-probe'},
                    'data': {'probe.py': (ROOT / 'scripts/common_runtime_probe.py').read_text()}}])
        spec = pod['spec']
        spec['containers'][0]['command'] = ['python3', '/tests/probe.py', '--gpus', str(tp)]
        spec['containers'][0]['volumeMounts'] = [{'name': 'tests', 'mountPath': '/tests', 'readOnly': True}]
        spec['volumes'] = [{'name': 'tests', 'configMap': {'name': 'tp-runtime-probe'}}]
    run.apply([pod])
    try:
        finished = run.wait_pod('common-runtime-probe', timeout=720, completed=True)
        logs = run.k('logs', 'common-runtime-probe', '-n', run.ns).stdout
        (run.path / 'common-runtime-probe.log').write_text(logs)
        report = json.loads(next(line.split(' ', 1)[1] for line in logs.splitlines() if line.startswith('COMMON_RUNTIME_RESULT ')))
        report['image_id'] = finished['status']['containerStatuses'][0]['imageID']
        run.result('common-runtime-probe', 'passed', **report)
    finally:
        run.k('delete', 'pod', 'common-runtime-probe', '-n', run.ns, '--ignore-not-found', '--wait=false', check=False)


def stop(run, graphs):
    for name in graphs:
        found = run.k('get', 'dgd', name, '-n', run.ns, '-o', 'json', check=False)
        if found.returncode == 0:
            obj = json.loads(found.stdout)
            if obj['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
                raise ValueError('DGD not owned')
            run.k('delete', 'dgd', name, '-n', run.ns, '--wait=true', '--timeout=90s', timeout=105)
        elif 'NotFound' not in found.stderr:
            raise RuntimeError(found.stderr)
        selector = 'nvidia.com/dynamo-graph-deployment-name=' + name
        for pod in run.get('get', 'pods', '-n', run.ns, '-l', selector)['items']:
            run.k('wait', '--for=delete', 'pod/' + pod['metadata']['name'], '-n', run.ns,
                  '--timeout=150s', timeout=165)


def stop_grove(run):
    found = run.k('get', 'podcliqueset', 'ft-grove', '-n', run.ns, '-o', 'json', check=False)
    if found.returncode == 0:
        if json.loads(found.stdout)['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
            raise ValueError('Grove test is not owned')
        run.k('delete', 'podcliqueset', 'ft-grove', '-n', run.ns, '--wait=true', '--timeout=90s', timeout=105)
    elif 'NotFound' not in found.stderr:
        raise RuntimeError(found.stderr)
    for pod in run.get('get', 'pods', '-n', run.ns)['items']:
        if pod['metadata']['name'].startswith('ft-grove-'):
            if pod['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
                raise ValueError('Grove Pod is not owned')
            run.k('wait', '--for=delete', 'pod/' + pod['metadata']['name'], '-n', run.ns,
                  '--timeout=150s', timeout=165)


def record_qualification(run, inventory=None):
    required = ('common-runtime-probe', 'agg-inference', 'kv-routing', 'engine-sidecar',
                'kvcr', 'kvcr-canary-stability', 'disaggregation', 'modelexpress',
                'grove-kai', 'snapshot-runtime-preparation', 'snapshot-restore',
                'snapshot-cleanup', 'common-cleanup', 'common-manifests')
    checks = run.state['checks']
    missing = [name for name in required if checks.get(name, {}).get('status') != 'passed']
    if missing or checks.get('shadow-runtime', {}).get('status') != 'present':
        raise ValueError('Incomplete feature qualification: ' + ', '.join(missing))
    if inventory is not None:
        inventory = inventory.resolve()
        receipt = json.loads((inventory / 'receipt.json').read_text())
        pods = json.loads((inventory / 'pods.json').read_text())
        active = [p['namespace'] + '/' + p['name'] for p in pods
                  if p['phase'] not in ('Succeeded', 'Failed')
                  and p['namespace'].startswith('dynamo-ft-')
                  and any(float(c.get('resources', {}).get('requests', {}).get('nvidia.com/gpu', 0))
                          for c in p['containers'])]
        if active or any(n['ready'] != 'True' for n in receipt['nodes']):
            raise ValueError('Final inventory has active test GPU Pods or non-Ready nodes')
        run.result('common-final-inventory', 'passed', nodes=receipt['nodes'], active_test_gpu_pods=active,
                   observed_at=receipt['finished_at'], receipt=str(inventory.relative_to(ROOT)))
    lock = lock_model(run)
    build_run = Path(run.state['common_build_run'])
    candidate_path = build_run / 'common-runtime-candidate.json'
    candidate = json.loads(candidate_path.read_text())
    if not lock.get('common_runtime') or candidate['image'] != lock['runtime_image']:
        raise ValueError('Candidate/run image mismatch')
    if checks['common-runtime-probe']['image_id'] != lock['runtime_image']:
        raise ValueError('Allocated probe image mismatch')
    restored = json.loads((run.path / 'snapshot-restored-pod.json').read_text())
    if restored['status']['containerStatuses'][0]['imageID'] != lock['runtime_image']:
        raise ValueError('Restored image mismatch')
    measurements = json.loads((run.path / 'snapshot-measurements-latest.json').read_text())
    if not measurements['ready']:
        raise ValueError('Snapshot artifact not ready')
    qualified = {**lock, 'qualification': {
        'status': 'passed', 'scope': 'Bounded vLLM/Nemotron TP1 feature matrix; not performance/capacity qualification',
        'run': str(run.path.relative_to(ROOT)), 'packages': checks['common-runtime-probe']['packages'],
        'features': {name: checks[name]['status'] for name in required},
        'shadow_failover': {'status': 'blocked' if checks['shadow-preflight']['blockers'] else 'unqualified',
                            'infrastructure_status': checks['shadow-preflight']['status'],
                            'blockers': checks['shadow-preflight']['blockers'], 'fault_injected': False},
        'limits': ['Snapshot TP1 same-node only', 'Sidecar vLLM aggregated only', 'KVCR peer reuse only',
                   'Grove basic gang admission/scaling only'],
        'snapshot_artifact': measurements['artifact'], 'snapshot_bytes': measurements['logical_bytes']}}
    (ROOT / 'configs/common-runtime-qualified.json').write_text(json.dumps(qualified, indent=2) + '\n')
    candidate.update(status='qualified', qualification=qualified['qualification']['scope'],
                     qualification_run=qualified['qualification']['run'])
    candidate_path.write_text(json.dumps(candidate, indent=2) + '\n')
    run.result('common-qualification', 'passed', image=lock['runtime_image'],
               lock='configs/common-runtime-qualified.json', scope=qualified['qualification']['scope'],
               shadow_failover_status=checks['shadow-preflight']['status'])


def test(run, feature):
    if not lock_model(run).get('common_runtime'):
        raise ValueError('This harness is for a frozen common-image run only')
    if feature == 'probe':
        return probe(run)
    if run.state.get('checks', {}).get('common-runtime-probe', {}).get('status') != 'passed':
        raise ValueError('Complete common-image GPU/EFA/entrypoint probe first')
    if feature in ('agg', 'disagg'):
        from serving_tests import deploy
        from request_tests import routing, disagg
        deploy(run, feature)
        smoke(run, feature)
        routing(run) if feature == 'agg' else disagg(run)
        stop(run, ['ft-' + feature])
    elif feature == 'mx':
        from modelexpress_tests import deploy, verify
        efa(run)
        deploy(run)
        deploy(run, target=True)
        verify(run)
        stop(run, ['ft-mx-target', 'ft-mx'])
    elif feature == 'sidecar':
        from sidecar_tests import deploy, verify
        deploy(run)
        smoke(run, 'sidecar')
        verify(run)
        stop(run, ['ft-sidecar'])
    elif feature == 'kvcr':
        from kvcr_tests import deploy, verify
        from upgrade_retests import canary_stability
        run.state['kvcr_canary_timeout'] = 180
        run.save()
        efa(run)
        deploy(run)
        smoke(run, 'kvcr')
        verify(run)
        canary_stability(run)
        stop(run, ['ft-kvcr'])
    elif feature == 'shadow-runtime':
        from shadow_failover_tests import runtime, preflight
        runtime(run)
        if run.state['checks'].get('shadow-runtime', {}).get('status') != 'present':
            raise RuntimeError('Common candidate is missing Shadow/GMS runtime entrypoints')
        preflight(run)
    elif feature == 'grove':
        from grove_tests import test as grove
        grove(run)
        stop_grove(run)
    else:
        from snapshot_runtime_tests import test as preparation
        from snapshot_tests import deploy, verify, cleanup
        from snapshot_diagnostics import collect_resources
        prepared = run.state.get('checks', {}).get('snapshot-runtime-preparation')
        if prepared is None:
            preparation(run)
        elif prepared.get('status') != 'passed':
            raise ValueError('Snapshot runtime preparation failed; resolve and rerun it before attempting capture')
        if lock_model(run).get('tensor_parallel_size', 1) > 1:
            from snapshot_launch_probe import probe as launch_probe
            if not launch_probe(run)['job_file_created']:
                raise RuntimeError('TP2 Snapshot requires a CUDA launch-job file; installed driver/tool does not support it. See snapshot-launch-probe.json')
        deploy(run)
        verify(run, observer=collect_resources)
        from snapshot_measurements import measure
        measure(run)
        from snapshot_diagnostics import collect
        collect(run)
        from snapshot_resource_summary import summarize
        summarize(run)
        cleanup(run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'probe', 'agg', 'disagg', 'mx', 'sidecar', 'kvcr', 'snapshot', 'shadow-runtime', 'grove', 'cleanup', 'status', 'record'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--build-run', type=Path)
    parser.add_argument('--inventory', type=Path, help='Completed final read-only inventory for record')
    args = parser.parse_args()
    run = Run(args.run)
    if args.action == 'prepare':
        if not args.build_run:
            parser.error('prepare requires --build-run')
        prepare(run, args.build_run)
    elif args.action == 'cleanup':
        stop(run, ['ft-agg', 'ft-disagg', 'ft-sidecar', 'ft-kvcr', 'ft-mx-target', 'ft-mx', 'ft-snapshot'])
        stop_grove(run)
        run.result('common-cleanup', 'passed', scope='Owned candidate DGDs and their workload Pods removed')
    elif args.action == 'status':
        from serving_tests import status
        status(run, brief=True)
    elif args.action == 'record':
        record_qualification(run, args.inventory)
    else:
        try:
            test(run, args.action)
            run.result('common-' + args.action, 'passed',
                       scope='Bounded candidate action completed; associated feature receipts specify qualification limits')
        except Exception as error:
            run.result('common-' + args.action, 'failed', error=str(error))
            raise


if __name__ == '__main__':
    main()
