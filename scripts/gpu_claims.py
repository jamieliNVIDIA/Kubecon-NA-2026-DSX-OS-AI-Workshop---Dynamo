"""Opt-in conversion of owned test GPU requests to NVIDIA DRA claims."""
import copy
import re


def convert_pod(spec, name, count=None):
    """Return claim templates; ordinary containers get distinct allocations."""
    templates = []
    for container in spec.get('containers', []) + spec.get('initContainers', []):
        resources = container.get('resources', {})
        scalar = resources.get('limits', {}).get('nvidia.com/gpu',
                    resources.get('requests', {}).get('nvidia.com/gpu', 0))
        if not int(scalar):
            continue
        amount = int(count or scalar)
        if amount <= 0:
            raise ValueError('GPU count must be positive')
        if resources.get('claims'):
            raise ValueError('Refusing mixed scalar GPU and explicit claims')
        for key in ('limits', 'requests'):
            resources.get(key, {}).pop('nvidia.com/gpu', None)
        claim = 'gpu-' + container['name']
        template = re.sub('[^a-z0-9-]', '-', f'{name}-{container["name"]}-gpus'.lower())
        if len(template) > 253:
            raise ValueError('Claim template name too long')
        resources['claims'] = [{'name': claim}]
        spec.setdefault('resourceClaims', []).append({'name': claim, 'resourceClaimTemplateName': template})
        templates.append({'apiVersion': 'resource.k8s.io/v1', 'kind': 'ResourceClaimTemplate',
            'metadata': {'name': template}, 'spec': {'spec': {'devices': {'requests': [
                {'name': 'gpu', 'exactly': {'deviceClassName': 'gpu.nvidia.com', 'count': amount}}]}}}})
    return templates


def prepare(objects, lock):
    """Return new manifests and claim templates; GMS uses operator-managed DRA."""
    converted = copy.deepcopy(objects)
    templates = []
    if lock.get('gpu_allocation') != 'dra':
        return converted, templates
    for obj in converted:
        name = obj['metadata']['name']
        if obj['kind'] == 'Pod':
            templates += convert_pod(obj['spec'], name)
        elif obj['kind'] == 'DynamoGraphDeployment':
            for component in obj['spec']['components']:
                if 'gpuMemoryService' in component.get('experimental', {}):
                    continue
                templates += convert_pod(component['podTemplate']['spec'], name + '-' + component['name'])
        elif obj['kind'] == 'PodCliqueSet':
            for clique in obj['spec']['template']['cliques']:
                templates += convert_pod(clique['spec']['podSpec'], name + '-' + clique['name'])
    return converted, templates


def verify_allocation(run, pod, container, count):
    reference = container['resources']['claims'][0]['name']
    actual = next(c['resourceClaimName'] for c in pod['status']['resourceClaimStatuses'] if c['name'] == reference)
    claim = run.get('get', 'resourceclaim', actual, '-n', run.ns)
    allocations = claim.get('status', {}).get('allocation', {}).get('devices', {}).get('results', [])
    if len(allocations) != count or any(a['driver'] != 'gpu.nvidia.com' for a in allocations):
        raise ValueError(f'Expected {count} allocated NVIDIA GPUs')
    return claim
