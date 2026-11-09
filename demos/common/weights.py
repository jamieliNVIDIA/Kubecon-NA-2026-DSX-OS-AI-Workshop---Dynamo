"""Shared ModelExpress loader/discovery settings for the first and second replica."""
from __future__ import annotations

import copy
import hashlib
import json


SOURCE_SERVICE = 'mx-source'


def worker_config(graph):
    worker = next(component for component in graph['spec']['components'] if component['type'] == 'worker')
    return copy.deepcopy(worker['podTemplate']['spec']['containers'][0])


def engine_signature(graph):
    """Bind the full worker configuration, including its ModelExpress loader."""
    return hashlib.sha256(json.dumps(worker_config(graph), sort_keys=True).encode()).hexdigest()


def configure(graph, lock, *, role='source'):
    """Enable peer weight publication/loading without changing the engine profile."""
    if role not in ('source', 'target'):
        raise ValueError('ModelExpress role must be source or target.')
    for component in graph['spec']['components']:
        if component['type'] != 'worker':
            continue
        pod = component['podTemplate']
        pod['metadata']['labels']['mx-role'] = role
        spec = pod['spec']
        container = spec['containers'][0]
        args = list(container['args'])
        if args[:3] == ['python3', '-m', 'dynamo.vllm']:
            args = args[3:]
        if '--load-format' in args:
            index = args.index('--load-format')
            del args[index:index + 2]
        container['command'] = ['bash', '/efa/entrypoint.sh']
        container['args'] = ['python3', '-m', 'dynamo.vllm'] + args + ['--load-format', 'modelexpress']
        settings = {
            'MX_METADATA_BACKEND': 'k8s-service', 'MX_K8S_SERVICE_PATTERN': SOURCE_SERVICE,
            'MX_MODEL_REVISION': lock['revision'], 'MX_NIXL_BACKEND': 'LIBFABRIC',
            'MX_P2P_METADATA': '1', 'MX_WORKER_GRPC_PORT': '6555', 'MX_METADATA_PORT': '5555',
            'MX_ARTIFACT_TRANSFER': '0', 'NCCL_IB_DISABLE': '1',
            'FI_PROVIDER': 'efa', 'FI_EFA_USE_DEVICE_RDMA': '1', 'FI_EFA_FORK_SAFE': '1',
            'FI_EFA_ENABLE_SHM_TRANSFER': '0', 'FI_HMEM_CUDA_USE_DMABUF': '1',
            'NIXL_LIBFABRIC_USE_DEVICE_RDMA': '1', 'NIXL_LOG_LEVEL': 'INFO',
        }
        container['env'] = [e for e in container.get('env', [])
                            if e['name'] not in settings and e['name'] != 'MX_WORKER_HOST']
        container['env'] += [{'name': key, 'value': value} for key, value in settings.items()]
        container['env'].append({'name': 'MX_WORKER_HOST',
                                 'valueFrom': {'fieldRef': {'fieldPath': 'status.podIP'}}})
        for kind in ('requests', 'limits'):
            container['resources'][kind]['vpc.amazonaws.com/efa'] = str(4 * lock['tensor_parallel_size'])
        spec['volumes'] = [v for v in spec['volumes'] if v['name'] != 'efa'] + [
            {'name': 'efa', 'configMap': {'name': 'efa-userspace'}}]
        container['volumeMounts'] = [v for v in container['volumeMounts'] if v['name'] != 'efa'] + [
            {'name': 'efa', 'mountPath': '/efa', 'readOnly': True}]
    return graph


def source_service(namespace, lock, labels=None):
    """Publish only the retained first replica to the ModelExpress loader."""
    return {'apiVersion': 'v1', 'kind': 'Service',
            'metadata': {'name': SOURCE_SERVICE, 'namespace': namespace, 'labels': dict(labels or {})},
            'spec': {'selector': {'mx-role': 'source', 'workshop-role': 'worker'}, 'ports': [
                {'name': 'mx-' + str(rank), 'port': 6555 + rank, 'targetPort': 6555 + rank}
                for rank in range(lock['tensor_parallel_size'])]}}
