"""Audit successful cleanup and release only this run's local delegation fence."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'results/workshop-baseline-final-cleanup-20261104-a3'
PREP = ROOT / 'results/workshop-baseline-controller-prep-20261104-a3'
RUN_REL = 'results/workshop-mx-startup-20261104-baseline03'
PROGRAM = r'''
import datetime,json,subprocess
from pathlib import Path
w=Path('/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace')
run=w/'results/workshop-mx-startup-20261104-baseline03'
assert not (w/'.local/workshop-measurements-20261030.gpu-lease').exists()
controller=json.loads(subprocess.check_output(['docker','inspect','kubecon-workshop-baseline-20261104-a3'],timeout=20))[0]
assert controller['Id']=='689c467d1dcdb12fd3633deb45686b705a2979553a4b8554d1817dff66160197'
assert controller['State']['Status']=='exited' and controller['State']['ExitCode']==0
assert json.loads((run/'qualification.json').read_text())['passed']
ns=json.loads((run/'state.json').read_text())['namespace']
def get(*parts):return json.loads(subprocess.check_output(['kubectl','--request-timeout=15s']+list(parts)+['-o','json'],timeout=25))
assert get('get','namespace',ns)['metadata']['labels']['app.kubernetes.io/managed-by']=='kubecon-dynamo-feature-tests'
resources={k:get('get',k,'-n',ns)['items'] for k in ['pods','resourceclaims','dgd']}
assert not any(resources.values()),'Owned resources remain'
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'controller_id':controller['Id'],'controller_state':controller['State'],'namespace':ns,
 'final_resource_counts':{k:len(v) for k,v in resources.items()},'remote_gpu_lease_absent':True}))
'''


def main():
    verification = json.loads((ROOT / 'results/workshop-baseline-pullback-20261104-a3/verification.json').read_text())
    assert verification['mismatches'] == 0 and verification['controller_state']['ExitCode'] == 0
    assert verification['gpu_lease_absent'] and not any(verification['final_resource_counts'].values())
    plan_sha = hashlib.sha256((PREP / 'controller-plan.json').read_bytes()).hexdigest()
    lease = ROOT / '.local/workshop-measurements-20261030.gpu-lease'
    owner = json.loads((lease / 'owner.json').read_text())
    assert owner['agent'] == '/root/stable_controller' and owner['run'] == str(ROOT / RUN_REL)
    assert owner['authorized_followup']['controller_name'] == 'kubecon-workshop-baseline-20261104-a3'
    assert owner['authorized_followup']['plan_sha256'] == plan_sha == owner['plan_sha256']
    assert {p.name for p in lease.iterdir()} == {'owner.json'}
    OUT.mkdir(exist_ok=False)
    args = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
            '-o', 'ForwardAgent=no', 'ubuntu@3.238.63.5', 'python3', '-c', shlex.quote(PROGRAM)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    (OUT / 'stderr.txt').write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:])
    proof = json.loads(result.stdout)
    (OUT / 'remote-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    (OUT / 'released-local-fence.json').write_text(json.dumps(owner, indent=2) + '\n')
    # Recheck after the network round trip before releasing the exact owned fence.
    assert json.loads((lease / 'owner.json').read_text()) == owner
    (lease / 'owner.json').unlink()
    lease.rmdir()
    proof.update(local_gpu_fence_released=True, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 completed_at=dt.datetime.now(dt.timezone.utc).isoformat())
    (OUT / 'receipt.json').write_text(json.dumps(proof, indent=2) + '\n')
    # Snapshot's separate chat is waiting for this audited handoff. Do not
    # acquire its lease, launch its work, or overwrite any of its artifacts.
    handoff = ROOT / 'results/workshop-snapshot-dgd-20261104-a1/gpu-handoff.json'
    handoff.parent.mkdir(exist_ok=True)
    with handoff.open('x') as stream:
        json.dump({'available': True, 'at': proof['completed_at'],
            'released_by': 'kubecon-workshop-baseline-20261104-a3',
            'controller_id': proof['controller_id'], 'startup_run': RUN_REL,
            'remote_gpu_lease_absent': True, 'local_gpu_fence_released': True,
            'final_resource_counts': proof['final_resource_counts'],
            'independent_cleanup_receipt': str((OUT / 'receipt.json').relative_to(ROOT)),
            'scope': 'MX comparison finished and owned resources audited absent. Snapshot must check live availability and acquire its own lease.'},
            stream, indent=2)
        stream.write('\n')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
