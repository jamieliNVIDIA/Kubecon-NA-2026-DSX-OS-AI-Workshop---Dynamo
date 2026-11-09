"""Build a credential-free health-pair payload after verified pilot02 pullback.

Offline only: no SSH, registry, Kubernetes or GPU operations.
"""
import hashlib
import io
import json
from pathlib import Path
import runpy
import tarfile

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
RUN=ROOT/'results/workshop-mx-startup-20261103-textonly-health01'
OUT=ROOT/'results/workshop-health-controller-prep-20261103-a1'
PULLBACK=ROOT/'results/workshop-textonly-pullback-20261103-a1'
PRIOR_REL='results/workshop-mx-startup-20261103-textonly02'
CONTROLLER_REL='results/workshop-textonly-controller-20261103-a5'
PRIOR_ID='a25a5e257b7ffb73467d73c4733dffca70e82b91cc7934698c0d15974f4b45ee'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n')


def main():
    prior=PULLBACK/'verified'/PRIOR_REL
    prior_controller=PULLBACK/'verified'/CONTROLLER_REL
    verification=json.loads((PULLBACK/'verification.json').read_text())
    assert not verification['mismatches'] and verification['files_verified']>0
    qualification=json.loads((prior/'text-only-qualification.json').read_text())
    cleanup=json.loads((prior/'cleanup-proof.json').read_text())
    state=json.loads((prior/'state.json').read_text())
    exited=json.loads((prior_controller/'exit.json').read_text())
    assert exited['exit_code']==0 and qualification['passed']
    assert state['checks']['text-only-pilot']['status']=='passed'
    assert cleanup['verified'] and cleanup['gpu_lease_absent']
    assert all(not cleanup[k] for k in ['gpu_pods','resourceclaims','graphs','coordinator_pods'])
    prior_spec=json.loads((prior/'spec.json').read_text())
    reference=json.loads((RUN/'pilot02-reference.json').read_text())
    assert sha(prior/'spec.json')==reference['control_spec_sha256'],'Verified predecessor spec differs from the frozen control reference'
    assert state['model_lock']==prior_spec['model_lock']==json.loads((RUN/'spec.json').read_text())['model_lock']
    inputs=json.loads((RUN/'inputs-sha256.json').read_text())
    for name,expected in inputs.items():assert sha(ROOT/name)==expected,'Frozen health input changed: '+name
    required={PRIOR_REL+'/'+name:sha(prior/name) for name in
        ['spec.json','state.json','text-only-qualification.json','cleanup-proof.json','evidence-sha256.json']}
    required[CONTROLLER_REL+'/exit.json']=sha(prior_controller/'exit.json')
    OUT.mkdir(exist_ok=False)
    handoff_path=OUT/'predecessor-handoff.json'
    handoff={'predecessor_id':PRIOR_ID,'accepted_terminal_exit_code':0,
        'predecessor_exit_path':CONTROLLER_REL+'/exit.json',
        'predecessor_exit_sha256':sha(prior_controller/'exit.json'),
        'prior_namespace':state['namespace'],'prior_run_directory':PRIOR_REL,
        'required_existing_sha256':required,
        'verified_pullback_receipt':str((PULLBACK/'verification.json').relative_to(ROOT)),
        'verified_pullback_receipt_sha256':sha(PULLBACK/'verification.json'),
        'scope':'Accepted terminal pilot02 success and cleanup; prior files are verified remotely, never overwritten'}
    write(handoff_path,handoff)
    helper=HERE/'text_only_health_startup.py';queue=HERE/'queue_health_pair.py'
    payload={name:ROOT/name for name in inputs}
    for p in [queue,Path(__file__),handoff_path,RUN/'inputs-sha256.json',RUN/'spec.sha256',RUN/'state.json',RUN/'offline-validation.json']:
        payload[str(p.relative_to(ROOT))]=p
    persistent={name:sha(p) for name,p in payload.items() if p.name not in ['state.json','LIVE_STATUS.json']}
    assert not any(name in persistent for name in [str((RUN/'state.json').relative_to(ROOT)),str((RUN/'LIVE_STATUS.json').relative_to(ROOT))])
    plan={'schema':1,'run_directory':str(RUN.relative_to(ROOT)),
        'controller_directory':'results/workshop-health-controller-20261103-a1',
        'predecessor_id':PRIOR_ID,'predecessor_handoff_path':str(handoff_path.relative_to(ROOT)),
        'predecessor_wait_timeout_seconds':10800,'source_sha256':persistent,
        'stages':[{'name':'health-'+action,'argv':[str(helper),action,'--run',str(RUN)],'timeout_seconds':timeout}
            for action,timeout in [('prepare',1800),('batch',9600),('cleanup',900),('finalize',300)]],
        'scope':'One fresh default-health text-only seed and two matched artifact receivers; only worker health policy differs'}
    plan_path=OUT/'controller-plan.json';write(plan_path,plan)
    payload[str(plan_path.relative_to(ROOT))]=plan_path
    credential_check=runpy.run_path(str(HERE.parent/'mx-startup/build_stable_controller_bundle.py'))['credential_check']
    records={}
    for name,p in sorted(payload.items()):
        assert p.is_file() and not p.is_symlink()
        assert not Path(name).is_absolute() and '..' not in Path(name).parts
        assert not name.startswith(('.local/','.git/','.aws/'))
        if p.suffix=='.json':credential_check(json.loads(p.read_text()),name)
        records[name]={'sha256':sha(p),'bytes':p.stat().st_size}
    manifest={'schema':1,'logical_root':str(ROOT),'files':records,
        'required_existing_sha256':required,
        'plan_path':str(plan_path.relative_to(ROOT)),'plan_sha256':sha(plan_path),
        'controller_name':'kubecon-workshop-health-20261103-a1',
        'queue_script':str(queue.relative_to(ROOT)),
        'predecessor_name':'kubecon-workshop-textonly-20261103-a5','predecessor_id':PRIOR_ID,
        'predecessor_handoff_path':str(handoff_path.relative_to(ROOT)),
        'physical_workspace':'/home/ubuntu/workshop-measurements/20261103-stable-controller/workspace',
        'cpu_image':'docker.io/library/python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337',
        'scope':'New frozen health inputs only; no credentials, raw Secrets, model weights or prior-state overwrite'}
    manifest_path=OUT/'payload-manifest.json';write(manifest_path,manifest)
    with tarfile.open(OUT/'payload.tar.gz','w:gz') as archive:
        for name,p in sorted(payload.items()):archive.add(p,arcname=name,recursive=False)
        data=manifest_path.read_bytes();info=tarfile.TarInfo('text-only-payload-manifest.json')
        info.size=len(data);info.mode=0o600;archive.addfile(info,io.BytesIO(data))
    (OUT/'payload.sha256').write_text(sha(OUT/'payload.tar.gz')+'\n')
    print(json.dumps({'directory':str(OUT),'files':len(records),'payload_sha256':sha(OUT/'payload.tar.gz'),
        'plan_sha256':sha(plan_path),'scope':'Offline packaging only; not staged or launched'},indent=2))


if __name__=='__main__':main()
