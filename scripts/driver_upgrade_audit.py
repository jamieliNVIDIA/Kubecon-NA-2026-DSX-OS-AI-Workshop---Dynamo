#!/usr/bin/env python3
"""Record final node, Helm, DRA, health-condition and test-cleanup upgrade evidence."""
import argparse
import json
import re
from pathlib import Path
import time
from prepare_driver_upgrade import CLIENT_LABEL, SENTINEL_LABEL, SKIP_LABEL, TARGET_VERSION, helm_base
from apply_driver_upgrade import node_healthy, observe, ready_pod, verify_bundle
from testlib import Run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--cleanup-build-probe', action='store_true')
    args = parser.parse_args()
    run = Run(args.run)
    lock = verify_bundle(args.bundle.resolve())
    if args.cleanup_build_probe:
        pod = run.k('get', 'pod', 'r610-build-probe', '-n', run.ns, '-o', 'json', check=False)
        if pod.returncode == 0:
            if json.loads(pod.stdout)['metadata'].get('labels', {}).get('feature-test-run') != run.ns:
                raise ValueError('Build probe is not owned')
            run.k('delete', 'pod', 'r610-build-probe', '-n', run.ns, '--wait=true', '--timeout=90s', timeout=105)
        elif 'NotFound' not in pod.stderr:
            raise RuntimeError(pod.stderr)
    before = json.loads((run.path / 'driver-baseline-nodes.json').read_text())['items']
    old = {n['metadata']['name']: n for n in before}
    after = run.get('get', 'nodes')['items']
    observed = observe(run, lock)
    report = {'target_driver': TARGET_VERSION, 'nodes': [], 'blockers': []}
    target = json.loads((run.path / 'target-image.json').read_text())[0]
    allowed = {target['digest']} | {p['digest'] for p in target['platforms']
                                    if p['platform'].get('architecture') == 'amd64'}
    if set(observed) != set(lock['nodes']):
        report['blockers'].append('Node set changed')
    for node in after:
        name = node['metadata']['name']
        baseline = old[name]
        labels = node['metadata']['labels']
        conditions = [c for c in node['status']['conditions'] if c['type'].startswith(('Gpu', 'SysLogs')) and c['status'] == 'True']
        old_conditions = {c['type']: c['status'] for c in baseline['status']['conditions']}
        entry = {'node': name, 'driver': labels.get('nvidia.com/cuda.driver-version.full'),
            'kernel': node['status']['nodeInfo']['kernelVersion'],
            'boot_id_unchanged': node['status']['nodeInfo']['bootID'] == baseline['status']['nodeInfo']['bootID'],
            'uid_unchanged': node['metadata']['uid'] == baseline['metadata']['uid'],
            'healthy_rollout': node_healthy(observed[name]),
            'efa_allocatable': node['status']['allocatable'].get('vpc.amazonaws.com/efa'),
            'efa_count_unchanged': node['status']['allocatable'].get('vpc.amazonaws.com/efa') == baseline['status']['allocatable'].get('vpc.amazonaws.com/efa'),
            'labels_restored': all(labels.get(k) == v for k, v in lock['nodes'][name]['labels'].items()),
            'client_deploy_labels_restored': all(labels.get(k) == v for k, v in baseline['metadata']['labels'].items()
                                                if k.startswith('nvidia.com/gpu.deploy.')),
            'preexisting_health_conditions': [c['type'] for c in conditions if old_conditions.get(c['type']) == 'True'],
            'new_health_conditions': [c['type'] for c in conditions if old_conditions.get(c['type']) != 'True']}
        driver_pods = observed[name]['driver_pods']
        entry['driver_image_id'] = driver_pods[0]['image_ids'].get('nvidia-driver-ctr') if len(driver_pods) == 1 else None
        entry['driver_digest_matches_build'] = bool(entry['driver_image_id'] and entry['driver_image_id'].split('@')[-1] in allowed)
        entry['driver_label_matches'] = entry['driver'] == TARGET_VERSION
        cuda = run.state['checks'].get('driver-cuda-' + name, {})
        entry['cuda_check_passed'] = (cuda.get('status') == 'passed' and cuda.get('driver') == TARGET_VERSION
                                      and cuda.get('gpu_count') == 8)
        log = run.path / ('driver-cuda-' + name.rsplit('-', 1)[-1] + '.log')
        entry['nccl_loaded_versions'] = sorted(set(re.findall(r'NCCL version (\S+)', log.read_text()))) if log.exists() else []
        report['nodes'].append(entry)
        if not all(entry[k] for k in ('boot_id_unchanged', 'uid_unchanged', 'healthy_rollout', 'labels_restored',
                'client_deploy_labels_restored', 'efa_count_unchanged', 'driver_digest_matches_build', 'driver_label_matches',
                'cuda_check_passed')) or not entry['nccl_loaded_versions'] or entry['new_health_conditions']:
            report['blockers'].append(name + ': rollout, maintenance, reboot or new health condition mismatch')
    pods = run.get('get', 'pods', '-A')['items']
    report['unready_infrastructure'] = [p['metadata']['namespace'] + '/' + p['metadata']['name'] for p in pods
        if p['metadata']['namespace'] in ('gpu-operator', 'nvidia-dra-driver', 'nvsentinel', 'dynamo-system')
        and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') and not ready_pod(p)]
    report['active_test_pods'] = [p['metadata']['namespace'] + '/' + p['metadata']['name'] for p in pods
        if p['metadata']['namespace'] == run.ns and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]
    report['claims'] = [c['metadata']['namespace'] + '/' + c['metadata']['name']
                        for c in run.get('get', 'resourceclaims', '-A')['items']]
    report['helm'] = json.loads(run.command(helm_base() + ['list', '-A', '-o', 'json']).stdout)
    for name in ('unready_infrastructure', 'active_test_pods', 'claims'):
        if report[name]:
            report['blockers'].append(name)
    report['focused_retests'] = {name: run.state['checks'].get(name, {}).get('status')
        for name in ('nixl-efa', 'shadow-claim-smoke', 'snapshot-launch-job')}
    if any(status != 'passed' for status in report['focused_retests'].values()):
        report['blockers'].append('Focused retests are incomplete')
    if run.state['checks'].get('nixl-efa', {}).get('pairs_completed') != 3:
        report['blockers'].append('All three EFA node pairs must be tested')
    (run.path / f'driver-upgrade-audit-{time.time_ns()}.json').write_text(json.dumps(report, indent=2) + '\n')
    (run.path / 'driver-upgrade-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    run.result('driver-upgrade-audit', 'blocked' if report['blockers'] else 'passed', **report)
    if report['blockers']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
