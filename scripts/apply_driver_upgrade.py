#!/usr/bin/env python3
"""Apply the reviewed driver upgrade with explicit one-node canary gates and receipts."""
import argparse
import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from prepare_driver_upgrade import (CLIENT_LABEL, RELEASES, SENTINEL_LABEL, SKIP_LABEL,
    TARGET_VERSION, command, helm_base, sha, value_hash)
from apply_gpu_dra_upgrade import gpu_resources
from testlib import ROOT, Run


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def verify_bundle(bundle):
    lock = json.loads((bundle / 'lock.json').read_text())
    if lock['status'] != 'server-dry-run-passed' or lock['target_driver'] != TARGET_VERSION:
        raise ValueError('Requires a passed, matching driver upgrade bundle')
    for spec in lock['releases'].values():
        for key in ('chart', 'values'):
            if sha(ROOT / spec[key + '_path']) != spec[key + '_sha256']:
                raise ValueError(f'Reviewed {key} changed')
    return lock


def idle(run):
    blockers = []
    for resource in ('pods', 'resourceclaims', 'dynamographdeployments', 'computedomain'):
        for obj in run.get('get', resource, '-A')['items']:
            if obj.get('status', {}).get('phase') in ('Succeeded', 'Failed'):
                continue
            spec = obj.get('spec', {})
            if resource != 'pods' or gpu_resources(spec) or spec.get('resourceClaims'):
                blockers.append(f'{resource}/{obj["metadata"].get("namespace", "")}/{obj["metadata"]["name"]}')
    if blockers:
        raise ValueError('GPU workloads or claims appeared: ' + ', '.join(blockers))


def verify_release(run, name, spec):
    values = json.loads(run.command(helm_base() + ['get', 'values', name,
        '-n', RELEASES[name]['namespace'], '--all', '-o', 'json']).stdout)
    releases = json.loads(run.command(helm_base() + ['list', '-n', RELEASES[name]['namespace'], '-o', 'json']).stdout)
    release = next(r for r in releases if r['name'] == name)
    if (str(release['revision']) != spec['revision'] or release['chart'] != spec['chart_name']
            or release['status'] != 'deployed' or value_hash(values) != spec['before_values_hash']):
        raise ValueError(f'{name} drifted since preparation')


def label(run, node, key, value):
    arg = key + '-' if value is None else key + '=' + value
    run.k('label', 'node', node, arg, '--overwrite')


def ready_pod(pod):
    return any(c['type'] == 'Ready' and c['status'] == 'True'
               for c in pod.get('status', {}).get('conditions', []))


def observe(run, lock):
    pods = run.get('get', 'pods', '-A')['items']
    nodes = run.get('get', 'nodes')['items']
    slices = run.get('get', 'resourceslices')['items']
    result = {}
    for node in nodes:
        name = node['metadata']['name']
        if name not in lock['nodes']:
            continue
        driver = [p for p in pods if p['spec'].get('nodeName') == name
                  and p['metadata']['name'].startswith('nvidia-driver-daemonset-')]
        dra = [p for p in pods if p['spec'].get('nodeName') == name
               and p['metadata']['namespace'] == 'nvidia-dra-driver'
               and 'kubelet-plugin' in p['metadata']['name']]
        devices = {d['name'] for s in slices if s['spec'].get('nodeName') == name
                   and s['spec']['driver'] == 'gpu.nvidia.com' for d in s['spec'].get('devices', [])}
        result[name] = {'node_ready': any(c['type'] == 'Ready' and c['status'] == 'True'
             for c in node['status']['conditions']), 'unschedulable': node['spec'].get('unschedulable', False),
             'state': node['metadata']['labels'].get('nvidia.com/gpu-driver-upgrade-state'),
             'client_label': node['metadata']['labels'].get(CLIENT_LABEL),
             'driver_pods': [{'name': p['metadata']['name'], 'ready': ready_pod(p),
                 'images': [c['image'] for c in p['spec']['containers']],
                 'image_ids': {c['name']: c.get('imageID') for c in p.get('status', {}).get('containerStatuses', [])}} for p in driver],
             'dra_ready': len(dra) == 1 and ready_pod(dra[0]), 'dra_devices': len(devices)}
    write(run.path / f'driver-observation-{time.time_ns()}.json', result)
    return result


def node_healthy(value):
    return (value['node_ready'] and not value['unschedulable'] and value['state'] == 'upgrade-done'
            and value['client_label'] == 'true' and value['dra_ready'] and value['dra_devices'] == 8
            and len(value['driver_pods']) == 1 and value['driver_pods'][0]['ready']
            and f'nvcr.io/nvidia/driver:{TARGET_VERSION}-ubuntu24.04' in value['driver_pods'][0]['images'])


def diagnostics(run, node):
    stamp = str(time.time_ns())
    pods = run.get('get', 'pods', '-n', 'gpu-operator')['items']
    for pod in pods:
        name = pod['metadata']['name']
        if pod['spec'].get('nodeName') != node:
            continue
        if not name.startswith('nvidia-driver-daemonset-'):
            if not ready_pod(pod) and pod.get('status', {}).get('phase') not in ('Succeeded', 'Failed'):
                write(run.path / f'{node}-{name}-{stamp}.json', pod)
                print(name, json.dumps(pod.get('status', {})), flush=True)
                for container in pod.get('status', {}).get('initContainerStatuses', []) + pod.get('status', {}).get('containerStatuses', []):
                    if container.get('state', {}).get('running') or container.get('restartCount'):
                        result = run.k('logs', name, '-n', 'gpu-operator', '-c', container['name'], '--tail=60', check=False)
                        print(container['name'], result.stdout[-3500:], result.stderr[-300:], flush=True)
            continue
        write(run.path / f'{node}-{name}-{stamp}.json', pod)
        for container in pod['spec'].get('initContainers', []) + pod['spec']['containers']:
            result = run.k('logs', name, '-n', 'gpu-operator', '-c', container['name'],
                           '--tail=250', check=False)
            (run.path / f'{node}-{container["name"]}-{stamp}.log').write_text(result.stdout + result.stderr)
            print(container['name'], result.stdout[-3500:], result.stderr[-300:])
    result = run.k('get', 'events', '-A', '--field-selector', 'involvedObject.kind=Node,involvedObject.name=' + node,
                   '--sort-by=.lastTimestamp', check=False)
    (run.path / f'{node}-events-{stamp}.log').write_text(result.stdout + result.stderr)
    print(result.stdout[-3500:])


def monitor(run, lock, node, timeout):
    end = time.monotonic() + timeout
    previous = None
    while time.monotonic() < end:
        observation = observe(run, lock)
        value = observation[node]
        current = json.dumps(value, sort_keys=True)
        if current != previous:
            print(node, json.dumps(value), flush=True)
            previous = current
        if value['state'] == 'upgrade-failed':
            diagnostics(run, node)
            raise RuntimeError(f'{node}: upgrade controller reported failure; leave other nodes skipped')
        if node_healthy(value):
            pod = value['driver_pods'][0]['name']
            target = json.loads((run.path / 'target-image.json').read_text())[0]
            allowed = {target['digest']} | {p['digest'] for p in target['platforms']
                                            if p['platform'].get('architecture') == 'amd64'}
            actual = value['driver_pods'][0]['image_ids'].get('nvidia-driver-ctr', '').split('@')[-1]
            if actual not in allowed:
                raise ValueError(f'{node}: running driver digest differs from the validated build image: {actual}')
            checks = r'''set -euo pipefail
nvidia-smi --query-gpu=uuid,driver_version,memory.used --format=csv,noheader
nvidia-smi -q
nvidia-smi topo -m
lsmod | awk 'NR==1 || /nvidia|gdrdrv|efa/'
test "$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | grep -cx 610.57.04)" -eq 8
lsmod | grep '^gdrdrv '
'''
            checked = run.k('exec', pod, '-n', 'gpu-operator', '-c', 'nvidia-driver-ctr',
                            '--', 'bash', '-c', checks, check=False)
            (run.path / f'{node}-r610-health-{time.time_ns()}.log').write_text(checked.stdout + checked.stderr)
            if checked.returncode:
                raise RuntimeError(f'{node}: driver/Fabric/GDRCopy verification failed; inspect saved log')
            xml = run.k('exec', pod, '-n', 'gpu-operator', '-c', 'nvidia-driver-ctr', '--', 'nvidia-smi', '-q', '-x').stdout
            (run.path / f'{node}-nvidia-smi-{time.time_ns()}.xml').write_text(xml)
            root = ET.fromstring(xml)
            fabrics = []
            for gpu in root.findall('gpu'):
                fabric = gpu.find('fabric')
                if fabric is None:
                    fabric = gpu.find('gpu_fabric_info')
                fabrics.append(fabric)
            if len(fabrics) != 8 or any(f is None or f.findtext('state') != 'Completed' for f in fabrics):
                raise ValueError(f'{node}: expected completed Fabric registration on all eight GPUs')
            run.result('driver-node-' + node, 'passed', **value,
                       scope='Driver, NVSwitch Fabric, GDRCopy, node and DRA inventory; CUDA/NCCL retest separate')
            return value
        time.sleep(5)
    diagnostics(run, node)
    raise TimeoutError(f'{node}: driver rollout timed out; other nodes remain skipped')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--phase', choices=['stage', 'start', 'resume-start', 'advance', 'monitor', 'restore', 'status', 'diagnose'], required=True)
    parser.add_argument('--node')
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    lock = verify_bundle(args.bundle.resolve())
    run = Run(args.run)
    journal_path = run.path / 'driver-upgrade-journal.json'
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'started_nodes': [], 'completed_nodes': []}
    if args.phase == 'stage':
        if journal_path.exists():
            raise ValueError('Maintenance journal already exists; inspect it before continuing')
        if run.state['checks'].get('r610-module-build', {}).get('status') != 'passed':
            raise ValueError('Compile-only validation must pass first')
        idle(run)
        for name, spec in lock['releases'].items():
            verify_release(run, name, spec)
        nodes = run.get('get', 'nodes')['items']
        if {n['metadata']['name']: n['metadata']['uid'] for n in nodes} != {n: v['uid'] for n, v in lock['nodes'].items()}:
            raise ValueError('Node identities changed')
        for node in nodes:
            baseline = lock['nodes'][node['metadata']['name']]
            if node['spec'].get('unschedulable', False) != baseline['unschedulable'] or baseline['unschedulable']:
                raise ValueError('Requires the baseline schedulable nodes')
            for key, expected in baseline['labels'].items():
                if node['metadata']['labels'].get(key) != expected:
                    raise ValueError('Maintenance labels drifted since review')
        journal['maintenance_started'] = True
        write(journal_path, journal)
        for node in lock['nodes']:
            label(run, node, SKIP_LABEL, 'true')
            label(run, node, SENTINEL_LABEL, 'false')
        spec = lock['releases']['nvidia-dra-driver-gpu']
        result = run.command(command('nvidia-dra-driver-gpu', ROOT / spec['chart_path'], ROOT / spec['values_path'])
                             + ['-o', 'json'], timeout=660)
        (run.path / 'driver-applied-dra.json').write_text(result.stdout)
        run.k('rollout', 'status', 'daemonset/nvidia-dra-driver-gpu-kubelet-plugin',
              '-n', 'nvidia-dra-driver', '--timeout=300s', timeout=330)
        journal['staged'] = True
        write(journal_path, journal)
    elif args.phase in ('start', 'resume-start', 'advance'):
        if not journal.get('staged') or not args.node or args.node not in lock['nodes']:
            raise ValueError('Requires staged maintenance and an explicit reviewed node')
        if journal['started_nodes'] != journal['completed_nodes']:
            raise ValueError('Previous node has not passed rollout verification')
        if args.node in journal['started_nodes']:
            raise ValueError('Node already started')
        idle(run)
        for previous_node in journal['completed_nodes']:
            if run.state['checks'].get('driver-cuda-' + previous_node, {}).get('status') != 'passed':
                raise ValueError('Previous node needs a passing allocated CUDA/NCCL validation before advancement')
        if args.phase in ('start', 'resume-start'):
            if journal['started_nodes']:
                raise ValueError('Upgrade already started; use advance')
            spec = lock['releases']['gpu-operator']
            if args.phase == 'start':
                verify_release(run, 'gpu-operator', spec)
            else:
                # Recovery only for an interrupted Helm readiness wait while
                # all nodes stayed skipped and no driver Pod was restarted.
                current = json.loads(run.command(helm_base() + ['get', 'values', 'gpu-operator',
                    '-n', 'gpu-operator', '--all', '-o', 'json']).stdout)
                import yaml
                desired_values = yaml.safe_load((ROOT / spec['values_path']).read_text())
                releases = json.loads(run.command(helm_base() + ['list', '-n', 'gpu-operator', '-o', 'json']).stdout)
                release = next(r for r in releases if r['name'] == 'gpu-operator')
                if (current != desired_values or release['status'] != 'failed'
                        or str(release['revision']) != str(int(spec['revision']) + 1)):
                    raise ValueError('Not the known interrupted readiness wait')
                nodes = run.get('get', 'nodes')['items']
                if any(n['metadata']['labels'].get(SKIP_LABEL) != 'true' for n in nodes):
                    raise ValueError('Interrupted-wait recovery requires every node still skipped')
            result = run.command(command('gpu-operator', ROOT / spec['chart_path'], ROOT / spec['values_path'])
                                 + ['-o', 'json'], timeout=660)
            (run.path / 'driver-applied-operator.json').write_text(result.stdout)
            journal['helm_upgraded'] = True
            write(journal_path, journal)
        elif not journal.get('helm_upgraded'):
            raise ValueError('Operator upgrade has not started')
        # Save intent first, so interruption never loses which node was released.
        journal['started_nodes'].append(args.node)
        write(journal_path, journal)
        label(run, args.node, SKIP_LABEL, None)
        monitor(run, lock, args.node, args.timeout)
        journal['completed_nodes'].append(args.node)
        write(journal_path, journal)
    elif args.phase == 'monitor':
        if args.node not in journal['started_nodes']:
            raise ValueError('Node has not been released for upgrade')
        monitor(run, lock, args.node, args.timeout)
        if args.node not in journal['completed_nodes']:
            journal['completed_nodes'].append(args.node)
            write(journal_path, journal)
    elif args.phase == 'restore':
        observed = observe(run, lock)
        if (set(journal['completed_nodes']) != set(lock['nodes'])
                or not all(node_healthy(value) for value in observed.values())):
            raise ValueError('All reviewed nodes must pass before leaving maintenance')
        baseline = json.loads((ROOT / lock['run'] / 'driver-baseline-nodes.json').read_text())['items']
        old_conditions = {n['metadata']['name']: {c['type']: c['status'] for c in n['status']['conditions']}
                          for n in baseline}
        end = time.monotonic() + 300
        while True:
            unhealthy_pods = [p['metadata']['namespace'] + '/' + p['metadata']['name']
                for p in run.get('get', 'pods', '-A')['items']
                if p['metadata']['namespace'] in ('gpu-operator', 'nvidia-dra-driver', 'nvsentinel')
                and p.get('status', {}).get('phase') not in ('Succeeded', 'Failed') and not ready_pod(p)]
            new_health_errors = [(n['metadata']['name'], c['type'])
                for n in run.get('get', 'nodes')['items'] if n['metadata']['name'] in old_conditions
                for c in n['status']['conditions'] if c['type'].startswith(('Gpu', 'SysLogs'))
                and c['status'] == 'True' and old_conditions[n['metadata']['name']].get(c['type']) != 'True']
            if not unhealthy_pods and not new_health_errors:
                break
            if time.monotonic() >= end:
                raise ValueError(f'Keep maintenance active: unhealthy Pods={unhealthy_pods}, new conditions={new_health_errors}')
            print('Waiting for maintenance recovery:', unhealthy_pods, new_health_errors, flush=True)
            time.sleep(10)
        for node, baseline in lock['nodes'].items():
            if run.state['checks'].get('driver-cuda-' + node, {}).get('status') != 'passed':
                raise ValueError(f'{node}: allocated CUDA/NCCL validation is missing')
            label(run, node, SKIP_LABEL, baseline['labels'][SKIP_LABEL])
            label(run, node, SENTINEL_LABEL, baseline['labels'][SENTINEL_LABEL])
        journal['maintenance_restored'] = True
        write(journal_path, journal)
        run.result('driver-upgrade', 'passed', version=TARGET_VERSION, nodes=list(lock['nodes']),
                   scope='Operator-managed driver rollout and per-node CUDA/NCCL; feature qualification separate')
    elif args.phase == 'diagnose':
        if args.node not in lock['nodes']:
            raise ValueError('An explicit reviewed node is required')
        diagnostics(run, args.node)
    else:
        print(json.dumps(observe(run, lock), indent=2))


if __name__ == '__main__':
    main()
