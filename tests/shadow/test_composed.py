"""Offline full-reader composition gates; no writer/reader success is simulated."""
import copy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.source_paths import source_path
import demos.shadow.composed as full


class FullShadowTests(unittest.TestCase):
    def basis(self):
        identity = {'candidate': 'writer', 'tensor_parallel_size': 2}
        serving = {'status': 'passed', 'worker_uid': 'pod', 'container_ids': {'main': 'writer', 'gms-server': 'gms'}}
        state = {'checks': {'shadow-writer-serving': serving,
            'shadow-writer-descriptors': {'status': 'passed', 'updated_at': '3'},
            'shadow-writer-qualification': {'status': 'passed', 'new_xids': []},
            'shadow-writer-cleanup': {'status': 'passed', 'updated_at': '5'}}}
        observed = {'pod_uid': 'pod', 'allocation': {'container_ids': serving['container_ids']},
            'gms': {'weights': {'state': {'memory_layout_hash': 'a' * 64}}}}
        provenance = {'before': observed, 'after': copy.deepcopy(observed)}
        counts = {'humming-linear': 80, 'humming-moe': 40, 'cutlass-fp8': 8, 'modelopt-attention': 4}
        manifests = {str(rank): {'version': full.VERSION, 'identity': dict(identity, tp_rank=rank),
            'reader_ready': True, 'unhandled_modules': {}, 'gms_memory_layout_hash': 'a' * 64,
            'counts': counts, 'modules': {owner: {'kind': 'humming-moe',
                'layer_class': full.descriptors.ROUTED_EXPERTS,
                'quant_method_class': full.descriptors.MODEL_OPT + ':ModelOptNvFp4FusedMoE',
                'experts_class': next(iter(full.descriptors.MOE_EXPERTS)),
                'parameters': {'e_score_correction_bias': {'shape': [512], 'stride': [1],
                    'dtype': 'torch.float32', 'requires_grad': True, 'attrs': {}, 'offset_bytes': 0,
                    'allocation_id': 'bias-fixture', 'inference_role': full.descriptors.routing_bias_role(owner, 'e_score_correction_bias')}}}
                for owner in full.descriptors.ROUTING_BIAS_OWNERS}} for rank in (0, 1)}
        capture = {str(rank): {'reader_ready': True} for rank in (0, 1)}
        return {'descriptor_identity': identity}, state, manifests, capture, provenance, {'receipt': {'observed_at': '4'}}

    def test_complete_writer_evidence_can_supply_a_reader_basis(self):
        self.assertEqual(full.validate_basis(*self.basis())['modelopt-attention'], 4)

    def test_missing_writer_or_descriptor_or_health_gate_is_refused(self):
        for key in ('shadow-writer-serving', 'shadow-writer-descriptors', 'shadow-writer-qualification', 'shadow-writer-cleanup'):
            values = self.basis()
            values[1]['checks'][key]['status'] = 'pending'
            with self.subTest(gate=key), self.assertRaises(ValueError): full.validate_basis(*values)
        values = self.basis()
        values[-1]['receipt']['observed_at'] = '2'
        with self.assertRaisesRegex(ValueError, 'predates descriptor capture'): full.validate_basis(*values)

    def test_incomplete_or_foreign_rank_manifest_is_refused(self):
        for change in ('unsupported', 'rank', 'layout', 'reader_ready'):
            values = self.basis()
            value = values[2]['1']
            if change == 'unsupported': value['unhandled_modules'] = {'new': {}}
            elif change == 'rank': value['identity']['tp_rank'] = 0
            elif change == 'layout': value['gms_memory_layout_hash'] = 'b' * 64
            else: value['reader_ready'] = False
            with self.subTest(change=change), self.assertRaises(ValueError): full.validate_basis(*values)

    def test_capture_generation_mismatch_is_refused(self):
        values = self.basis()
        values[4]['after']['pod_uid'] = 'replacement'
        with self.assertRaisesRegex(ValueError, 'stable serving-generation'): full.validate_basis(*values)

    def test_freeze_refuses_incomplete_actual_writer_before_creating_a_run(self):
        with self.collected_fixture() as fixture:
            before = (fixture.original / 'state.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'composition gate is incomplete'):
                full.qualified_basis(fixture.original)
            self.assertEqual((fixture.original / 'state.json').read_bytes(), before)

    @contextmanager
    def collected_fixture(self):
        """Synthetic proof bytes only; no Run, network, cluster or GPU is used."""
        implementations = {name: (source_path(name, root=full.ROOT)).read_bytes() for name in
            ('workshop_shadow_descriptors_v4.py', 'workshop_shadow_parameter_inventory.py')}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            original, collection = root / 'results/writer', root / 'results/collected'
            original.mkdir(parents=True); collection.mkdir()
            namespace = 'dynamo-ft-r610-' + hashlib.sha256(str(original).encode()).hexdigest()[:8] + '-demo'
            def save(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(value, bytes): path.write_bytes(value)
                else: path.write_text(json.dumps(value, indent=2) + '\n')
            canonical = root / 'configs/model-lock.json'
            save(canonical, {'model': 'fixture'})
            model_lock = {'model': 'fixture', 'runtime_image': 'fixture@sha256:' + 'f' * 64}
            save(original / 'model-lock.json', model_lock)
            spec, state, manifests, capture, provenance, health = self.basis()
            source_snapshot = {}
            for name, content in implementations.items():
                save(source_path(name, root=root), content)
                save(original / 'source-snapshot' / name, content)
                source_snapshot[name] = full.ui.digest(original / 'source-snapshot' / name)
            contracts = {'vllm/fixture.py': hashlib.sha256(b'fixture source').hexdigest()}
            save(original / 'runtime-contract-sources/vllm/fixture.py', b'fixture source')
            save(original / 'source-contract-manifest.json', {'files': contracts})
            identity = dict(spec['descriptor_identity'], source_manifest_sha256=full.ui.digest(original / 'source-contract-manifest.json'))
            overlay = {'workshop_descriptors.py': implementations['workshop_shadow_descriptors_v4.py'].decode(),
                'workshop_parameter_inventory.py': implementations['workshop_shadow_parameter_inventory.py'].decode()}
            save(original / 'runtime-overlay.json', {'data': overlay})
            for name, content in overlay.items(): save(original / name, content.encode())
            save(original / 'deployment.json', {'spec': {'components': []}})
            save(original / 'deployment.yaml', b'fixture executable manifest\n')
            config = root / 'configs/dgd/workshop-shadow-descriptor-writer/writer/deployment.yaml'
            save(config, (original / 'deployment.yaml').read_bytes())
            spec.update(profile=full.instrumented.PROFILE, descriptor_version=full.VERSION,
                descriptor_identity=identity, namespace=namespace, reader_enabled=False, intentional_fault=False,
                node=full.NODE, gpu_uuids=list(full.UUIDS), source_snapshot=source_snapshot,
                runtime_contract_hashes=contracts, config_manifest=str(config), config_manifest_sha256=full.ui.digest(config),
                model_lock_sha256=full.ui.digest(canonical),
                overlay_sha256=hashlib.sha256(json.dumps(overlay, sort_keys=True).encode()).hexdigest())
            spec['inputs'] = {name: full.ui.digest(original / name) for name in
                ('runtime-overlay.json', 'source-contract-manifest.json', 'deployment.json', 'deployment.yaml',
                 'workshop_descriptors.py', 'workshop_parameter_inventory.py')}
            save(original / 'descriptor-writer-spec.json', spec)
            state.update(owner='kubecon-dynamo-feature-tests', namespace=namespace, model_lock=model_lock,
                shadow_writer_profile=full.instrumented.PROFILE,
                shadow_descriptor_spec_sha256=full.ui.digest(original / 'descriptor-writer-spec.json'))
            initial = copy.deepcopy(state); initial['checks'] = {'shadow-writer-preparation': {'status': 'passed'}}
            save(original / 'state.json', initial)
            immutable = {str(path.relative_to(original)): full.ui.digest(path) for path in original.rglob('*')
                if path.is_file() and path.name != 'state.json'}
            plan = {'run': 'results/writer', 'logical_root': str(root), 'namespace': namespace,
                'reader_enabled': False, 'intentional_fault': False, 'immutable_run_sha256': immutable}
            save(original / 'writer-remote-package/plan.json', plan)
            plan_hash = full.ui.digest(original / 'writer-remote-package/plan.json')
            save(original / 'writer-remote-package/payload-manifest.json', {'name': 'fixture-controller', 'plan_sha256': plan_hash})
            source = collection / 'run'; shutil.copytree(original, source)
            for rank in (0, 1):
                manifests[str(rank)]['identity'] = dict(identity, tp_rank=rank)
                save(source / 'rank-manifests' / ('rank-' + str(rank) + '.json'), manifests[str(rank)])
                capture[str(rank)]['manifest_sha256'] = full.ui.digest(source / 'rank-manifests' / ('rank-' + str(rank) + '.json'))
            for name, value in {'state.json': state, 'descriptor-capture.json': capture,
                    'descriptor-capture-provenance.json': provenance, 'health-before.json': {}, 'health-after.json': health,
                    'coding-responses.json': [], 'private-lock-proof.json': [], 'gms-after.json': {},
                    'writer-remote-exit.json': {'status': 'qualified_and_cleaned_pending_root_audit',
                        'cleanup': 'passed', 'reader_enabled': False, 'intentional_fault': False}}.items():
                save(source / name, value)
            files = {str(path.relative_to(collection)): {'bytes': path.stat().st_size, 'sha256': full.ui.digest(path)}
                for path in source.rglob('*') if path.is_file()}
            save(collection / 'collection-manifest.json', {'run': 'results/writer', 'controller_name': 'fixture-controller',
                'plan_sha256': plan_hash, 'docker_state': {'Running': False, 'ExitCode': 0}, 'files': files})
            save(collection / 'collection-verification.json', {'status': 'verified', 'state_adopted': False,
                'run': 'results/writer', 'controller_name': 'fixture-controller', 'plan_sha256': plan_hash,
                'files': len(files), 'archive_sha256': '0' * 64})
            with patch.object(full, 'ROOT', root), patch.object(full.ui, 'MODEL_LOCK', canonical):
                audit = collection / 'root-audit.json'
                save(audit, dict(schema=1, kind='shadow-writer-basis-root-audit', status='passed',
                    **full.writer_basis_binding(source)))
                yield SimpleNamespace(root=root, original=original, source=source, collection=collection,
                    audit=audit, save=save, state=state, spec=spec)

    def test_verified_collected_basis_is_read_only_and_original_state_is_not_adopted(self):
        with self.collected_fixture() as fixture:
            original = (fixture.original / 'state.json').read_bytes()
            collected = (fixture.source / 'state.json').read_bytes()
            with patch.object(full, 'Run', side_effect=AssertionError('Run construction would adopt/mutate state')), \
                    patch.object(full.instrumented, 'load', side_effect=AssertionError('Writer load mutates state')):
                basis, spec, receipts, counts = full.qualified_basis(fixture.source, fixture.audit)
            self.assertTrue(basis.collected); self.assertEqual(basis.original_path, fixture.original)
            self.assertEqual(counts['humming-moe'], 40)
            self.assertIn('root-acceptance.json', receipts)
            self.assertEqual((fixture.original / 'state.json').read_bytes(), original)
            self.assertEqual((fixture.source / 'state.json').read_bytes(), collected)
            self.assertFalse((fixture.source / '.state.lock').exists())

    def test_collection_requires_explicit_exact_root_acceptance(self):
        with self.collected_fixture() as fixture:
            with self.assertRaisesRegex(ValueError, 'separate accepted root audit'):
                full.qualified_basis(fixture.source)
            audit = json.loads(fixture.audit.read_text()); audit['files']['state.json'] = 'wrong'
            fixture.save(fixture.audit, audit)
            with self.assertRaisesRegex(ValueError, 'exact collected bytes'):
                full.qualified_basis(fixture.source, fixture.audit)

    def test_changed_collection_input_or_original_config_is_refused(self):
        for target in ('collection-state', 'original-config'):
            with self.subTest(target=target), self.collected_fixture() as fixture:
                if target == 'collection-state':
                    (fixture.source / 'state.json').write_text('{}')
                    expected = 'collection changed'
                else:
                    Path(fixture.spec['config_manifest']).write_text('changed')
                    expected = 'config path/model lock/effective manifest'
                with self.assertRaisesRegex(ValueError, expected):
                    full.qualified_basis(fixture.source, fixture.audit)

    def test_v4_basis_rejects_unreviewed_correction_role_or_backend(self):
        for field in ('requires_grad', 'shape', 'inference_role', 'experts_class'):
            values = self.basis(); manifest = values[2]['0']
            owner = sorted(full.descriptors.ROUTING_BIAS_OWNERS)[0]
            row = manifest['modules'][owner]
            if field == 'experts_class': row[field] = 'unreviewed:Expert'
            else:
                layout = row['parameters']['e_score_correction_bias']
                if field == 'requires_grad': layout[field] = False
                elif field == 'shape': layout[field] = [512.0]
                else: layout[field]['gate_parameter'] += '_wrong'
            with self.subTest(field=field), self.assertRaises(ValueError):
                full.validate_basis(*values)

    def test_freeze_without_collected_root_acceptance_creates_no_candidate(self):
        with self.collected_fixture() as fixture:
            candidate = fixture.root / 'results/not-created'
            with patch.object(full, 'Run', side_effect=AssertionError('Incomplete source must fail before Run')):
                with self.assertRaisesRegex(ValueError, 'separate accepted root audit'):
                    full.freeze(candidate, fixture.source)
            self.assertFalse(candidate.exists())

    def test_original_remote_gpu_reservation_blocks_full_freeze_after_acceptance(self):
        with self.collected_fixture() as fixture:
            lease = fixture.root / '.local' / (fixture.state['namespace'] + '-writer-remote.gpu-lease')
            lease.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'close the original writer GPU reservation'):
                full.qualified_basis(fixture.source, fixture.audit)

    def test_live_source_release_uses_frozen_collected_cleanup_proof_and_empty_namespace(self):
        with self.collected_fixture() as fixture:
            demo = object.__new__(full.ComposedShadowDemo)
            demo.path = fixture.root / 'results/full-fixture'
            proof = demo.path / 'writer-basis/state.json'
            proof.parent.mkdir(parents=True)
            proof.write_bytes((fixture.source / 'state.json').read_bytes())
            demo.spec = {'source_writer_run': str(fixture.original),
                'source_writer_namespace': fixture.state['namespace'],
                'writer_basis_receipts': {'state.json': full.ui.digest(proof)}}
            queries = []
            def empty(*args):
                queries.append(args)
                return {'items': []}
            demo.run = SimpleNamespace(get=empty)
            original = (fixture.original / 'state.json').read_bytes()
            demo.source_released()
            self.assertEqual({args[1] for args in queries}, {'pods', 'resourceclaims'})
            self.assertEqual((fixture.original / 'state.json').read_bytes(), original)
            self.assertNotIn('shadow-writer-cleanup', json.loads(original)['checks'])
            proof.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Frozen writer cleanup proof changed'):
                demo.source_released()

    def test_live_remaining_source_claim_blocks_full_gpu_probe(self):
        with self.collected_fixture() as fixture:
            demo = object.__new__(full.ComposedShadowDemo)
            demo.path = fixture.root / 'results/full-fixture'
            proof = demo.path / 'writer-basis/state.json'
            proof.parent.mkdir(parents=True)
            proof.write_bytes((fixture.source / 'state.json').read_bytes())
            demo.spec = {'source_writer_namespace': fixture.state['namespace'],
                'writer_basis_receipts': {'state.json': full.ui.digest(proof)}}
            demo.run = SimpleNamespace(get=lambda *args: {'items': [{'name': 'live-claim'}] if args[1] == 'resourceclaims' else []})
            with patch.object(full.writer, 'probe') as gpu_probe:
                with self.assertRaisesRegex(ValueError, 'Source writer still owns live'):
                    demo.probe()
                gpu_probe.assert_not_called()

    def test_full_graph_adds_failover_discovery_and_preserves_exact_serving_profile(self):
        template, _ = full.presenter.render('old', full.ui.read_json(full.ui.MODEL_LOCK))
        writer = full.instrumented.render_graph(template, 'writer', 'writer-overlay', {'candidate': 'writer'})
        graph = full.render_graph(writer, 'full', 'full-overlay', {'candidate': 'full'})
        self.assertEqual(graph['metadata']['name'], full.GRAPH)
        self.assertEqual(graph['metadata']['annotations']['nvidia.com/dynamo-kube-discovery-mode'], 'container')
        worker = next(c for c in graph['spec']['components'] if c['type'] == 'worker')
        before = next(c for c in writer['spec']['components'] if c['type'] == 'worker')
        self.assertEqual(set(worker['experimental']), {'gpuMemoryService', 'failover'})
        spec, original = worker['podTemplate']['spec'], before['podTemplate']['spec']
        self.assertEqual(spec['containers'][0]['args'], original['containers'][0]['args'])
        self.assertEqual(len([v for v in spec['volumes'] if v['name'] == 'runtime-descriptors']), 1)
        env = spec['containers'][0]['env']
        self.assertEqual(len([e for e in env if e['name'] == 'DYN_WORKSHOP_SHADOW_RUNTIME_IDENTITY']), 1)
        self.assertEqual(len([e for e in env if e['name'] == 'DYN_WORKSHOP_SHADOW_DESCRIPTOR_DIR']), 1)

    def test_full_graph_refuses_combining_request_migration_with_shadow_proof(self):
        template, _ = full.presenter.render('old', full.ui.read_json(full.ui.MODEL_LOCK))
        frontend = next(c for c in template['spec']['components'] if c['type'] == 'frontend')
        next(e for e in frontend['podTemplate']['spec']['containers'][0]['env'] if e['name'] == 'DYN_MIGRATION_LIMIT')['value'] = '3'
        with self.assertRaisesRegex(ValueError, 'migration disabled'):
            full.render_graph(template, 'full', 'overlay', {})

    def test_fault_is_refused_without_actual_active_parked_reader_proof(self):
        demo = object.__new__(full.ComposedShadowDemo)
        demo.run = SimpleNamespace(state={'checks': {}})
        with self.assertRaisesRegex(ValueError, 'active/parked reader'):
            demo.failover()

    def test_ready_generation_change_is_refused_at_the_fault_verifier_snapshot(self):
        expected = {'pod_uid': 'pod', 'states': {'engine-0': 'active', 'engine-1': 'standby'},
            'container_statuses': {name: {'containerID': name, 'restartCount': 0}
                for name in ('engine-0', 'engine-1', 'gms-server')}, 'gms': {}}
        changed = copy.deepcopy(expected)
        changed['container_statuses']['gms-server']['containerID'] = 'replacement'
        with tempfile.TemporaryDirectory() as directory:
            demo = object.__new__(full.ComposedShadowDemo)
            demo.path = Path(directory)
            full.write(demo.path / 'full-ready-after.json', expected)
            demo.run = SimpleNamespace(state={'checks': {'shadow-full-ready': {'status': 'passed', 'updated_at': 'now'}}})
            demo.args, demo.data = SimpleNamespace(health_after='health'), {}
            demo.health_after = lambda *args: None
            demo.assert_graph = lambda: None
            with patch.object(full.presenter.control, 'snapshot', return_value=changed) as original, \
                    patch.object(full.presenter.ShadowDemo, 'failover', side_effect=lambda: full.presenter.control.snapshot(demo.run)):
                with self.assertRaisesRegex(ValueError, 'generation changed'):
                    demo.failover()
                self.assertIs(full.presenter.control.snapshot, original)
            self.assertFalse((demo.path / 'shadow-fault-intent.json').exists())

    def test_recreated_same_label_dgd_is_refused(self):
        demo = object.__new__(full.ComposedShadowDemo)
        demo.ns = 'owned'
        graph = {'metadata': {'uid': 'replacement', 'generation': 1,
            'labels': {'feature-test-run': 'owned'}}, 'spec': {}}
        demo.run = SimpleNamespace(state={'shadow_full_dgd_uid': 'original'}, get=lambda *args: graph)
        with self.assertRaisesRegex(ValueError, 'DGD identity'):
            demo.assert_graph()

    def test_standby_or_gms_replacement_after_baseline_refuses_fault_intent(self):
        for target in ('engine-1', 'gms-server'):
            expected = {'pod_uid': 'pod', 'states': {'engine-0': 'active', 'engine-1': 'standby'},
                'container_statuses': {name: {'containerID': name, 'restartCount': 0}
                    for name in ('engine-0', 'engine-1', 'gms-server')}, 'gms': {}}
            changed = copy.deepcopy(expected)
            changed['container_statuses'][target]['containerID'] = 'replacement'
            with self.subTest(container=target), tempfile.TemporaryDirectory() as directory:
                demo = object.__new__(full.ComposedShadowDemo)
                demo.path = Path(directory)
                full.write(demo.path / 'full-ready-after.json', expected)
                demo.run = SimpleNamespace(path=demo.path, state={'checks': {
                    'shadow-full-ready': {'status': 'passed', 'updated_at': 'now'}}})
                demo.args, demo.data = SimpleNamespace(health_after='health'), {}
                demo.health_after = lambda *args: None
                demo.assert_graph = lambda: None
                def baseline_then_intent():
                    full.presenter.control.snapshot(demo.run)
                    full.presenter.control.write(demo.run, 'shadow-fault-intent.json', {})
                with patch.object(full.presenter.control, 'snapshot', side_effect=[expected, changed]), \
                        patch.object(full.presenter.ShadowDemo, 'failover', side_effect=baseline_then_intent):
                    with self.assertRaisesRegex(ValueError, 'generation changed'):
                        demo.failover()
                self.assertFalse((demo.path / 'shadow-fault-intent.json').exists())

    def test_final_kill_boundary_rechecks_all_container_ids_without_cuda_probes(self):
        expected = {'pod_uid': 'pod', 'container_statuses': {name: {'containerID': name, 'restartCount': 0}
            for name in ('engine-0', 'engine-1', 'gms-server')}}
        for target in ('engine-1', 'gms-server'):
            pod = {'metadata': {'uid': 'pod'}, 'status': {'containerStatuses': [
                {'name': name, 'containerID': 'replacement' if name == target else name, 'restartCount': 0}
                for name in ('engine-0', 'engine-1', 'gms-server')]}}
            with self.subTest(container=target), self.assertRaisesRegex(ValueError, 'mutation boundary'):
                full.validate_boundary_pod(expected, pod)


if __name__ == '__main__': unittest.main()
