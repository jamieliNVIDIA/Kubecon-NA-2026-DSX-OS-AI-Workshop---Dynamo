"""Independent small-data checks; no model bytes, RPC or cluster execution."""
from tests.support import ROOT
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import yaml

import scripts.development.mx_cache.seed as seed
import scripts.development.mx_cache.render_server as renderer
import tests.development.mx_cache.test_seed as author


class SeedReviewTests(unittest.TestCase):
    def test_invalid_owned_ids_fail_before_any_destination_or_resource_gate(self):
        for identity in ('../escape', 'x/../../escape', '', 'UPPER', 'x' * 37):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                spec, source, snapshot, payload = author.fixture_snapshot(directory)
                spec['id'] = identity
                with self.assertRaises(ValueError):
                    seed.seed(spec, source, directory / 'cache', resource_gate=lambda *_: self.fail('Bad ID reached resource gate'))
                self.assertFalse((directory / 'cache').exists())

    def test_memory_capacity_uses_current_cgroup_usage_and_all_reserves(self):
        GiB = seed.GiB
        good = {'MemAvailable': 200 * GiB, 'memory.max': str(112 * GiB), 'memory.current': str(2 * GiB)}
        for case in ('current-usage', 'host-headroom', 'cache-limit', 'filesystem-free'):
            with self.subTest(case=case):
                memory, total, limit, free = dict(good), 70 * GiB, 96 * GiB, 100 * GiB
                if case == 'current-usage': memory['memory.current'] = str(40 * GiB)
                elif case == 'host-headroom': memory['MemAvailable'] = 127 * GiB
                elif case == 'cache-limit': total = 96 * GiB
                elif case == 'filesystem-free': free = 70 * GiB
                with patch.object(seed, 'memory_state', return_value=memory), \
                        patch.object(seed.os, 'statvfs', return_value=SimpleNamespace(f_bavail=free, f_frsize=1)), \
                        self.assertRaises(ValueError): seed.preflight('/unused', total, limit)
        with patch.object(seed, 'memory_state', return_value=good), \
                patch.object(seed.os, 'statvfs', return_value=SimpleNamespace(f_bavail=100 * GiB, f_frsize=1)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(seed.preflight('/unused', 70 * GiB, 96 * GiB), good)

    def test_git_blob_metadata_is_checked_then_relinked_to_internal_sha256_blob(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                spec, source, snapshot, payloads = author.fixture_snapshot(directory)
                name, content = 'assets/vocab.json', payloads['assets/vocab.json']
                oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
                blob = snapshot.parent.parent / 'blobs' / oid
                blob.write_bytes(content if not corrupt else b'{"b":2}')
                target = snapshot / name; target.unlink(); target.symlink_to(blob)
                cache = directory / 'cache'
                if corrupt:
                    with self.assertRaisesRegex(ValueError, 'Git-blob checksum'), contextlib.redirect_stdout(io.StringIO()):
                        seed.seed(spec, source, cache, resource_gate=lambda *_: {})
                    self.assertFalse((cache / 'mx-dev-cache-seed.json').exists())
                    self.assertFalse((cache / 'models--example--model').exists())
                else:
                    with contextlib.redirect_stdout(io.StringIO()): receipt = seed.seed(spec, source, cache, resource_gate=lambda *_: {})
                    record = receipt['files'][name]
                    self.assertEqual(record['source_blob_id'], oid)
                    self.assertEqual(record['sha256'], hashlib.sha256(content).hexdigest())
                    copied = cache / 'models--example--model/snapshots' / spec['revision'] / name
                    self.assertEqual(copied.resolve().name, record['sha256'])
                    self.assertTrue(copied.resolve().is_relative_to((cache / 'models--example--model').resolve()))

    def test_late_copy_failure_preserves_partial_stage_without_publication_or_source_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            spec, source, snapshot, payloads = author.fixture_snapshot(directory)
            content = b'late immutable asset'
            oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
            blob = snapshot.parent.parent / 'blobs' / oid; blob.write_bytes(content)
            late = snapshot / 'zz-late.json'; late.symlink_to(blob)
            rows = json.loads(spec['hf_manifest_json'])
            rows.append({'type': 'file', 'oid': oid, 'size': len(content), 'path': late.name})
            spec.update(hf_manifest_json=json.dumps(rows), hf_manifest_entries=len(rows),
                        hf_manifest_sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
            before = {str(p): p.read_bytes() for p in snapshot.parent.parent.rglob('*') if p.is_file()}
            actual_open = Path.open
            def fail_late(path, mode='r', *args, **kwargs):
                if path == late and mode == 'rb': raise OSError('synthetic late source read failure')
                return actual_open(path, mode, *args, **kwargs)
            cache = directory / 'cache'
            with patch.object(Path, 'open', fail_late), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(OSError):
                seed.seed(spec, source, cache, resource_gate=lambda *_: {})
            self.assertTrue((cache / '.mx-staging-fixture').exists())
            self.assertFalse((cache / 'models--example--model').exists())
            self.assertFalse((cache / 'mx-dev-cache-seed.json').exists())
            self.assertEqual({str(p): p.read_bytes() for p in snapshot.parent.parent.rglob('*') if p.is_file()}, before)

    def test_cli_installs_finite_deadline_and_rejects_out_of_range_values(self):
        handler = {}
        with patch.object(sys, 'argv', ['seed', '--spec', 'missing', '--source-hf-home', '/source', '--cache', '/cache', '--timeout-seconds', '7201']), \
                patch.object(seed.signal, 'alarm') as alarm, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): seed.main()
        alarm.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / 'spec.json'; spec.write_text('{}')
            def signal(signum, callback): handler['callback'] = callback
            with patch.object(sys, 'argv', ['seed', '--spec', str(spec), '--source-hf-home', '/source', '--cache', '/cache', '--timeout-seconds', '2400']), \
                    patch.object(seed.signal, 'signal', side_effect=signal), patch.object(seed.signal, 'alarm') as alarm, \
                    patch.object(seed, 'seed') as copying:
                seed.main()
            self.assertEqual([value.args[0] for value in alarm.call_args_list], [2400, 0])
            copying.assert_called_once()
            with self.assertRaises(TimeoutError): handler['callback'](seed.signal.SIGALRM, None)

    def test_fresh_render_hashes_seed_cpu_only_resources_and_read_only_init_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, _, _, _ = author.fixture_snapshot(root)
            lock = {key: spec[key] for key in ('model', 'revision', 'model_metadata_sha256')}
            lock['runtime_image'] = 'example/runtime@sha256:' + 'b' * 64
            inputs = {
                'configs/super-vl-tp2-lock.json': lock,
                'results/20261015-super-vl-tp2/state.json': {'checks': {'model-staging': {
                    'status': 'passed', 'model': spec['model'], 'revision': spec['revision'],
                    'weight_files': spec['weight_files'], 'weight_bytes': spec['weight_bytes']}}},
            }
            tree = json.loads(spec['hf_manifest_json'])
            for index in range(114 - len(tree)):
                tree.append({'type': 'file', 'path': f'asset-{index}.txt', 'size': 0,
                             'oid': hashlib.sha1(b'blob 0\0').hexdigest()})
            raw = json.dumps(tree)
            inputs['results/mx-dev-source-hf-tree-20261105-a1/receipt.json'] = {
                'http_status': 200, 'entries': len(tree), 'url': spec['hf_manifest_url'],
                'sha256': hashlib.sha256(raw.encode()).hexdigest()}
            for name, content in inputs.items():
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(content))
            (root / 'results/mx-dev-source-hf-tree-20261105-a1/tree.json').write_text(raw)
            for name in ('configs/dgd/super-vl-textonly-fast-startup/coordinator.yaml',
                         'scripts/development/mx_cache/seed.py'):
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            output = root / 'render'
            with patch.object(renderer, 'ROOT', root), patch.object(sys, 'argv', [
                    'render', '--output', str(output), '--namespace', 'dynamo-ft-fixture', '--id', 'fixture']), \
                    contextlib.redirect_stdout(io.StringIO()):
                renderer.main()
            self.check_render(output)

    def check_render(self, output):
        plan = json.loads((output / 'plan.json').read_text())
        for name, expected in plan['files_sha256'].items():
            self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), expected)
        groups = {name: yaml.safe_load((output / (name + '.yaml')).read_text())['items'] for name in ('redis', 'server')}
        cm = next(obj for obj in groups['server'] if obj['kind'] == 'ConfigMap')
        self.assertIs(cm['immutable'], True)
        self.assertEqual(cm['data']['seed.py'], (ROOT / 'scripts/development/mx_cache/seed.py').read_text())
        self.assertEqual(json.loads(cm['data']['seed-spec.json']), json.loads((output / 'seed-spec.json').read_text()))
        self.assertEqual(len(seed.hf_manifest(json.loads(cm['data']['seed-spec.json']))), 114)
        deployment = next(obj for obj in groups['server'] if obj['kind'] == 'Deployment')
        self.assertEqual(deployment['spec']['replicas'], 1)
        self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
        pod = deployment['spec']['template']['spec']
        self.assertNotIn('activeDeadlineSeconds', pod)
        self.assertNotIn('resourceClaims', pod)
        volumes = {v['name']: v for v in pod['volumes']}
        self.assertEqual(volumes['cache']['emptyDir'], {'medium': 'Memory', 'sizeLimit': '96Gi'})
        self.assertTrue(volumes['source']['persistentVolumeClaim']['readOnly'])
        init, server = pod['initContainers'][0], pod['containers'][0]
        self.assertEqual(init['args'][init['args'].index('--timeout-seconds') + 1], '2400')
        self.assertTrue(next(m for m in init['volumeMounts'] if m['name'] == 'source')['readOnly'])
        self.assertEqual({m['name'] for m in server['volumeMounts']}, {'cache'})
        for container in (init, server):
            self.assertEqual({e['name']: e['value'] for e in container['env']}['NVIDIA_VISIBLE_DEVICES'], 'void')
            self.assertEqual(container['resources']['requests']['memory'], '96Gi')
            self.assertEqual(container['resources']['limits']['memory'], '112Gi')
            self.assertFalse(any('gpu' in name.lower() for section in container['resources'].values() for name in section))
        for name in ('redis', 'server'):
            deployment = next(obj for obj in groups[name] if obj['kind'] == 'Deployment')
            service = next(obj for obj in groups[name] if obj['kind'] == 'Service')
            pod = deployment['spec']['template']['spec']
            self.assertNotIn('resourceClaims', pod)
            self.assertNotIn('activeDeadlineSeconds', pod)
            for container in pod['containers'] + pod.get('initContainers', []):
                self.assertFalse(any('gpu' in key.lower() for section in container['resources'].values() for key in section))
            labels = deployment['spec']['template']['metadata']['labels']
            self.assertTrue(all(labels[key] == value for key, value in service['spec']['selector'].items()))
            self.assertEqual(deployment['metadata']['namespace'], plan['namespace'])
            self.assertEqual(labels['mx-development-run'], plan['id'])


if __name__ == '__main__': unittest.main()
