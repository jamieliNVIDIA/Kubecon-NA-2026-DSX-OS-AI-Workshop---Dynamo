"""Metadata-only inventory and live CPU/filesystem rank rendezvous contracts."""
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import demos.shadow.parameter_inventory as inventory


class OpaqueMetadata:
    def __repr__(self):
        raise AssertionError('Metadata inventory attempted opaque/tensor repr')
    def __str__(self):
        raise AssertionError('Metadata inventory attempted opaque/tensor str')


class Parameter(OpaqueMetadata):
    """Tensor metadata double; every value/copy/pointer API is a tripwire."""
    forbidden = {'data', 'data_ptr', 'untyped_storage', 'storage', 'item', 'numpy',
                 'cpu', 'cuda', 'to', 'copy_', 'clone', 'detach', 'tolist', '__array__'}
    def __init__(self, *, dtype='torch.int32', grad=True, device='cpu', shape=(3, 2), stride=(1, 4)):
        self.dtype, self.requires_grad, self.device = dtype, grad, device
        self.shape, self._stride = shape, stride
        self.is_cuda, self.is_meta, self.layout = device.startswith('cuda'), device == 'meta', 'torch.strided'
        self.input_dim, self.output_dim = 0, None
        self.packed_factor, self._packed_factor = Fraction(3, 2), None
        self.is_transposed, self.opaque = True, OpaqueMetadata()
    def __getattribute__(self, name):
        if name in object.__getattribute__(self, 'forbidden'):
            raise AssertionError('Tensor value/copy/GPU/pointer API accessed: ' + name)
        return object.__getattribute__(self, name)
    def stride(self): return self._stride
    def storage_offset(self): return 7
    def element_size(self): return 4
    def is_contiguous(self): return False
    def __iter__(self): raise AssertionError('Tensor contents were iterated')


class Module:
    def __init__(self, parameters=None):
        self._parameters = parameters or {}
        self.quant_method = None


class Model(Module):
    def __init__(self, parameters=None, children=None):
        super().__init__(parameters)
        self.children, self.named_module_arguments = children or [], []
    def named_modules(self, *, remove_duplicate=True):
        self.named_module_arguments.append(remove_duplicate)
        yield '', self
        yield from self.children
    def named_parameters(self, *args, **kwargs):
        raise AssertionError('De-duplicating named_parameters loses aliases/None slots')


class TrackingStream(io.StringIO):
    def __init__(self):
        super().__init__(); self.flushed = []
    def flush(self):
        self.flushed.append(self.getvalue())
        super().flush()


def identity(rank, **changes):
    result = {'candidate': 'fresh-inventory-unit-fixture', 'image_sha256': 'a' * 64,
              'model_revision': 'b' * 40, 'model_config_sha256': 'c' * 64,
              'source_manifest_sha256': 'd' * 64, 'tensor_parallel_size': 2, 'tp_rank': rank}
    result.update(changes)
    return result


def events(stream):
    rows = []
    for line in stream.getvalue().splitlines():
        if not line.startswith(inventory.PREFIX): raise AssertionError('Unexpected inventory JSONL prefix')
        rows.append(json.loads(line[len(inventory.PREFIX):]))
    return rows


def live_pair(directory, models=None, *, exporter=None):
    """Only live CPU threads and private files; no Torch or network transport."""
    barrier = threading.Barrier(2)
    streams = [TrackingStream(), TrackingStream()]
    models = models or [Model({'weight': Parameter()}), Model({'weight': Parameter()})]
    def run(rank):
        barrier.wait(timeout=3)
        try:
            result = inventory.emit_writer_parameter_inventory(models[rank], identity(rank), directory,
                                                                timeout=3, stream=streams[rank])
            if exporter:
                exporter(rank, result, streams[rank])
            return {'inventory': result, 'error': None}
        except Exception as error:
            return {'inventory': None, 'error': error}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, rank) for rank in (0, 1)]
        results = [future.result(timeout=5) for future in futures]
    return results, streams


class ParameterInventoryTests(unittest.TestCase):
    def test_direct_slots_retain_tied_parameters_module_aliases_none_meta_and_exact_metadata(self):
        tied = Parameter()
        meta = Parameter(dtype='torch.bfloat16', grad=False, device='meta', shape=(0, 4), stride=(4, 1))
        scalar = Parameter(dtype='torch.float32', grad=False, shape=(), stride=())
        child = Module({'weight': tied, 'meta': meta, 'scalar': scalar})
        child.quant_method = type('QuantMethod', (), {'kernel': type('Kernel', (), {})(), 'moe_kernel': None})()
        model = Model({'root_weight': tied, 'optional': None}, [('block', child), ('block_alias', child)])
        report = inventory.parameter_inventory(model, identity(0))
        self.assertEqual(model.named_module_arguments, [False])
        rows = {row['name']: row for row in report['parameters']}
        self.assertEqual(set(rows), {'root_weight', 'optional', 'block.weight', 'block.meta', 'block.scalar',
                                     'block_alias.weight', 'block_alias.meta', 'block_alias.scalar'})
        self.assertTrue(rows['optional']['is_none']); self.assertNotIn('dtype', rows['optional'])
        self.assertIsNone(rows['root_weight']['alias_of'])
        self.assertEqual(rows['block.weight']['alias_of'], 'root_weight')
        self.assertEqual(rows['block_alias.meta']['alias_of'], 'block.meta')
        self.assertEqual(rows['block_alias.scalar']['alias_of'], 'block.scalar')
        row = rows['root_weight']
        self.assertEqual({k: row[k] for k in ('dtype', 'requires_grad', 'shape', 'stride', 'device', 'storage_offset', 'element_size')},
                         {'dtype': 'torch.int32', 'requires_grad': True, 'shape': [3, 2], 'stride': [1, 4],
                          'device': 'cpu', 'storage_offset': 7, 'element_size': 4})
        self.assertFalse(row['is_contiguous'])
        self.assertEqual(row['layout_attributes']['packed_factor'], {'type': 'fractions:Fraction', 'numerator': 3, 'denominator': 2})
        self.assertEqual(row['layout_attributes']['output_dim'], {'type': 'builtins:NoneType', 'value': None})
        self.assertEqual(row['layout_attributes']['_packed_factor'], {'type': 'builtins:NoneType', 'value': None})
        self.assertEqual(rows['block.meta']['device'], 'meta'); self.assertTrue(rows['block.meta']['is_meta'])
        self.assertEqual(rows['block.scalar']['shape'], []); self.assertEqual(rows['block.scalar']['stride'], [])
        self.assertEqual(rows['block.weight']['kernel_class'].rsplit(':', 1)[-1], 'Kernel')
        self.assertEqual(report['summary']['slots'], 8); self.assertEqual(report['summary']['parameters'], 7)
        self.assertEqual(report['summary']['none_slots'], 1); self.assertEqual(report['summary']['aliases'], 4)
        self.assertEqual(report['summary']['meta_parameters'], 2)
        self.assertEqual(report['summary']['dtypes']['torch.int32'], 3)
        self.assertEqual(report['summary']['inspection_errors'], [])
        self.assertTrue(report['metadata_only']); self.assertFalse(report['tensor_contents_read']); self.assertFalse(report['cuda_operations'])

    def test_typed_metadata_never_stringifies_unknown_objects_and_keeps_scalar_types(self):
        class Layout(Enum):
            PACKED = (Fraction(7, 3), None)
        value = inventory.typed_value(Layout.PACKED)
        self.assertEqual(value['name'], 'PACKED')
        self.assertEqual(value['value']['value'][0], {'type': 'fractions:Fraction', 'numerator': 7, 'denominator': 3})
        for raw, expected in [(True, 'builtins:bool'), (2, 'builtins:int'), (None, 'builtins:NoneType'),
                              (float('nan'), 'builtins:float'), (float('inf'), 'builtins:float')]:
            record = inventory.typed_value(raw)
            self.assertEqual(record['type'], expected); json.dumps(record, allow_nan=False)
        opaque = inventory.typed_value(OpaqueMetadata())
        self.assertTrue(opaque['value_not_read']); self.assertNotIn('value', opaque)
        parameter = Parameter(device='cuda:1'); parameter.group_size = OpaqueMetadata()
        report = inventory.parameter_inventory(Model({'cuda_metadata_double': parameter}), identity(0))
        self.assertEqual(report['summary']['cuda_parameters'], 1)
        self.assertTrue(report['parameters'][0]['layout_attributes']['group_size']['value_not_read'])
        # All Tensor content/copy/pointer/repr APIs are tripwires above. This is a
        # metadata double, not a claim that a GPU was allocated during the test.

    def test_live_cpu_ranks_flush_each_jsonl_row_and_finish_before_unchanged_exporter_guard(self):
        exporter_calls = []
        with tempfile.TemporaryDirectory() as directory:
            def strict_exporter(rank, report, stream):
                self.assertEqual(events(stream)[-1]['event'], 'all-ranks-ready')
                self.assertEqual(stream.flushed[-1], stream.getvalue())
                self.assertEqual(report['parameters'][0]['dtype'], 'torch.int32')
                self.assertIs(report['parameters'][0]['requires_grad'], True)
                for peer in (0, 1):
                    self.assertTrue((Path(directory) / f'parameter-inventory-rank-{peer}.json').is_file())
                    self.assertTrue((Path(directory) / f'parameter-inventory-ack-rank-{peer}.json').is_file())
                exporter_calls.append(rank)
                raise ValueError('unchanged strict integer/gradient exporter guard')
            results, streams = live_pair(directory, exporter=strict_exporter)
            self.assertEqual(sorted(exporter_calls), [0, 1])
            self.assertTrue(all(isinstance(v['error'], ValueError) and 'unchanged strict' in str(v['error']) for v in results))
            for rank, stream in enumerate(streams):
                rows = events(stream)
                self.assertEqual(rows[0]['event'], 'begin')
                self.assertEqual([v['event'] for v in rows], ['begin', 'parameter', 'summary', 'published', 'all-ranks-ready'])
                self.assertGreaterEqual(len(stream.flushed), len(rows))
                self.assertTrue(all(v.endswith('\n') for v in stream.flushed))
                raw = (Path(directory) / f'parameter-inventory-rank-{rank}.json').read_bytes()
                published = next(v for v in rows if v['event'] == 'published')
                self.assertEqual(published['sha256'], hashlib.sha256(raw).hexdigest())

    def test_atomic_publication_fsyncs_complete_private_json_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'parameter-inventory-rank-0.json'
            value = {'identity': identity(0), 'metadata': 'complete before link'}
            actual_link = os.link
            observed = []
            def link(source, destination):
                self.assertFalse(Path(destination).exists())
                self.assertEqual(json.loads(Path(source).read_text()), value)
                observed.append(Path(source)); return actual_link(source, destination)
            with mock.patch.object(inventory.os, 'link', side_effect=link), mock.patch.object(inventory.os, 'fsync', wraps=os.fsync) as sync:
                digest = inventory._publish(target, value)
            self.assertTrue(observed); self.assertGreaterEqual(sync.call_count, 1)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(digest, hashlib.sha256(target.read_bytes()).hexdigest())
            original = target.read_bytes()
            with self.assertRaises(FileExistsError): inventory._publish(target, {'replacement': True})
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(list(Path(directory).glob('*.pending-*')))

    def test_publish_failure_preserves_flushed_diagnostics_and_leaves_no_partial_rank_file(self):
        with tempfile.TemporaryDirectory() as directory:
            stream = TrackingStream()
            with mock.patch.object(inventory.os, 'link', side_effect=OSError('simulated atomic publication failure')), \
                    self.assertRaisesRegex(OSError, 'atomic publication'):
                inventory.emit_writer_parameter_inventory(Model({'weight': Parameter()}), identity(0), directory, timeout=0.1, stream=stream)
            self.assertEqual([v['event'] for v in events(stream)], ['begin', 'parameter', 'summary'])
            self.assertEqual(stream.flushed[-1], stream.getvalue())
            self.assertFalse(list(Path(directory).iterdir()))

    def test_foreign_candidate_or_missing_generation_never_satisfies_peer_barrier(self):
        for kind in ('foreign_candidate', 'missing_generation'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                peer = inventory.parameter_inventory(Model({'weight': Parameter()}), identity(1))
                if kind == 'foreign_candidate': peer['identity']['candidate'] = 'previous-candidate'
                else: peer.pop('generation')
                inventory._publish(Path(directory) / 'parameter-inventory-rank-1.json', peer)
                stream = TrackingStream()
                with self.assertRaises(ValueError):
                    inventory.emit_writer_parameter_inventory(Model({'weight': Parameter()}), identity(0), directory, timeout=0.2, stream=stream)
                self.assertNotIn('all-ranks-ready', [v['event'] for v in events(stream)])

    def test_same_identity_leftover_peer_without_fresh_ack_times_out(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'parameter-inventory-rank-1.json'
            peer = inventory.parameter_inventory(Model({'weight': Parameter()}), identity(1))
            peer.update(created_at_ns=1, generation='b' * 32)
            inventory._publish(path, peer); original = path.read_bytes(); stream = TrackingStream()
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                inventory.emit_writer_parameter_inventory(Model({'weight': Parameter()}), identity(0), directory, timeout=0.08, stream=stream)
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(path.read_bytes(), original)
            self.assertNotIn('all-ranks-ready', [v['event'] for v in events(stream)])

    def test_stale_ack_for_previous_local_generation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            peer = inventory.parameter_inventory(Model({'weight': Parameter()}), identity(1))
            peer['generation'] = 'b' * 32
            inventory._publish(Path(directory) / 'parameter-inventory-rank-1.json', peer)
            ack = {'version': inventory.VERSION, 'identity': identity(1), 'generations': {'0': 'a' * 32, '1': 'b' * 32}}
            inventory._publish(Path(directory) / 'parameter-inventory-ack-rank-1.json', ack)
            stream = TrackingStream()
            with mock.patch.object(inventory.secrets, 'token_hex', return_value='c' * 32), self.assertRaisesRegex(ValueError, 'acknowledgement'):
                inventory.emit_writer_parameter_inventory(Model({'weight': Parameter()}), identity(0), directory, timeout=0.2, stream=stream)
            self.assertNotIn('all-ranks-ready', [v['event'] for v in events(stream)])

    def test_stale_local_rank_file_is_not_replaced_or_adopted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'parameter-inventory-rank-0.json'
            old = inventory.parameter_inventory(Model({'weight': Parameter()}), identity(0)); old['pid'] = -1
            inventory._publish(path, old); original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                inventory.emit_writer_parameter_inventory(Model({'weight': Parameter()}), identity(0), directory, timeout=0.2, stream=TrackingStream())
            self.assertEqual(path.read_bytes(), original)

    def test_inspection_error_is_emitted_for_all_ranks_then_stops_exporter(self):
        class BadStride(Parameter):
            def stride(self): raise RuntimeError('stride metadata unavailable')
        models = [Model({'weight': Parameter()}), Model({'weight': BadStride(), 'optional': None})]
        with tempfile.TemporaryDirectory() as directory:
            exporter = mock.Mock()
            results, streams = live_pair(directory, models, exporter=exporter)
            self.assertTrue(all(isinstance(v['error'], ValueError) and 'inspection errors' in str(v['error']) for v in results))
            exporter.assert_not_called()
            for stream in streams:
                self.assertIn('summary', [v['event'] for v in events(stream)])
                self.assertNotIn('all-ranks-ready', [v['event'] for v in events(stream)])
            report = json.loads((Path(directory) / 'parameter-inventory-rank-1.json').read_text())
            self.assertEqual(report['summary']['slots'], 2)
            self.assertEqual(report['summary']['inspection_errors'][0]['field'], 'stride')

    def test_invalid_timeout_identity_or_relative_path_stops_before_metadata_and_publication(self):
        cases = [(identity(0), 'relative', 1)]
        cases += [(identity(0), '/unused-inventory-unit-fixture', t) for t in (0, -1, True, False, None, '1', float('nan'), float('inf'), -float('inf'))]
        cases += [(identity(rank), '/unused-inventory-unit-fixture', 1) for rank in (-1, 2, True)]
        cases += [(identity(0, tensor_parallel_size=1), '/unused-inventory-unit-fixture', 1)]
        for who, directory, timeout in cases:
            with self.subTest(identity=who, directory=directory, timeout=timeout), \
                    mock.patch.object(inventory, 'parameter_inventory') as inspect, mock.patch.object(inventory, '_publish') as publish, \
                    self.assertRaises(ValueError):
                inventory.emit_writer_parameter_inventory(None, who, directory, timeout=timeout, stream=TrackingStream())
            inspect.assert_not_called(); publish.assert_not_called()

    def test_exception_metadata_never_formats_an_opaque_or_tensor_error_argument(self):
        class BadStride(Parameter):
            def stride(self): raise RuntimeError(OpaqueMetadata())
        report = inventory.parameter_inventory(Model({'weight': BadStride()}), identity(0))
        self.assertEqual(report['summary']['inspection_errors'][0]['field'], 'stride')
        self.assertFalse(report['tensor_contents_read']); self.assertFalse(report['cuda_operations'])

    def test_malformed_metadata_is_typed_and_does_not_preempt_other_parameter_rows(self):
        parameter = Parameter()
        parameter.dtype = OpaqueMetadata()
        parameter.requires_grad = OpaqueMetadata()
        parameter.shape = (OpaqueMetadata(), 2)
        model = Model({'malformed': parameter, 'optional': None, 'later': Parameter()})
        report = inventory.parameter_inventory(model, identity(0))
        self.assertEqual([v['name'] for v in report['parameters']], ['malformed', 'optional', 'later'])
        self.assertEqual(report['summary']['slots'], 3)
        fields = {v['field'] for v in report['summary']['inspection_errors']}
        self.assertTrue({'dtype', 'requires_grad', 'shape[0]'} <= fields)
        self.assertTrue(report['parameters'][0]['requires_grad']['value_not_read'])
        json.dumps(report, allow_nan=False)  # No opaque __str__/__repr__ was invoked.

    def test_truncated_peer_file_fails_closed_after_flushing_local_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            peer = Path(directory) / 'parameter-inventory-rank-1.json'
            peer.write_text('{"partial":')
            original = peer.read_bytes(); stream = TrackingStream()
            with self.assertRaises(json.JSONDecodeError):
                inventory.emit_writer_parameter_inventory(Model({'weight': Parameter()}), identity(0), directory, timeout=0.2, stream=stream)
            self.assertEqual(peer.read_bytes(), original)
            self.assertEqual(events(stream)[-1]['event'], 'published')
            self.assertEqual(stream.flushed[-1], stream.getvalue())
            self.assertNotIn('all-ranks-ready', [v['event'] for v in events(stream)])


if __name__ == '__main__':
    unittest.main()
