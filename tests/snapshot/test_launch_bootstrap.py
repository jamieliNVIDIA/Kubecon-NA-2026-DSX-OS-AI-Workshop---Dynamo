"""Snapshot job identity survives exec; restore standby never creates a new job."""
from tests.support import ROOT
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from testlib import Run


class BootstrapTests(unittest.TestCase):
    def test_stable_identity_and_argv_survive_exec(self):
        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory)
            transient = control / 'transient'
            transient.write_bytes(b'CUDA job identity\0mutable state')
            env = dict(os.environ, SNAPSHOT_CONTROL_DIR=directory, CUDA_CHECKPOINT_JOB_FILE=str(transient))
            command = [sys.executable, '-c',
                       'import json,os,sys;print(json.dumps([os.environ["CUDA_CHECKPOINT_JOB_FILE"],sys.argv[1:]]))',
                       'an argument with spaces', '$(literal)']
            result = subprocess.run(['sh', str(ROOT / 'scripts/snapshot-persist-job.sh')] + command,
                                    env=env, text=True, capture_output=True, check=True)
            stable, args = json.loads(result.stdout)
            self.assertEqual(stable, str(control / 'cuda-checkpoint-job'))
            self.assertEqual(Path(stable).read_bytes(), transient.read_bytes())
            self.assertEqual(Path(stable).stat().st_mode & 0o777, 0o600)
            self.assertEqual(args, command[-2:])
            # A second source launch must not silently overwrite a prior job.
            transient.write_bytes(b'different job')
            second = subprocess.run(['sh', str(ROOT / 'scripts/snapshot-persist-job.sh'), 'true'], env=env,
                                    text=True, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(Path(stable).read_bytes(), b'CUDA job identity\0mutable state')

    def test_missing_job_fails_before_workload(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, SNAPSHOT_CONTROL_DIR=directory)
            env.pop('CUDA_CHECKPOINT_JOB_FILE', None)
            marker = Path(directory) / 'workload-ran'
            result = subprocess.run(['sh', str(ROOT / 'scripts/snapshot-persist-job.sh'),
                                     'touch', str(marker)], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_restore_standby_never_launches_cuda_or_workload(self):
        with tempfile.TemporaryDirectory() as directory:
            sleeper = Path(directory) / 'sleep'
            sleeper.write_text('#!/bin/sh\nprintf STANDBY\n')
            sleeper.chmod(0o700)
            env = dict(os.environ, SNAPSHOT_RESTORE_STANDBY='1', PATH=directory)
            result = subprocess.run(['/bin/sh', str(ROOT / 'scripts/snapshot-launch-entrypoint.sh'),
                                     '/definitely-not-a-workload'], env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, 'STANDBY')
            self.assertFalse((Path(directory) / 'cuda-checkpoint-job').exists())

    def test_effective_dgd_keeps_tp2_claim_and_worker_only_bootstrap(self):
        import snapshot_tests
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            run = Run(Path(directory) / 'run')
            lock = json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())
            lock.update(snapshot_launch_job=True, manifest_directory=str(Path(directory) / 'manifests'))
            run.state['model_lock'] = lock
            snapshot_tests.render(run)
            bundle = yaml.safe_load(Path(run.state['graphs']['snapshot']['manifest']).read_text())
            claim, graph = bundle['items']
            self.assertEqual(claim['spec']['spec']['devices']['requests'][0]['exactly']['count'], 2)
            for component in graph['spec']['components']:
                main = component['podTemplate']['spec']['containers'][0]
                self.assertEqual(main['image'], lock['runtime_image'])
                if component['type'] == 'frontend':
                    self.assertEqual(main['command'], ['python3', '-m', 'dynamo.frontend'])
                else:
                    self.assertEqual(main['command'][:2], ['/bin/sh', '/snapshot-bootstrap/entrypoint.sh'])
                    self.assertEqual(main['args'][main['args'].index('--tensor-parallel-size') + 1], '2')
                    self.assertNotIn('--enforce-eager', main['args'])
                    self.assertTrue(main['resources']['claims'])
                    self.assertNotIn('nvidia.com/gpu', main['resources']['limits'])

    def test_legacy_ipc_control_is_explicit_and_worker_only(self):
        import snapshot_tests
        with tempfile.TemporaryDirectory() as directory:
            run = Run(Path(directory) / 'run')
            lock = json.loads((ROOT / 'configs/super-vl-tp2-lock.json').read_text())
            lock.update(snapshot_launch_job=True, snapshot_legacy_ipc=True, snapshot_eager=True,
                        manifest_directory=str(Path(directory) / 'manifests'))
            run.state['model_lock'] = lock
            graph = snapshot_tests.render(run)
            for component in graph['spec']['components']:
                main = component['podTemplate']['spec']['containers'][0]
                env = {e['name']: e.get('value') for e in main['env']}
                if component['type'] == 'frontend':
                    self.assertNotIn('--enforce-eager', main['args'])
                else:
                    self.assertIn('--enforce-eager', main['args'])
                for name in ('NCCL_CUMEM_ENABLE', 'NCCL_CUMEM_HOST_ENABLE', 'NCCL_NVLS_ENABLE'):
                    if component['type'] == 'frontend':
                        self.assertNotIn(name, env)
                    else:
                        self.assertEqual(env[name], '0')

    def test_stalled_stop_rejects_ready_capture_before_agent_command(self):
        from snapshot_tp2_workflow import stop_stalled
        with tempfile.TemporaryDirectory() as directory:
            class ReadyRun(Run):
                def get(self, *args):
                    return {'metadata': {'labels': {'feature-test-run': self.ns}},
                            'status': {'checkpoints': {'VllmSnapshotWorker': {'ready': True}}}}
                def k(self, *args, **kwargs):
                    raise AssertionError('A ready capture must not reach an agent/stop command')
            run = ReadyRun(Path(directory) / 'run')
            (run.path / 'snapshot-source-pod.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Capture became ready'):
                stop_stalled(run)

    def test_stalled_stop_requires_actual_ten_minute_helper_age(self):
        from snapshot_tp2_workflow import stop_stalled
        with tempfile.TemporaryDirectory() as directory:
            uid = '11111111-1111-1111-1111-111111111111'
            class YoungHelperRun(Run):
                def get(self, *args):
                    if args[1] == 'dgd':
                        return {'metadata': {'labels': {'feature-test-run': self.ns}},
                                'status': {'checkpoints': {'VllmSnapshotWorker': {'checkpointName': 'owned-checkpoint'}}}}
                    if args[1] == 'pod':
                        return {'metadata': {'uid': uid, 'labels': {'nvidia.com/snapshot-job': 'owned-checkpoint'}}}
                    if args[1] == 'pods':
                        return {'items': [{'metadata': {'name': 'dynamo-platform-snapshot-agent-test'},
                                           'spec': {'nodeName': 'node-test'}}]}
                    raise AssertionError(args)
                def k(self, *args, **kwargs):
                    return subprocess.CompletedProcess(args, 0, '123 599\n/usr/local/bin/cuda-checkpoint-helper --action checkpoint --pid 456\n', '')
                def result(self, *args, **kwargs):
                    raise AssertionError('A young helper must not reach a stop receipt')
            run = YoungHelperRun(Path(directory) / 'run')
            source = {'metadata': {'name': 'source', 'uid': uid}, 'spec': {'nodeName': 'node-test'}}
            (run.path / 'snapshot-source-pod.json').write_text(json.dumps(source))
            with self.assertRaisesRegex(ValueError, '600-second CUDA action limit'):
                stop_stalled(run)


if __name__ == '__main__':
    unittest.main()
