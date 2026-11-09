"""Build a credential-free, immutable follow-up payload; no network actions."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import runpy
import tarfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', choices=['01', '02'], default='02')
    parser.add_argument('--generation', choices=['4', '5'], default='5')
    args = parser.parse_args()
    suffix = '' if args.attempt == '01' else '_02'
    RUN = ROOT / ('results/workshop-mx-startup-20261103-textonly' + args.attempt)
    OUT = ROOT / ('results/workshop-textonly-controller-prep-20261103-a' + args.generation)
    PILOT = HERE / ('text_only_startup' + suffix + '.py')
    QUEUE = HERE / 'queue_text_only_03.py'
    FINALIZER = HERE / ('finalize_text_only' + suffix + '.py')
    HANDOFF = ROOT / 'results/workshop-textonly-predecessor-audit-20261103-a1/handoff.json'
    assert (RUN / 'spec.json').is_file(), 'Freeze the new pilot first'
    assert PILOT.is_file()
    OUT.mkdir(exist_ok=False)
    credential_check = runpy.run_path(str(HERE.parent / 'mx-startup/build_stable_controller_bundle.py'))['credential_check']
    inputs = [PILOT, QUEUE, FINALIZER, HANDOFF,
              HERE.parent / 'mx-startup/measure_startup.py',
              HERE.parent / 'mx-startup/artifact_comparison.py',
              HERE.parent / 'mx-startup/analyze_startup.py',
              HERE.parent / 'mx-startup/artifact-coordinator-images.json',
              ROOT / 'configs/super-vl-tp2-lock.json',
              ROOT / 'configs/dgd/super-vl-r610-d906a5f1/mx/nemotron-modelexpress.yaml',
              ROOT / 'configs/dgd/super-vl-r610-d906a5f1/mx/nemotron-modelexpress-target.yaml',
              ROOT / 'configs/upstream/recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh',
              ROOT / 'results/workshop-mx-startup-20261030-pair04/spec.json',
              ROOT / 'results/workshop-rr-20261030-prep-1705/rr-1-replica.yaml']
    # These are imported transitively by the unchanged measurement helpers.
    inputs += [ROOT / ('scripts/' + name + '.py') for name in
               ('testlib', 'storage_tests', 'common_runtime_tests',
                'common_runtime_build', 'serving_tests', 'gpu_claims', 'feature_tests')]
    payload = {str(PILOT.relative_to(ROOT)): PILOT,
               str(QUEUE.relative_to(ROOT)): QUEUE,
               str(FINALIZER.relative_to(ROOT)): FINALIZER,
               str(HANDOFF.relative_to(ROOT)): HANDOFF}
    # The pilot already froze this complete dependency set. Existing identical
    # remote files are checked, never rewritten; absent files can be staged.
    pilot_inputs = json.loads((RUN / 'inputs-sha256.json').read_text())
    for relative, expected in pilot_inputs.items():
        p = ROOT / relative
        assert sha(p) == expected, 'Pilot input changed: ' + relative
        payload[relative] = p
    # Only top-level offline freeze products, not arbitrary historical results.
    for p in RUN.iterdir():
        if p.is_file() and p.suffix in ('.json', '.sha256'):
            if args.generation == '5' and p.name in ('state.json', 'LIVE_STATUS.json'):
                continue
            payload[str(p.relative_to(ROOT))] = p
    assert not any(name.startswith('.local/') for name in payload)
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    frozen.update({name: sha(p) for name, p in payload.items()
                   if p.name not in ('state.json', 'LIVE_STATUS.json')})
    helper = str(PILOT)
    plan = {'schema': 1, 'run_directory': str(RUN.relative_to(ROOT)),
            'predecessor_handoff_path': str(HANDOFF.relative_to(ROOT)),
            'controller_directory': 'results/workshop-textonly-controller-20261103-a' + args.generation,
            'predecessor_wait_timeout_seconds': 10800,
            'source_sha256': frozen,
            'stages': [{'name': 'text-only-' + action,
                        'argv': [helper, action, '--run', str(RUN)],
                        'timeout_seconds': timeout}
                       for action, timeout in [('prepare', 1800), ('batch', 7200), ('cleanup', 600)]],
            'scope': 'One fresh text-only MX seed and artifact receiver; existing probes and serving envelope; no alteration of prior runs'}
    plan['stages'].append({'name': 'text-only-finalize',
                           'argv': [str(FINALIZER), '--run', str(RUN)],
                           'timeout_seconds': 300})
    plan_path = OUT / 'controller-plan.json'
    plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    payload[str(plan_path.relative_to(ROOT))] = plan_path
    records = {}
    for name, p in sorted(payload.items()):
        assert p.is_file() and not p.is_symlink()
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        if p.suffix == '.json':
            credential_check(json.loads(p.read_text()), name)
        records[name] = {'sha256': sha(p), 'bytes': p.stat().st_size}
    manifest = {'schema': 1, 'logical_root': str(ROOT), 'files': records,
                'required_existing_sha256': {name: value for name, value in frozen.items() if name not in payload},
                'plan_path': str(plan_path.relative_to(ROOT)), 'plan_sha256': sha(plan_path),
                'controller_name': 'kubecon-workshop-textonly-20261103-a' + args.generation,
                'queue_script': str(QUEUE.relative_to(ROOT)),
                'predecessor_name': 'kubecon-workshop-controller-20261103',
                'predecessor_id': '5b2205e449583b1a8bd79466e7a8f90d2664c8ad59fe760c7ae46d8a139b3411',
                'predecessor_handoff_path': str(HANDOFF.relative_to(ROOT)),
                'physical_workspace': '/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace',
                'cpu_image': 'docker.io/library/python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337',
                'scope': 'New source/locked pilot inputs only; no kubeconfig, Secret, model weights, dataset, virtual environment or prior-run overwrite'}
    manifest_path = OUT / 'payload-manifest.json'
    if args.generation == '5':
        recovery_path = ROOT / 'results/workshop-textonly-cpu-recovery-20261103-a1/receipt.json'
        recovery = json.loads(recovery_path.read_text())
        assert recovery['coordinator_ready'] and recovery['redis_ready']
        manifest['required_existing_sha256'][str((RUN / 'state.json').relative_to(ROOT))] = recovery['state_sha256']
        manifest['resumed_cpu_preparation'] = {'receipt': str(recovery_path.relative_to(ROOT)),
                                              'receipt_sha256': sha(recovery_path),
                                              'scope': 'No GPU batch was started; reuse unchanged Ready CPU services and rerun the original prepare action'}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    with tarfile.open(OUT / 'payload.tar.gz', 'w:gz') as archive:
        for name, p in sorted(payload.items()):
            archive.add(p, arcname=name, recursive=False)
        data = manifest_path.read_bytes()
        info = tarfile.TarInfo('text-only-payload-manifest.json')
        info.size = len(data)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(data))
    (OUT / 'payload.sha256').write_text(sha(OUT / 'payload.tar.gz') + '\n')
    print(json.dumps({'directory': str(OUT), 'payload_sha256': sha(OUT / 'payload.tar.gz'),
                      'plan_sha256': sha(plan_path), 'files': len(records),
                      'scope': 'Offline prepared; not staged or launched'}, indent=2))


if __name__ == '__main__':
    main()
