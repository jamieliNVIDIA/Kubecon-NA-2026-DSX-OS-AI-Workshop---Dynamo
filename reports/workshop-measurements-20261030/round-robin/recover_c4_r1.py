#!/usr/bin/env python3
"""Collect the original completed C4 r1 after transport loss; never replay it.

Fixed scope: resume02/c4-r1-a1, the retained exact lease, original CPU/worker
UIDs, and original sealed profile. Root reviews and launches this helper.
It does not deploy, delete, restart, alter serving, or release the GPU lease.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import execute_pair as e
import analyze as analysis
from gpu_claims import verify_allocation

RUN = e.ROOT / 'results/workshop-rr-20261103-resume02'
ARM = 'c4-r1-a1'
CLIENT_UID = 'b2e69037-fe15-4cf1-a00a-fff65d545588'
WORKER = 'ft-agg-0-agg-w4859'
WORKER_UID = '66649d97-fd14-4054-be3f-7aa55d7f2215'
SPEC_SHA = '705ecb1d1aeb9c1a8898aa710c94511f799967dbd9bd8ac86d5ae8e457270508'


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def digest(path):
    return analysis.sha(path)


def ready(pod, uid, image):
    assert pod['metadata']['uid'] == uid, 'Original Pod UID changed'
    assert not pod['metadata'].get('deletionTimestamp')
    assert pod['status']['phase'] == 'Running'
    assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status']['conditions'])
    assert all(c.get('restartCount', 0) == 0 and c.get('ready') for c in pod['status']['containerStatuses'])
    assert pod['spec']['containers'][0]['image'] == image
    assert all(c['imageID'].split('@')[-1] == image.split('@')[-1] for c in pod['status']['containerStatuses'])


def run_collection(label):
    dest = RUN / ('recovery-c4-r1-' + label)
    dest.mkdir(exist_ok=False)
    arm = RUN / ARM
    lock = RUN / '.c4-r1-recovery.lock'
    acquired = False
    run = None
    try:
        assert not (RUN / '.remaining-controller.lock').exists(), 'Continuation still active'
        prior = json.loads((RUN / 'continuation-a1/exit.json').read_text())
        assert prior['exit_code'] == 1 and prior['gpu_lease_present'] is True
        assert 'scaleout-c4 exited 1' in prior['error']
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'label': label, 'at': e.now()}) + '\n')
        acquired = True
        lease = json.loads((e.LEASE / 'owner.json').read_text())
        assert lease['agent'] == e.OWNER and Path(lease['run']).resolve() == RUN
        assert lease['namespace'] == 'dynamo-ft-r610-1ec4908b-rr'
        save(dest / 'lease-before.json', lease)
        frozen = json.loads((RUN / 'continuation-a1/plan.json').read_text())['source_sha256']
        for relative, expected in frozen.items():
            assert digest(e.ROOT / relative) == expected, 'Original frozen input changed: ' + relative
        save(dest / 'helper-provenance.json', {'at': e.now(), 'helper_sha256': digest(Path(__file__)),
                                             'original_frozen_inputs': frozen})
        assert digest(arm / 'spec.json') == SPEC_SHA
        spec = json.loads((arm / 'spec.json').read_text())
        assert digest(arm / 'profile.yaml') == spec['profile_sha256']
        for key, expected in {'arm': ARM, 'replicas': 1, 'h100_gpus': 2,
                              'concurrency_session_trees': 4, 'router_mode': 'round-robin',
                              'model': e.MODEL, 'model_revision': e.REV,
                              'dataset_revision': e.DATASET_REV, 'dataset_sha256': e.DATASET_SHA,
                              'native_max_model_len': 1048576, 'max_num_seqs_per_worker': 4}.items():
            assert spec[key] == expected, key
        assert spec['worker_pods'][0]['uid'] == WORKER_UID
        assert not any((arm / name).exists() for name in ('raw', 'raw-artifacts.tar.gz', 'summary.json', 'integrity.json'))
        shutil.copytree(arm, dest / 'precollection-arm')
        run = e.Run(RUN)
        namespace = run.get('get', 'namespace', run.ns)
        save(dest / 'namespace.json', namespace)
        assert namespace['metadata']['labels']['app.kubernetes.io/managed-by'] == run.state['owner']
        objects = {}
        for kind in ('pods', 'resourceclaims', 'dgd', 'nodes'):
            value = run.get('get', kind, *([] if kind == 'nodes' else ['-n', run.ns]))
            save(dest / (kind + '.json'), value)
            objects[kind] = value['items']
        expected_nodes = {'kubecon-nke-site-cp-0124', 'kubecon-nke-site-cp-0198', 'kubecon-nke-site-cp-0942'}
        assert {n['metadata']['name'] for n in objects['nodes']} == expected_nodes
        assert all(any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status']['conditions'])
                   for n in objects['nodes'])
        client_pod = next(p for p in objects['pods'] if p['metadata']['name'] == 'rr-loadgen')
        worker = next(p for p in objects['pods'] if p['metadata']['name'] == WORKER)
        ready(client_pod, CLIENT_UID, spec['runtime_image'])
        ready(worker, WORKER_UID, spec['runtime_image'])
        assert {p['metadata']['uid'] for p in e.workers(run)} == {WORKER_UID}
        argv = worker['spec']['containers'][0]['args']
        for flag, expected in (('--revision', e.REV), ('--tensor-parallel-size', '2'),
                               ('--max-num-seqs', '4'), ('--max-num-batched-tokens', '8192'),
                               ('--gpu-memory-utilization', '0.85')):
            assert argv[argv.index(flag) + 1] == expected, flag
        assert '--max-model-len' not in argv and '--load-format' not in argv
        assert e.MODEL in argv and '--enable-prefix-caching' in argv
        verify_allocation(run, worker, worker['spec']['containers'][0], 2)
        qualification = run.state['checks']['rr-cpu-client-qualified']
        receipt = json.loads((Path(qualification['evidence']) / 'receipt-c4.json').read_text())
        assert qualification['status'] == 'passed' and receipt['status'] == 'cache_verified'
        remote = '''import datetime,hashlib,json,sys
from pathlib import Path
expected=json.loads(sys.stdin.read());root=Path('/tmp/workshop-rr/runs/c4-r1-a1')
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  while b:=f.read(4194304):h.update(b)
 return h.hexdigest()
assert sha(root/'profile.yaml')==expected['profile_sha256']
checks={}
for relative,wanted in expected['source_file_sha256'].items():
 p=Path('/tmp/workshop-rr/aiperf-source/src/aiperf')/relative
 checks[relative]=sha(p);assert checks[relative]==wanted,relative
for name,wanted in expected['cache_files'].items():
 p=Path(name);assert p.stat().st_size==wanted['bytes']
 checks[name]=sha(p);assert checks[name]==wanted['sha256'],name
outcome=json.loads((root/'exit.json').read_text());assert outcome['exit_code']==0,outcome
process=json.loads((root/'process.json').read_text())
paths=[p for p in (root/'artifacts').rglob('profile_export_aiperf.json') if 'phases' not in p.parts]
assert len(paths)==1,len(paths)
data=json.loads(paths[0].read_text())
value={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'process':process,'exit':outcome,
 'remote_profile_sha256':sha(root/'profile.yaml'),'checked_hashes':checks,
 'export_path':str(paths[0]),'export_sha256':sha(paths[0]),
 'is_complete':data.get('is_complete'),'was_cancelled':data.get('was_cancelled'),
 'metadata':data.get('metadata'),'request_count':data.get('request_count'),
 'error_request_count':data.get('error_request_count'),'context_overflow_count':data.get('context_overflow_count'),
 'console_tail':(root/'console.log').read_text(errors='replace')[-2500:]}
print(json.dumps(value))
'''
        expected = {key: receipt[key] for key in ('source_file_sha256', 'cache_files')}
        expected['profile_sha256'] = spec['profile_sha256']
        result = e.client(run, remote, timeout=600, input_text=json.dumps(expected))
        probe = json.loads(result.stdout)
        save(dest / 'remote-completion.json', probe)
        assert probe['is_complete'] is True and probe['was_cancelled'] is False
        assert (probe.get('metadata') or {}).get('submission_valid') is True
        # Stop/collect only the pre-existing nvidia-smi sampler. No serving or
        # benchmark process is signalled; the detached benchmark has exit 0.
        e.telemetry_stop(run, ARM)
        e.collect_workers(run, ARM)
        e.collect_frontend_metrics(run, e.endpoint(run), ARM, 'after')
        e.collect_profile(run, ARM)
        local_export = next(p for p in (arm / 'raw').rglob('profile_export_aiperf.json') if 'phases' not in p.parts)
        assert digest(local_export) == probe['export_sha256']
        assert digest(arm / 'spec.json') == SPEC_SHA and digest(arm / 'profile.yaml') == spec['profile_sha256']
        run.result('rr-' + ARM, 'completed', **probe['exit'],
                   note='Original detached execution recovered after API outage; no replay or request substitution')
        summary = e.validate_profile(run, ARM)
        measured = analysis.load_arm(arm)
        save(dest / 'accepted-original-arm.json', {
            'at': e.now(), 'original_arm': ARM, 'spec_sha256': SPEC_SHA,
            'client_uid': CLIENT_UID, 'worker_uid': WORKER_UID,
            'benchmark_id': summary['benchmark_id'], 'requests': measured['requests'],
            'request_errors': measured['request_error_count'], 'cancelled_profile_records': measured['cancelled_profile_records'],
            'lease_retained': True, 'scope': 'Original first arm collected and accepted; second arm has not started'})
        run.result('rr-c4-r1-recovered', 'passed', evidence=str(dest), worker_uid=WORKER_UID,
                   client_uid=CLIENT_UID, original_arm=ARM, spec_sha256=SPEC_SHA)
        e.status(run, 'original C4 first arm recovered and accepted; second arm pending', recovery=str(dest),
                 successful_requests=measured['requests'], gpu_lease_retained=True)
    except BaseException as error:
        save(dest / 'failure.json', {'at': e.now(), 'error': repr(error), 'traceback': traceback.format_exc(),
                                     'gpu_lease_present': e.LEASE.exists(), 'scope': 'No replay, deployment or cleanup attempted'})
        raise
    finally:
        save(dest / 'integrity.json', {str(p.relative_to(dest)): digest(p) for p in dest.rglob('*') if p.is_file()})
        if acquired:
            assert json.loads(lock.read_text())['pid'] == os.getpid()
            lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not e.re.fullmatch(r'[a-z0-9-]+', args.label):
        raise ValueError('Invalid immutable recovery label')
    run_collection(args.label)


if __name__ == '__main__':
    main()
