#!/usr/bin/env python3
"""Render an attendee-owned baseline without changing a cluster or workshop locks."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Presenter GPU assignments are specific to the private workshop cluster. Load a
# separate copy of its pure renderer without evaluating that assignment, even if
# a normal workshop_demo module is already in this interpreter. Restore the
# caller's environment immediately; do not alter that module's ALLOCATION.
_allocation_environment = os.environ.pop('WORKSHOP_ALLOCATION', None)
try:
    _intro_spec = importlib.util.spec_from_file_location('take_home_intro_renderer',
                                                       ROOT / 'demos/common/runtime.py')
    intro = importlib.util.module_from_spec(_intro_spec)
    _intro_spec.loader.exec_module(intro)
finally:
    if _allocation_environment is not None:
        os.environ['WORKSHOP_ALLOCATION'] = _allocation_environment

MANAGED_BY = 'dynamo-workshop-take-home'
DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
IMAGE = re.compile(r'[^\s@]+@sha256:[0-9a-f]{64}\Z')


def validate_inputs(args):
    for label, value in (('namespace', args.namespace), ('name', args.name),
                         ('cache PVC', args.cache_pvc)):
        if not DNS_LABEL.fullmatch(value):
            raise ValueError(f'{label} must be a Kubernetes DNS label of at most 63 characters.')
    if len(args.name) > 45:
        raise ValueError('Use a deployment name of at most 45 characters for generated resource names.')
    if args.namespace in {'default', 'kube-system', 'kube-public', 'kube-node-lease', 'dynamo-system'}:
        raise ValueError('Use a dedicated attendee namespace.')
    if not IMAGE.fullmatch(args.runtime_image):
        raise ValueError('--runtime-image must end in @sha256: plus 64 lowercase hex digits.')
    if not re.fullmatch(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})', args.runtime_version):
        raise ValueError('--runtime-version must be an operator-compatible X.Y.Z version; a package prerelease suffix is not accepted by the DGD CRD.')
    if args.image_pull_secret and not DNS_LABEL.fullmatch(args.image_pull_secret):
        raise ValueError('--image-pull-secret must name an existing secret in the attendee namespace.')
    subpath = getattr(args, 'cache_subpath', None)
    if subpath is not None and (not subpath or subpath.startswith('/') or '\\' in subpath or
                                any(part in ('', '.', '..') for part in subpath.split('/')) or
                                not re.fullmatch(r'[A-Za-z0-9_./-]+', subpath)):
        raise ValueError('--cache-subpath must be a nonempty relative directory without dot segments.')
    uid = getattr(args, 'run_as_user', None)
    if uid is not None and (not isinstance(uid, int) or isinstance(uid, bool) or not 0 <= uid <= 4294967294):
        raise ValueError('--run-as-user must be a numeric UID between 0 and 4294967294.')


def labels(name, role=None):
    value = {'app.kubernetes.io/managed-by': MANAGED_BY, 'workshop-service': name}
    if role:
        value['workshop-role'] = role
    return value


def download_program(lock):
    """Prepare exact weights and check the runtime's unversioned metadata path offline."""
    metadata = {name: lock['model_metadata_sha256'][name]
                for name in ('config.json', 'tokenizer_config.json', 'model.safetensors.index.json')}
    model_spec = {'model': lock['model'], 'revision': lock['revision'],
                  'metadata': metadata, 'weight_files': lock['checkpoint_weight_files']}
    return f'''import asyncio,hashlib,json,os,subprocess,sys
from pathlib import Path
from huggingface_hub import snapshot_download
spec={model_spec!r}
model_root=Path(os.environ['HF_HOME'])/'hub'/('models--'+spec['model'].replace('/','--'))
ref=model_root/'refs/main'
def check_ref():
 if ref.exists() and (not ref.is_file() or ref.read_text().strip()!=spec['revision']):
  raise RuntimeError('Dedicated cache refs/main differs from the pinned model. Use another cache; nothing was overwritten.')
check_ref()
snapshot=Path(snapshot_download(repo_id=spec['model'],revision=spec['revision']))
expected=model_root/'snapshots'/spec['revision']
if snapshot.resolve()!=expected.resolve():
 raise RuntimeError('Download returned an unexpected revision directory')
for name,digest in spec['metadata'].items():
 if hashlib.sha256((snapshot/name).read_bytes()).hexdigest()!=digest:
  raise RuntimeError('Checkpoint metadata hash mismatch: '+name)
weights=set(json.loads((snapshot/'model.safetensors.index.json').read_text())['weight_map'].values())
if len(weights)!=spec['weight_files'] or any((snapshot/name).stat().st_size<=0 for name in weights):
 raise RuntimeError('Checkpoint weight inventory is incomplete')
check_ref()
if not ref.exists():
 ref.parent.mkdir(parents=True,exist_ok=True)
 with ref.open('x') as stream:
  stream.write(spec['revision']+'\\n')
# Registration in the pinned workshop runtime resolves model metadata without a
# revision. Check the actual implementation in a fresh offline interpreter.
probe="""import asyncio,json,os
from pathlib import Path
from dynamo.common.model_fetch import fetch_model
resolved=Path(asyncio.run(fetch_model({lock['model']!r}))).resolve()
expected=(Path(os.environ['HF_HOME'])/'hub'/{('models--' + lock['model'].replace('/', '--'))!r}/'snapshots'/{lock['revision']!r}).resolve()
if resolved!=expected:
 raise RuntimeError('Offline metadata resolution selected a different snapshot: '+str(resolved))
print(json.dumps({{'status':'passed','scope':'CPU cache preparation and metadata resolution; no GPU serving proof','model':{lock['model']!r},'revision':{lock['revision']!r},'offline':'1'}}))
"""
environment=dict(os.environ,HF_HUB_OFFLINE='1')
subprocess.run([sys.executable,'-c',probe],env=environment,check=True)
'''


def render(args):
    """Transform the qualified intro template; resulting portable profile is unqualified."""
    validate_inputs(args)
    lock = json.loads(intro.MODEL_LOCK.read_text())
    lock['runtime_image'] = args.runtime_image
    graph, claim = intro.render(args.namespace, lock)
    graph['metadata'] = {'name': args.name, 'namespace': args.namespace,
                         'labels': labels(args.name)}
    claim['metadata'] = {'name': args.name + '-gpus', 'namespace': args.namespace,
                         'labels': labels(args.name)}
    for component in graph['spec']['components']:
        role = 'worker' if component['type'] == 'worker' else 'frontend'
        component['runtimeVersionOverride'] = args.runtime_version
        pod = component['podTemplate']
        pod['metadata'] = {'labels': labels(args.name, role)}
        spec = pod['spec']
        if args.image_pull_secret:
            spec['imagePullSecrets'] = [{'name': args.image_pull_secret}]
        else:
            spec.pop('imagePullSecrets', None)
        for volume in spec['volumes']:
            if volume['name'] == 'shared-model-cache':
                volume['persistentVolumeClaim']['claimName'] = args.cache_pvc
        main = spec['containers'][0]
        if getattr(args, 'run_as_user', None) is not None:
            main.setdefault('securityContext', {})['runAsUser'] = args.run_as_user
        if getattr(args, 'cache_subpath', None):
            for mount in main.get('volumeMounts', []):
                if mount['name'] == 'shared-model-cache':
                    mount['subPath'] = args.cache_subpath
        for env in main.get('env', []):
            if env['name'] == 'HF_HOME':
                env['value'] = '/model-cache/hf'
        if role == 'worker':
            if args.gpu_mode == 'dra':
                spec['resourceClaims'][0]['resourceClaimTemplateName'] = claim['metadata']['name']
            else:
                spec.pop('resourceClaims', None)
                main['resources'].pop('claims', None)
                for key in ('requests', 'limits'):
                    main['resources'].setdefault(key, {})['nvidia.com/gpu'] = lock['tensor_parallel_size']
    service = {
        'apiVersion': 'v1', 'kind': 'Service',
        'metadata': {'name': args.name + '-http', 'namespace': args.namespace,
                     'labels': labels(args.name)},
        # The deployment controller may overwrite the conventional managed-by
        # label (Grove does). Select only application labels we own and preserve.
        'spec': {'type': 'ClusterIP', 'selector': {'workshop-service': args.name,
                                                'workshop-role': 'frontend'},
                 'ports': [{'name': 'http', 'port': 8000, 'targetPort': 8000, 'protocol': 'TCP'}]},
    }
    # The CPU-only job populates the cache before either serving component runs.
    program = download_program(lock)
    job_spec = {
        'restartPolicy': 'Never', 'automountServiceAccountToken': False,
        'containers': [{'name': 'download', 'image': args.runtime_image,
                        'command': ['python3', '-c', program],
                        'env': [{'name': 'HF_HOME', 'value': '/model-cache/hf'},
                                {'name': 'HF_HUB_OFFLINE', 'value': '0'},
                                {'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'}],
                        'resources': {'requests': {'cpu': '2', 'memory': '8Gi'},
                                      'limits': {'memory': '16Gi'}},
                        'volumeMounts': [{'name': 'cache', 'mountPath': '/model-cache'}]}],
        'volumes': [{'name': 'cache', 'persistentVolumeClaim': {'claimName': args.cache_pvc}}],
    }
    if args.image_pull_secret:
        job_spec['imagePullSecrets'] = [{'name': args.image_pull_secret}]
    if getattr(args, 'cache_subpath', None):
        job_spec['containers'][0]['volumeMounts'][0]['subPath'] = args.cache_subpath
    if getattr(args, 'run_as_user', None) is not None:
        job_spec['containers'][0]['securityContext'] = {'runAsUser': args.run_as_user}
    job = {'apiVersion': 'batch/v1', 'kind': 'Job',
           'metadata': {'name': args.name + '-download', 'namespace': args.namespace,
                        'labels': labels(args.name)},
           'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 14400,
                    'template': {'metadata': {'labels': labels(args.name)}, 'spec': job_spec}}}
    request = {'model': lock['model'], 'messages': [{'role': 'user', 'content':
        'Write a short Python function add(a, b) that returns their sum. Reply with code only.'}],
        'max_completion_tokens': 64, 'temperature': 0,
        'chat_template_kwargs': {'enable_thinking': False}}
    objects = {'deployment.yaml': graph, 'frontend-service.yaml': service, 'download-job.yaml': job}
    if args.gpu_mode == 'dra':
        objects['gpu-claim-template.yaml'] = claim
    return objects, request, lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--name', default='coding-agent')
    parser.add_argument('--runtime-image', required=True,
                        help='An accessible, Super-VL-compatible image pinned by digest; no workshop default.')
    parser.add_argument('--runtime-version', required=True,
                        help='Version accepted by your operator for this image, e.g. 1.6.0 for the workshop stack.')
    parser.add_argument('--cache-pvc', required=True, help='An existing dedicated RWX model-cache PVC.')
    parser.add_argument('--cache-subpath', help='Existing relative directory within that PVC; shared by all components.')
    parser.add_argument('--run-as-user', type=int,
                        help='Explicit UID for downloader, frontend and worker; must match cache permissions and cluster policy. Does not chown data.')
    parser.add_argument('--image-pull-secret', help='Existing registry pull secret name, if needed.')
    parser.add_argument('--gpu-mode', choices=('device-plugin', 'dra'), default='device-plugin')
    parser.add_argument('--output', type=Path, required=True, help='Fresh local directory; never overwritten.')
    args = parser.parse_args()
    objects, request, lock = render(args)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, obj in objects.items():
        (args.output / name).write_text(yaml.safe_dump(obj, sort_keys=False))
    (args.output / 'request.json').write_text(json.dumps(request, indent=2) + '\n')
    profile = {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'status': 'Render-only profile; supplied image and target cluster need live qualification.',
        'model': lock['model'], 'revision': lock['revision'], 'tensor_parallel_size': lock['tensor_parallel_size'],
        'runtime_image': args.runtime_image, 'runtime_version': args.runtime_version,
        'gpu_mode': args.gpu_mode, 'namespace': args.namespace, 'name': args.name,
        'cache_pvc': args.cache_pvc,
        'cache_subpath': args.cache_subpath,
        'run_as_user': args.run_as_user,
        'source_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (Path(__file__).resolve(), Path(intro.__file__), intro.SCRIPT, intro.TEMPLATE, intro.MODEL_LOCK,
                                       ROOT / 'demos/common/allocation.py')},
        'files_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in sorted(args.output.iterdir())}}
    (args.output / 'profile.json').write_text(json.dumps(profile, indent=2) + '\n')
    print(f'Rendered {args.output}. No Kubernetes calls were made.')
    print('Inspect profile.json and all manifests before following take-home/README.md.')


if __name__ == '__main__':
    main()
