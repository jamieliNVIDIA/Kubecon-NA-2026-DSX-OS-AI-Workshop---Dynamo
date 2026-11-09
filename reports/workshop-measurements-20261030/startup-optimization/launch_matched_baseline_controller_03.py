"""Stage and launch the matched baseline after qualified health cleanup."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'results/workshop-baseline-controller-prep-20261104-a3'


def main():
    launcher=Path(__file__).with_name('launch_text_only_controller.py')
    remote=runpy.run_path(str(launcher))['REMOTE']
    previous="assert prior['State']['ExitCode']==handoff['accepted_terminal_exit_code']==1"
    assert remote.count(previous)==1
    remote=remote.replace(previous,"assert prior['State']['ExitCode']==handoff['accepted_terminal_exit_code']==0")
    marker=" prior=json.loads(subprocess.check_output(['docker','inspect',manifest['predecessor_name']],timeout=20))[0]"
    assert marker in remote
    audit=" failed=json.loads(subprocess.check_output(['docker','inspect','kubecon-workshop-baseline-20261104-a1'],timeout=20))[0]\n assert failed['Id']=='27f5e872befffac9634c048102433734de15df35ef85e30ea5dc7ab4392b63f1' and failed['State']['Status']=='exited' and failed['State']['ExitCode']==1\n"
    remote=remote.replace(marker,audit+marker)
    payload=(OUT/'payload.tar.gz').read_bytes();expected=(OUT/'payload.sha256').read_text().strip()
    assert hashlib.sha256(payload).hexdigest()==expected
    manifest=json.loads((OUT/'payload-manifest.json').read_text())
    assert manifest['controller_name']=='kubecon-workshop-baseline-20261104-a3'
    assert hashlib.sha256((ROOT/manifest['plan_path']).read_bytes()).hexdigest()==manifest['plan_sha256']
    receipt=OUT/'launch-attempt.json';assert not receipt.exists(),'Inspect the prior launch before any retry'
    fence_path=ROOT/'.local/workshop-measurements-20261030.gpu-lease/owner.json'
    fence=json.loads(fence_path.read_text());assert fence['agent']=='/root/stable_controller'
    (OUT/'local-fence-before-launch.json').write_text(json.dumps(fence,indent=2)+'\n')
    fence['authorized_followup']={'controller_name':manifest['controller_name'],'plan_sha256':manifest['plan_sha256'],'scope':'Matched updated baseline after qualified health cleanup; no local GPU operations'}
    temp=fence_path.with_name('owner.json.tmp');temp.write_text(json.dumps(fence,indent=2)+'\n');temp.replace(fence_path)
    argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-o','ForwardAgent=no','ubuntu@3.238.63.5','python3','-c',shlex.quote(remote.replace('EXPECTED_ARCHIVE_SHA',repr(expected)))]
    started=dt.datetime.now(dt.timezone.utc).isoformat();unknown=False
    try:r=subprocess.run(argv,input=payload,capture_output=True,timeout=180)
    except subprocess.TimeoutExpired as error:
        unknown=True;r=subprocess.CompletedProcess(argv,124,error.stdout or b'',error.stderr or b'')
    value={'started_at':started,'finished_at':dt.datetime.now(dt.timezone.utc).isoformat(),'exit_code':r.returncode,'stderr':r.stderr.decode(errors='replace'),'remote_state_unknown':unknown,'plan_sha256':manifest['plan_sha256'],'payload_sha256':expected,'launcher_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'shared_launcher_sha256':hashlib.sha256(launcher.read_bytes()).hexdigest()}
    if r.returncode==0:value['remote']=json.loads(r.stdout)
    receipt.write_text(json.dumps(value,indent=2)+'\n')
    if r.returncode:raise RuntimeError(value['stderr'][-2500:])
    print(json.dumps(value['remote'],indent=2))


if __name__=='__main__':main()
