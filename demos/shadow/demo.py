#!/usr/bin/env python3
"""Investigate shared model weights and promotion of a parked Shadow Engine."""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

import yaml
import demos.common.runtime as ui
import demos.common.support as support
import shadow_failover_tests as control
from demos.shadow.runtime import singleton_meta_scale

GRAPH = control.GRAPH
OWNER = 'workshop-demo-shadow'
PROFILE = 'super-vl-shadow-text-eager-v1'
NODE = 'kubecon-nke-site-cp-0124'
UUIDS = ['GPU-b896cc31-be76-0f28-2e2d-d82564b624b7',
         'GPU-a63322d6-c08e-79cb-c42a-031aeb4c1488']
# New runs use Qwen3-0.6B at TP1, the model of the October 14 and 22 controls; Super VL GMS startup is still
# blocked. WORKSHOP_SHADOW_MODEL=super-vl selects the Super VL candidate for a new run.
MODEL_ENV = 'WORKSHOP_SHADOW_MODEL'
QWEN_PROFILE = 'qwen3-0.6b-shadow-tp1-v1'
QWEN_LOCK = ui.ROOT / 'configs/qwen3-0.6b-shadow-lock.json'
QWEN_NODE = 'kubecon-nke-site-cp-0942'
QWEN_UUIDS = ['GPU-7b0cff01-e024-1e7f-5c2e-53c85b3835e4']  # gpu-1
GMS_COMPAT = ui.ROOT / 'configs/patches/shadow-gms-vllm031/manifest.json'
# Fresh request that proves Qwen recovery. Its answer to the workshop coding prompt is not qualified live yet;
# if it fails the add(a, b) check, change 'coding' to 'ready': the controls' 'Reply with exactly READY.' request.
QWEN_RECOVERY_REQUEST = 'coding'
# The feature-test preflight runs this path (the laptop's Homebrew Helm); the Linux jump host has Helm on PATH.
HOMEBREW_HELM = '/opt/homebrew/bin/helm'
STEPS = [
    ('One weight copy, two engines', 'Inspect active and standby engines sharing one GPU.'),
    ('Verify the parked standby', 'Check failover state, GPU identity, and the shared GMS weight layout.'),
    ('Lose the active engine', 'Kill one verified EngineCore; observe standby promotion and fresh inference.'),
    ('Check restored capacity', 'Inspect changed worker identity, unchanged GMS, and standby replenishment.'),
]
SUPER_VL_STEPS = [(STEPS[0][0], 'Inspect active/standby sharing on the same two GPUs.')] + STEPS[1:]
QWEN_CACHE_PROBE = '''import json,os
from pathlib import Path
lock=json.loads(os.environ['MODEL_LOCK'])
path=Path(os.environ['HF_HOME'])/'hub'/('models--'+lock['model'].replace('/','--'))/'snapshots'/lock['revision']
weights=list(path.glob('*.safetensors'))
assert len(weights)==lock['checkpoint_weight_files'] and sum(p.stat().st_size for p in weights)==lock['checkpoint_weight_bytes']
assert json.loads((path/'config.json').read_text())['model_type']==lock['config_model_type']
print(json.dumps({'model':lock['model'],'revision':lock['revision'],'weight_files':len(weights),'weight_bytes':sum(p.stat().st_size for p in weights)}))
'''


def qwen(data):
    return data.get('shadow_profile') == QWEN_PROFILE


def device_class(namespace, uuids):
    if not uuids or len(set(uuids)) != len(uuids) or any(not u.startswith('GPU-') for u in uuids):
        raise ValueError('Distinct explicit GPU UUIDs are required.')
    return {'apiVersion': 'resource.k8s.io/v1', 'kind': 'DeviceClass',
            'metadata': {'name': namespace + '-shadow', 'labels': {'feature-test-run': namespace}},
            'spec': {'selectors': [{'cel': {'expression':
                'device.driver == "gpu.nvidia.com" && '
                'device.attributes["gpu.nvidia.com"].uuid in ' + json.dumps(uuids)}}]}}


def render(namespace, lock, node=NODE, uuids=UUIDS, overlay=None):
    """Adapt the qualified intro template; operator manages the shared claim."""
    graph, _ = ui.render(namespace, lock, enable_mx=False)
    graph['metadata'] = {'name': GRAPH, 'namespace': namespace,
                         'annotations': {'nvidia.com/dynamo-kube-discovery-mode': 'container'}}
    for component in graph['spec']['components']:
        pod = component['podTemplate']
        pod['metadata']['labels'].update({'feature-test-run': namespace, 'workshop-demo': 'shadow'})
        spec, worker = pod['spec'], component['type'] == 'worker'
        main = spec['containers'][0]
        if not worker:
            # Recovery below issues fresh requests. This is separate from migration.
            main['env'].append({'name': 'DYN_MIGRATION_LIMIT', 'value': '0'})
            continue
        spec.pop('resourceClaims', None)
        main['resources'].pop('claims', None)
        for section in ('requests', 'limits'):
            main['resources'].setdefault(section, {})['nvidia.com/gpu'] = '2'
        spec['nodeSelector'] = {'kubernetes.io/hostname': node}
        component['experimental'] = {'gpuMemoryService': {
            'deviceClassName': namespace + '-shadow'}, 'failover': {}}
        main['args'] = [
            '--model', lock['model'], '--revision', lock['revision'], '--served-model-name', lock['model'],
            '--trust-remote-code', '--tensor-parallel-size', '2', '--max-model-len', '8192',
            '--max-num-seqs', '4', '--max-num-batched-tokens', '1024', '--gpu-memory-utilization', '0.65',
            '--reasoning-parser', 'nemotron_v3', '--enforce-eager', '--language-model-only',
            '--attention-backend', 'FLASHINFER', '--mamba-backend', 'flashinfer',
            '--mamba-ssm-cache-dtype', 'float16', '--mamba-cache-mode', 'align',
            '--load-format', 'gms', '--enable-sleep-mode',
        ]
        main['env'] += [{'name': 'CUDA_LAUNCH_BLOCKING', 'value': '1'},
                        {'name': 'NCCL_IB_DISABLE', 'value': '1'},
                        {'name': 'PYTHONHASHSEED', 'value': '0'}]
        if overlay:
            spec['volumes'].append({'name': 'shadow-runtime', 'configMap': {'name': overlay}})
            for name, path in [('patches.py', 'integrations/vllm/patches.py'),
                               ('module.py', 'client/torch/module.py')]:
                main['volumeMounts'].append({'name': 'shadow-runtime', 'subPath': name,
                    'mountPath': '/usr/local/lib/python3.12/dist-packages/gpu_memory_service/' + path,
                    'readOnly': True})
    return graph, device_class(namespace, uuids)


def render_qwen(namespace, lock, node=QWEN_NODE, uuids=QWEN_UUIDS, overlay=None):
    """The presenter graph with the qualified Qwen control's worker container and patches.py overlay."""
    if len(uuids) != lock['tensor_parallel_size']:
        raise ValueError('Assign exactly one GPU per Qwen TP rank.')
    graph, dc = render(namespace, lock, node, uuids)
    gpus = str(lock['tensor_parallel_size'])
    common = [{'name': name, 'value': value} for name, value in (
        ('HF_HOME', '/model-cache/feature-tests/' + lock['model_cache_run_id'] + '/hf'), ('HF_HUB_OFFLINE', '1'),
        ('HF_MODULES_CACHE', '/tmp/hf_modules'), ('VLLM_CACHE_ROOT', '/tmp/vllm-cache'),
        ('TRITON_CACHE_DIR', '/tmp/triton-cache'), ('NCCL_IB_DISABLE', '1'), ('PYTHONHASHSEED', '0'))]
    for component in graph['spec']['components']:
        pod = component['podTemplate']
        main = pod['spec']['containers'][0]
        if component['type'] != 'worker':
            main['env'] = common + [{'name': 'NVIDIA_VISIBLE_DEVICES', 'value': 'void'},
                                    {'name': 'DYN_MIGRATION_LIMIT', 'value': '0'}]
            continue
        main['workingDir'] = '/workspace/examples/backends/vllm'
        main['args'] = [
            '--model', lock['model'], '--revision', lock['revision'], '--served-model-name', lock['model'],
            '--trust-remote-code', '--tensor-parallel-size', gpus, '--max-model-len', '1024',
            '--max-num-seqs', '4', '--max-num-batched-tokens', '1024', '--gpu-memory-utilization', '0.25',
            '--enable-prefix-caching', '--block-size', '64', '--disaggregation-mode', 'agg',
            '--load-format', 'gms', '--enable-sleep-mode',
        ]
        main['env'] = common + [{'name': 'DYN_HEALTH_CHECK_REQUEST_TIMEOUT', 'value': '180'}]
        main['resources'] = {'requests': {'cpu': '4', 'memory': '64Gi', 'nvidia.com/gpu': gpus},
                             'limits': {'memory': '128Gi', 'nvidia.com/gpu': gpus}}
        if overlay:
            pod['spec']['volumes'].append({'name': 'shadow-gms-compat', 'configMap': {'name': overlay['configmap']}})
            main['volumeMounts'].append({'name': 'shadow-gms-compat', 'subPath': 'patches.py', 'readOnly': True,
                'mountPath': '/usr/local/lib/python3.12/dist-packages/gpu_memory_service/integrations/vllm/patches.py'})
            pod['metadata'].setdefault('annotations', {})['workshop.nvidia.com/shadow-gms-compat-sha256'] = overlay['sha256']
    return graph, dc


def validate_pair(observation, expected, node=NODE):
    normalize = lambda s: s if s.startswith('GPU-') else 'GPU-' + s
    for name in ('engine-0', 'engine-1'):
        if {normalize(x) for x in observation['engines'][name]['gpu_uuids']} != set(expected):
            raise ValueError('Shadow allocation differs from the assigned ' +
                             {1: 'GPU.', 2: 'GPU pair.'}.get(len(expected), 'GPUs.'))
    if observation['node'] != node:
        raise ValueError('Unexpected Shadow node.')


@contextlib.contextmanager
def local_helm(run):
    """Run the feature-test preflight's Helm call with the Helm on PATH when Homebrew's is absent."""
    original, helm = getattr(run, 'command', None), shutil.which('helm')
    if original is None or helm is None or os.path.exists(HOMEBREW_HELM):
        yield
        return
    run.command = lambda args, *rest, **options: original(
        [helm] + list(args[1:]) if args and args[0] == HOMEBREW_HELM else args, *rest, **options)
    try:
        yield
    finally:
        run.command = original


def settings_excerpt(graph):
    """Project the effective sharing and failover configuration for the talk."""
    worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
    frontend = next(c for c in graph['spec']['components'] if c['type'] != 'worker')
    main = worker['podTemplate']['spec']['containers'][0]
    args = []
    for flag in ('--tensor-parallel-size', '--load-format'):
        index = main['args'].index(flag)
        args.extend(main['args'][index:index + 2])
    if '--enable-sleep-mode' in main['args']:
        args.append('--enable-sleep-mode')
    frontend_env = frontend['podTemplate']['spec']['containers'][0]['env']
    migration = next(e['value'] for e in frontend_env if e['name'] == 'DYN_MIGRATION_LIMIT')
    return {
        'experimental': copy.deepcopy(worker['experimental']),
        'engine_args': args,
        'frontend_env': {'DYN_MIGRATION_LIMIT': migration},
        'engines': 'one active; one initialized and parked standby',
        'weights': 'one shared committed allocation per TP rank',
        'fault': 'one verified active EngineCore SIGKILL',
        'recovery': 'standby promotion; fresh requests; then replenish standby',
        'scope': 'same Pod and healthy GPUs; no live KV or stream preservation',
    }


class ShadowDemo(ui.Demo):
    """GMS/Shadow promotion on Qwen3-0.6B TP1, or the Super VL TP2 candidate; live success requires its own proof."""
    entrypoint = Path(__file__).resolve()

    def __init__(self, args):
        args = copy.copy(args)
        if args.run is None:
            args.run = ui.ROOT / 'results' / ('demo-08-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        existed = (args.run / 'demo.json').exists()
        model = os.environ.get(MODEL_ENV, 'qwen3-0.6b')
        if not existed and model not in ('qwen3-0.6b', 'super-vl'):
            raise ValueError(MODEL_ENV + ' must be qwen3-0.6b or super-vl.')
        super().__init__(args)
        self.compact_output = True
        self.lease = ui.ROOT / '.local' / (self.ns + '-shadow.gpu-lease')
        if existed:
            if self.data.get('shadow_profile') not in (PROFILE, QWEN_PROFILE):
                raise ValueError('Use a fresh Shadow run.')
            model = self.data.get('shadow_model', 'super-vl')
            if os.environ.get(MODEL_ENV, model) != model:
                raise ValueError('This Shadow run uses ' + model + '; unset ' + MODEL_ENV + ' or use a fresh run.')
            if qwen(self.data) and ui.digest(QWEN_LOCK) != self.data['shadow_lock_sha256'] and args.action != 'cleanup':
                raise ValueError('The Qwen Shadow lock changed; use a fresh run.')
            if self.data.get('cleaned_at') and args.action not in ('cleanup', 'preview') and not args.preview:
                raise ValueError('This Shadow run was cleaned up; use a fresh run.')
            return
        if model == 'qwen3-0.6b':
            lock = ui.read_json(QWEN_LOCK)
            graph, dc = render_qwen(self.ns, lock, overlay=ui.read_json(GMS_COMPAT)['patch'])
            graph['metadata']['labels'] = self.run.labels()
            settings = dict(model=lock['model'], **settings_excerpt(graph))
            settings['scope'] = 'same Pod and healthy GPU; no live KV or stream preservation'
            ui.write_json(self.path / 'model-lock.json', lock)
            body = ui.read_json(self.path / 'request.json')
            body['model'] = lock['model']
            ui.write_json(self.path / 'request.json', body)
            self.data.update(shadow_profile=QWEN_PROFILE, model=lock['model'], shadow_lock_sha256=ui.digest(QWEN_LOCK),
                             resource_note='Active + parked standby / Qwen3-0.6B TP1 / one H100, shared weights',
                             expected_node=QWEN_NODE, expected_gpu_uuids=QWEN_UUIDS)
        else:
            graph, dc = render(self.ns, ui.read_json(ui.MODEL_LOCK))
            settings = settings_excerpt(graph)
            self.data.update(shadow_profile=PROFILE,
                             resource_note='Experimental / active + parked standby / TP2 shared weights',
                             expected_node=NODE, expected_gpu_uuids=UUIDS)
        self.data.update(shadow_model=model, demo_kind='shadow', graph=GRAPH,
                         pod_selector='workshop-demo=shadow', resource_kinds='dgd',
                         log_files=['engine-0.log', 'engine-1.log', 'gms-server.log'])
        support.write_yaml(self.path / 'deployment.yaml', graph)
        ui.write_json(self.path / 'device-class.json', dc)
        support.write_yaml(self.path / 'shadow-settings.yaml', settings)
        names = ('deployment.yaml', 'device-class.json', 'shadow-settings.yaml')
        self.data['inputs'] = {name: ui.digest(self.path / name) for name in
                               names + (('model-lock.json',) if qwen(self.data) else ())}
        self.save()

    @property
    def placement(self):
        """Node and GPU UUIDs assigned to this run's model."""
        return (QWEN_NODE, QWEN_UUIDS) if qwen(self.data) else (NODE, UUIDS)

    def acquire(self):
        node, uuids = self.placement
        if not self.lease.exists():
            self.lease.mkdir()
            ui.write_json(self.lease / 'owner.json', {'owner': OWNER, 'run': str(self.path),
                'node': node, 'gpu_uuids': uuids, 'acquired_at': ui.now()})
        value = ui.read_json(self.lease / 'owner.json')
        if value.get('owner') != OWNER or value.get('run') != str(self.path) or value.get('gpu_uuids') != uuids:
            raise ValueError('Foreign scoped Shadow GPU reservation.')

    def check_inputs(self):
        for name, sha in self.data['inputs'].items():
            if ui.digest(self.path / name) != sha:
                raise ValueError('Frozen Shadow input changed: ' + name)
        for name, sha in self.data.get('runtime_overlay', {}).get('patched_sources', {}).items():
            if ui.digest(self.path / name) != sha:
                raise ValueError('Frozen Shadow runtime overlay changed: ' + name)

    def preview(self):
        print((self.path / 'shadow-settings.yaml').read_text())
        print('Full manifest: ' + str(self.path / 'deployment.yaml'))
        print('Experimental candidate. Rehearsal is simulated; no ' + ('Qwen' if qwen(self.data) else 'Super VL') +
              ' promotion claim without live proof.')

    def prepare(self):
        self.check_inputs()
        if self.data['prepared']:
            return
        if self.args.rehearsal:
            print('[REHEARSAL] Exact checkpoint and GMS runtime inspection simulated.')
        elif qwen(self.data):
            self.acquire()
            self.prepare_qwen()
        else:
            self.acquire()
            from r610_feature_retests import prepare
            prepare(self.run, self.path, 'demo')
            if self.run.ns != self.ns:
                raise ValueError('Namespace changed during preparation.')
            control.runtime(self.run)
            from snapshot_tp2_workflow import cpu_probe
            program = '''import importlib.metadata as m,json
from pathlib import Path
root=Path(m.distribution('ai-dynamo').locate_file(''))
names=['gpu_memory_service/client/torch/module.py','gpu_memory_service/integrations/vllm/patches.py']
print(json.dumps({n:(root/n).read_text() for n in names}))
'''
            sources = cpu_probe(self.run, 'shadow-source-inspect', program)
            sources.pop('image_id', None)
            directory = self.path / 'runtime-sources'
            directory.mkdir(exist_ok=True)
            for name, source in sources.items():
                (directory / Path(name).name).write_text(source)
            module = singleton_meta_scale(sources['gpu_memory_service/client/torch/module.py'])
            patch = (ui.ROOT / 'configs/patches/shadow-gms-vllm031/patches.py').read_text()
            overlay = 'shadow-runtime-' + hashlib.sha256((module + patch).encode()).hexdigest()[:12]
            self.run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap',
                'metadata': {'name': overlay}, 'immutable': True,
                'data': {'module.py': module, 'patches.py': patch}}])
            (self.path / 'patched-module.py').write_text(module)
            (self.path / 'patched-patches.py').write_text(patch)
            graph, dc = render(self.ns, ui.read_json(ui.MODEL_LOCK), overlay=overlay)
            graph['metadata']['labels'] = self.run.labels()
            support.write_yaml(self.path / 'deployment.yaml', graph)
            self.data['inputs']['deployment.yaml'] = ui.digest(self.path / 'deployment.yaml')
            self.data['runtime_overlay'] = {'configmap': overlay, 'changes': [
                'vLLM 0.31 request_memory external_weight_memory signature',
                'meta one-element scale accepts committed scalar shape'],
                'original_sources': {n: hashlib.sha256(s.encode()).hexdigest() for n, s in sources.items()},
                'patched_sources': {n: ui.digest(self.path / n) for n in ('patched-module.py', 'patched-patches.py')}}
            self.data['inputs'].update(self.data['runtime_overlay']['patched_sources'])
            self.admit(dc)
        self.data['prepared'] = True
        self.save()

    def prepare_qwen(self):
        """Mirror the Qwen control: cache PVC, pull secret, cached checkpoint, runtime source and overlay checks."""
        from common_runtime_tests import pull_secret
        from serving_tests import lock_model, model_cache_home
        from snapshot_tp2_workflow import cpu_probe
        from storage_tests import prepare as storage
        lock = lock_model(self.run)  # The run's frozen model-lock.json.
        if self.run.ns != self.ns:
            raise ValueError('Namespace changed during preparation.')
        self.run.state['model_cache_run_id'] = lock['model_cache_run_id']
        self.run.save()
        storage(self.run)
        pull_secret(self.run)
        report = cpu_probe(self.run, 'shadow-cache-check', QWEN_CACHE_PROBE, [
            {'name': 'MODEL_LOCK', 'value': json.dumps(lock)},
            {'name': 'HF_HOME', 'value': model_cache_home(self.run)}], cache=True)
        self.run.result('model-staging', 'passed', **report, scope='Reverified cached Qwen revision; no download')
        node, _ = self.placement
        with local_helm(self.run):
            infra = control.preflight(self.run)
        if infra['blockers'] or node not in infra['eligible_nodes']:
            raise RuntimeError('Shadow preflight blocked: ' + str(infra['blockers'] or [node + ' is not eligible']))
        control.runtime(self.run)
        runtime = self.run.state['checks']['shadow-runtime']
        compat = ui.read_json(GMS_COMPAT)
        patch = compat['patch']
        if (runtime['status'] != 'present' or lock['runtime_image'] != compat['runtime_image'] or
                runtime['files']['gpu_memory_service/integrations/vllm/patches.py']['sha256'] != patch['original_sha256'] or
                ui.digest(ui.ROOT / patch['path']) != patch['sha256']):
            raise ValueError('The GMS compatibility overlay does not match the installed runtime source.')
        source = (ui.ROOT / patch['path']).read_text()
        self.run.apply([{'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': patch['configmap']},
                         'immutable': True, 'data': {'patches.py': source}}])
        (self.path / 'patched-patches.py').write_text(source)
        self.data['runtime_overlay'] = {'configmap': patch['configmap'], 'changes': [
            'vLLM 0.31 request_memory external_weight_memory signature'],
            'original_sources': {'gpu_memory_service/integrations/vllm/patches.py': patch['original_sha256']},
            'patched_sources': {'patched-patches.py': ui.digest(self.path / 'patched-patches.py')}}
        self.data['inputs'].update(self.data['runtime_overlay']['patched_sources'])
        self.admit(ui.read_json(self.path / 'device-class.json'))

    def admit(self, dc):
        existing = self.run.k('get', 'deviceclass', dc['metadata']['name'], '-o', 'json', check=False)
        if existing.returncode == 0:
            actual = json.loads(existing.stdout)
            if actual['spec'] != dc['spec'] or actual['metadata'].get('labels', {}).get('feature-test-run') != self.ns:
                raise ValueError('DeviceClass exists with different ownership or GPU selection.')
        self.run.k('apply', '-f', '-', input_text=json.dumps(dc))
        for mode in ('client', 'server'):
            self.run.k('apply', '--dry-run=' + mode, '-f', str(self.path / 'deployment.yaml'))

    def prime(self):
        self.prepare()
        if self.args.rehearsal:
            print('[REHEARSAL] Prepared active + standby; timings are not measured.')
        else:
            self.acquire()
            if not self.data.get('apply_started_at'):
                self.data['apply_started_at'] = ui.now()
                self.save()
                graph = yaml.safe_load((self.path / 'deployment.yaml').read_text())
                self.run.state.setdefault('graphs', {})['shadow'] = {'name': GRAPH}
                self.run.save()
                self.run.apply([graph])
            from shadow_live_tests import wait_standby
            try:
                wait_standby(self.run, self.args.timeout)
            except Exception as error:
                self.run.result('shadow-presenter-startup', 'blocked', error=str(error),
                    fault_injected=False, scope='Startup unqualified; workload retained for diagnosis or bounded resume')
                try:
                    self.logs()
                except Exception as diagnostic:
                    ui.write_json(self.path / 'startup-log-collection-error.json', {
                        'primary_error': str(error), 'diagnostic_error': str(diagnostic), 'at': ui.now()})
                raise
            else:
                self.logs()
            observation = control.snapshot(self.run)
            node, uuids = self.placement
            validate_pair(observation, uuids, node)
            ui.write_json(self.path / 'shadow-before.json', observation)
        self.data['ready_observed_at'] = ui.now()
        self.save()

    def logs(self):
        pods = self.run.get('get', 'pods', '-n', self.ns)['items']
        ui.write_json(self.path / 'latest-pods.json', {'items': pods})
        for pod in pods:
            for c in pod['spec'].get('containers', []) + pod['spec'].get('initContainers', []):
                if c['name'] in ('engine-0', 'engine-1', 'gms-server'):
                    value = self.run.k('logs', pod['metadata']['name'], '-n', self.ns, '-c', c['name'], '--timestamps=true', check=False)
                    (self.path / (c['name'] + '.log')).write_text(value.stdout + value.stderr)

    def settings(self):
        self.show_command(['cat', str(self.path / 'shadow-settings.yaml')])
        print((self.path / 'shadow-settings.yaml').read_text())
        print('Full executable manifest: deployment.yaml. Capture/Snapshot is not involved.')

    def inspect(self):
        if not self.data.get('ready_observed_at'):
            if self.args.rehearsal:
                self.prime()
            else:
                raise ValueError('Prime and verify active/standby offstage before the live presenter; no deployment submitted.')
        if self.args.rehearsal:
            print('[REHEARSAL] engine-0 active; engine-1 parked standby; shared GMS weights (simulated).')
        else:
            value = control.snapshot(self.run)
            node, uuids = self.placement
            validate_pair(value, uuids, node)
            ui.write_json(self.path / 'shadow-before.json', value)
            print(json.dumps({'states': value['states'], 'pod_uid': value['pod_uid'],
                              'shared_gpu_uuids': uuids}, indent=2))
        print('Fresh request continuity and capacity restoration are separate questions.')

    def failover(self):
        self.check_inputs()
        self.show_command(ui.presenter_command(self.entrypoint, 'verify', '--run', str(self.path)))
        if self.args.rehearsal:
            proof = {'status': 'simulated', 'rehearsal': True, 'fault_command_to_first_verified_response_seconds': None,
                     'active_before': 'engine-0', 'active_after': 'engine-1', 'new_standby_confirmed': True}
            print('[REHEARSAL] Active EngineCore killed; standby promotion and fresh response simulated.')
        else:
            self.acquire()
            value = control.snapshot(self.run)
            node, uuids = self.placement
            validate_pair(value, uuids, node)
            with local_helm(self.run):
                infra = control.preflight(self.run)
                if infra['blockers']:
                    raise RuntimeError('Shadow preflight blocked: ' + str(infra['blockers']))
                # Retain the feature verifier's promotion/identity invariants while
                # using the same deterministic coding request as the workshop.
                from demos.snapshot.dgd import coding_request
                original_completion = control.completion
                if not qwen(self.data) or QWEN_RECOVERY_REQUEST == 'coding':
                    control.completion = coding_request
                try:
                    control.verify(self.run, min(self.args.timeout, 300), [node])
                finally:
                    control.completion = original_completion
                    self.logs()
            proof = self.run.state['checks']['shadow-failover']
        ui.write_json(self.path / 'recovery-proof.json', proof)
        print(json.dumps(proof, indent=2))

    def summary(self):
        path = self.path / 'recovery-proof.json'
        if not path.exists():
            raise ValueError('No recovery proof; do not present a passed outcome.')
        print(path.read_text())
        print('Recovery timing includes fault command and request polling. It is not a workload SLO result.')
        print('Initialized standby overhead, under-load recovery and repeated swaps remain separate measurements.')

    def require_primed(self):
        self.check_inputs()
        self.require_prepared()
        if self.args.rehearsal:
            # Offline playback has no preparation workload or live readiness proof.
            if not self.data.get('ready_observed_at'):
                self.data['ready_observed_at'] = ui.now()
                self.save()
        elif not self.data.get('ready_observed_at'):
            command = shlex.join(ui.presenter_command(self.entrypoint, 'prime', '--run', ui.repo_path(self.path)))
            raise RuntimeError('Prime and verify the active/standby pair offstage before opening the demo:\n' + command)

    def guided(self):
        self.require_primed()
        if not self.args.auto and not sys.stdin.isatty():
            raise RuntimeError('Interactive steps need a terminal; use --rehearsal --plain --auto.')
        print('Dynamo workshop · Shadow Engine · ' + ('REHEARSAL / SIMULATED / NO CLUSTER CALLS' if self.args.rehearsal else 'LIVE EXPERIMENTAL'))
        self.run_steps(STEPS if qwen(self.data) else SUPER_VL_STEPS,
                       [self.settings, self.inspect, self.failover, self.summary])

    def cleanup(self):
        if self.args.rehearsal:
            print('[REHEARSAL] Scoped cleanup simulated.')
        else:
            self.acquire()
            control.cleanup(self.run)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                pods = self.run.get('get', 'pods', '-n', self.ns)['items']
                claims = self.run.get('get', 'resourceclaims', '-n', self.ns)['items']
                if not pods and not claims:
                    break
                time.sleep(3)
            else:
                raise RuntimeError('Owned Pods/claims remain; reservation retained.')
            found = self.run.k('get', 'deviceclass', self.ns + '-shadow', '-o', 'json', check=False)
            if found.returncode == 0:
                dc = json.loads(found.stdout)
                if dc['metadata'].get('labels', {}).get('feature-test-run') != self.ns:
                    raise ValueError('Refusing foreign DeviceClass deletion.')
                self.run.k('delete', 'deviceclass', self.ns + '-shadow')
            elif 'NotFound' not in found.stderr:
                raise RuntimeError(found.stderr)
            (self.lease / 'owner.json').unlink()
            self.lease.rmdir()
        self.data['cleaned_at'] = ui.now()
        self.save()
        print('Owned Shadow workloads and reservation released; cache and evidence retained.')


def main():
    # The common presenter parser intentionally has no arbitrary mutation hooks.
    # Expose one explicit, guarded qualification action for independent captures.
    if len(sys.argv) > 1 and sys.argv[1] == 'verify':
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('action')
        parser.add_argument('--run', required=True, type=Path)
        parser.add_argument('--timeout', type=int, default=180)
        args = parser.parse_args()
        args.rehearsal = args.preview = args.plain = args.detach = False
        args.auto, args.port = True, 18008
        demo = ShadowDemo(args)
        with ui.presenter_lock(demo.path):
            demo.failover()
    else:
        support.launch(ShadowDemo, STEPS, 18008)


if __name__ == '__main__':
    main()
