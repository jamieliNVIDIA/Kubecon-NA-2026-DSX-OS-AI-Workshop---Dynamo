#!/usr/bin/env python3
"""Fresh immutable text-only MX pilot: one storage seed, one artifact receiver.

freeze is entirely local. prepare/batch/cleanup are for the delegated stable
controller after the parent queue has verified predecessor cleanup.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
MX = HERE.parent / 'mx-startup'
sys.path.insert(0, str(MX))
import artifact_comparison as previous
import measure_startup as base

RAW = ROOT / 'results/workshop-mx-pullback-20261103-breakdown/verified/results/workshop-mx-startup-20261103-artifact04'
SECRET_SOURCE = 'dynamo-ft-r610-1ec4908b-rr'
OWNER = '/root/startup_textonly'
COMPILE_DIGEST = 'supervl-tp2-native1048576-seqs4-batch8192-textonly-e98d074e-pilot02'
ORIGINAL_CENTRAL_MANIFESTS = previous.central_manifests
ACTIVE_RUN = None


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def status(message):
    record = {'updated_at': base.now(), 'message': message}
    if ACTIVE_RUN is not None:
        write(ACTIVE_RUN.path / 'LIVE_STATUS.json', record)
    print(message, flush=True)


def spec(run):
    return json.loads((run.path / 'spec.json').read_text())


def generate(run, role, native=False):
    objects = ORIGINAL_CENTRAL_MANIFESTS(run, role, native)
    for obj in objects:
        if obj['kind'] != 'DynamoGraphDeployment':
            continue
        for component in obj['spec']['components']:
            if component['type'] == 'worker':
                container = component['podTemplate']['spec']['containers'][0]
                assert '--language-model-only' not in container['args']
                container['args'].append('--language-model-only')
    return objects


def frozen_manifests(run, role, native=False):
    name = 'source' if role == 'source' else 'target-native' if native else 'target-p2p'
    return copy.deepcopy(json.loads((run.path / (name + '.json')).read_text())['items'])


def freeze(run):
    if (run.path / 'inputs-sha256.json').exists():
        verify_inputs(run)
        status('Frozen inputs verified; no Kubernetes activity')
        return
    assert not (run.path / 'spec.json').exists(), 'Incomplete freeze; preserve it and choose a fresh run'
    original = json.loads((RAW / 'spec.json').read_text())
    assert run.state['model_lock'] == original['model_lock']
    historical = json.loads((RAW / 'central-mx-artifacts/result.json').read_text())
    pods = json.loads((RAW / 'central-mx-artifacts/pods.json').read_text())['items']
    pod = next(p for p in pods if p['metadata']['uid'] == historical['pod_uid'])
    c = pod['spec']['containers'][0]
    baseline = {'scope': 'Historical unpaired full-multimodal artifact04 reference, not a contemporaneous control',
                'result': historical, 'spec': original,
                'source_files': {str(p.relative_to(ROOT)): base.digest(p) for p in
                    [RAW / 'spec.json', RAW / 'central-mx-artifacts/result.json', RAW / 'central-mx-artifacts/pods.json']},
                'worker_probes': {k: c[k] for k in ['startupProbe', 'readinessProbe', 'livenessProbe']}}
    write(run.path / 'baseline-reference.json', baseline)
    candidate = copy.deepcopy(original)
    candidate.update(schema=3, script_sha256=base.digest(__file__),
        artifact_helper_sha256=base.digest(previous.__file__),
        shared_helper_sha256=base.digest(base.__file__),
        baseline_reference_sha256=base.digest(run.path / 'baseline-reference.json'),
        sequence=['text-only-source-bootstrap', 'text-only-mx-artifacts'],
        comparison_group='One text-only seed and one matching receiver; historical full-MM reference is unpaired',
        capability='text-only; image and video input capability disabled by --language-model-only',
        changed_worker_args=['--language-model-only'],
        compile_config_digest=COMPILE_DIGEST,
        artifact_transfer={'source': True, 'artifact_target': True},
        pull_secret_source_namespace=SECRET_SOURCE,
        source_publication_types_required=['torch_compile_cache'],
        control_changes='No model/revision/image/context/TP/seq/batch/memory/probe/transport tuning changes',
        engine_compile_caches='Fresh per-Pod filesystem caches; isolated coordinator and text-only artifact identity')
    write(run.path / 'spec.json', candidate)
    (run.path / 'spec.sha256').write_text(base.digest(run.path / 'spec.json') + '\n')
    for name, role, native in [('source','source',False), ('target-native','target',True), ('target-p2p','target',False)]:
        write(run.path / (name + '.json'), {'apiVersion':'v1','kind':'List','items':generate(run, role, native)})
    write(run.path / 'target-artifacts.json', json.loads((run.path / 'target-p2p.json').read_text()))
    write(run.path / 'coordinator.json', {'apiVersion':'v1','kind':'List','items':previous.coordinator_objects(run)})
    paths = [Path(__file__), Path(previous.__file__), Path(base.__file__),
             Path(original['source_template']), Path(original['target_template']),
             ROOT / 'configs/super-vl-tp2-lock.json',
             ROOT / 'configs/upstream/recipes/nemotron-3.5-lightning/vllm/check-efa-userspace.sh']
    paths += [ROOT / 'scripts' / name for name in ['testlib.py','storage_tests.py',
        'common_runtime_tests.py','common_runtime_build.py','serving_tests.py',
        'gpu_claims.py','feature_tests.py']]
    paths += [run.path / name for name in ['spec.json','baseline-reference.json','source.json',
                'target-native.json','target-p2p.json','target-artifacts.json','coordinator.json']]
    write(run.path / 'inputs-sha256.json', {str(p.relative_to(ROOT)):base.digest(p) for p in paths})
    verify_inputs(run)
    status('Text-only pilot frozen locally; no Kubernetes activity')


def verify_inputs(run):
    for name, expected in json.loads((run.path / 'inputs-sha256.json').read_text()).items():
        assert base.digest(ROOT / name) == expected, 'Frozen input changed: ' + name
    s = spec(run)
    assert run.state['model_lock'] == s['model_lock'], 'Run model lock differs from frozen spec'
    assert s['context_length'] == 1048576 and s['max_model_len_override'] is None
    assert s['tensor_parallel_size'] == 2 and s['max_num_seqs'] == 4
    assert s['max_num_batched_tokens'] == 8192 and s['gpu_memory_utilization'] == .85
    assert s['compile_config_digest'] == COMPILE_DIGEST
    for role in ['source','target-p2p']:
        obj = next(o for o in json.loads((run.path / (role+'.json')).read_text())['items'] if o['kind']=='DynamoGraphDeployment')
        c = next(c for c in obj['spec']['components'] if c['type']=='worker')['podTemplate']['spec']['containers'][0]
        assert c['args'].count('--language-model-only') == 1
        assert '--max-model-len' not in c['args']
        assert c['image'] == s['model_lock']['runtime_image']
        assert c['args'][c['args'].index('--revision')+1] == s['model_lock']['revision']
        env = {e['name']:e.get('value') for e in c['env']}
        assert 'MODEL_EXPRESS_URL' not in env
        assert env['MX_ARTIFACT_TRANSFER']=='1' and env['MX_ARTIFACT_COMPILE_CONFIG_DIGEST']==COMPILE_DIGEST


def copy_pull_secret(run):
    """Existing deployment credential stays inside API→process memory→API."""
    source = spec(run)['pull_secret_source_namespace']
    for ns in [source, run.ns]:
        namespace = run.get('get','namespace',ns)
        assert namespace['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by') == 'kubecon-dynamo-feature-tests'
    # Deliberately bypass Run.command: never persist raw Secret stdout.
    result = subprocess.run(run.kbase + ['get','secret','common-runtime-pull','-n',source,'-o','json'],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Unable to read owned source image-pull Secret (body not logged)')
    old = json.loads(result.stdout)
    assert old['metadata'].get('labels',{}).get('feature-test-run') == source
    assert old['type'] == 'kubernetes.io/dockerconfigjson' and '.dockerconfigjson' in old['data']
    found = run.k('get','secret','common-runtime-pull','-n',run.ns,
                  '-o','jsonpath={.metadata.labels.feature-test-run}',check=False)
    assert found.returncode != 0 or found.stdout == run.ns
    obj = {'apiVersion':'v1','kind':'Secret','metadata':{'name':'common-runtime-pull',
           'namespace':run.ns,'labels':run.labels()},'type':old['type'],'data':old['data']}
    content = json.dumps(obj)
    run.k('apply','--dry-run=server','-f','-',input_text=content)
    run.k('apply','-f','-',input_text=content)
    write(run.path / 'pull-secret-copy-metadata.json', {'source_namespace':source,
        'source_secret_uid':old['metadata']['uid'],'target_namespace':run.ns,
        'type':old['type'],'scope':'API-to-API in memory; credential body not persisted'})


def worker_from(directory, role):
    pods = json.loads((directory / 'pods.json').read_text())['items']
    return next(p for p in pods if p['metadata'].get('labels',{}).get('mx-role') == role)


def validate_arm(run, tag, role, result):
    directory = run.path / tag
    pod = worker_from(directory, role)
    c = pod['spec']['containers'][0]
    expected = next(o for o in frozen_manifests(run,role) if o['kind']=='DynamoGraphDeployment')
    expected_c = next(x for x in expected['spec']['components'] if x['type']=='worker')['podTemplate']['spec']['containers'][0]
    assert c['args'] == expected_c['args'] and c['image'] == expected_c['image']
    baseline = json.loads((run.path / 'baseline-reference.json').read_text())
    assert {k:c[k] for k in baseline['worker_probes']} == baseline['worker_probes'], 'Effective probes changed'
    assert pod['spec']['nodeName'] == spec(run)['source_node' if role=='source' else 'target_node']
    assert result['models']['data'][0]['context_window'] == 1048576
    assert all(x.get('restartCount',0)==0 for x in pod['status']['containerStatuses'])
    assert all(x['imageID'].endswith(spec(run)['model_lock']['runtime_image'].split('@')[1]) for x in pod['status']['containerStatuses'])
    gpu_lines=(directory/'gpu-visible.csv').read_text().strip().splitlines()
    assert len(gpu_lines)==2 and all('H100' in x for x in gpu_lines), gpu_lines
    write(directory / 'identity-proof.json', {'passed':True,'worker_uid':pod['metadata']['uid'],
        'native_context':1048576,'text_only_flag':True,'same_effective_probes_as_reference':True})


def cache_proof(run, tag):
    deadline=time.monotonic()+spec(run)['artifact_effectiveness_wait_seconds']
    while True:
        directory=base.collect(run,tag)
        logs=previous.logs_for(run,directory,'target')
        hits=[s for s in logs.splitlines() if 'Directly load AOT compilation from path' in s or 'Directly load the compiled graph(s)' in s]
        ranks=sorted(set(re.findall(r'Worker_TP(\d+)', '\n'.join(hits))))
        selected=[s for s in logs.splitlines() if 'vLLM selected torch.compile cache directory' in s and 'which ModelExpress installed' in s]
        installs=[s for s in logs.splitlines() if 'vLLM artifact install complete:' in s]
        failures=[s for s in logs.splitlines() if ('installed' in s.lower() and any(x in s.lower() for x in ['not used','unused','not reused'])) or 'Compiling model again due to a load failure' in s]
        if failures or (ranks==['0','1'] and selected and any('name=torch_compile_cache ' in s for s in installs)) or time.monotonic()>=deadline:
            break
        time.sleep(5)
    publication=(run.path/'source-artifact-publication.log').read_text()
    source_ids=set(re.findall(r'artifact publish complete:.*?name=torch_compile_cache .*?artifact_id=([0-9a-f]+)',publication))
    installed_ids=set(re.findall(r'vLLM artifact install complete: name=torch_compile_cache artifact_id=([0-9a-f]+)',logs))
    proof={'actual_engine_cache_hit_ranks':ranks,'actual_engine_cache_hit_lines':hits,
        'installed_selection_lines':selected,'artifact_install_lines':installs,
        'source_torch_artifact_ids':sorted(source_ids),'installed_torch_artifact_ids':sorted(installed_ids),
        'failure_lines':failures,'scope':'Distinct TP cache loads, not duplicate selected-cache log count'}
    write(run.path/'artifact-reuse-evidence.json',proof)
    assert ranks==['0','1'] and selected and not failures and installed_ids and installed_ids<=source_ids, proof
    for rank in ['0','1']:
        rank_hits=[s for s in hits if 'Worker_TP'+rank+' ' in s]
        assert any('/tmp/workshop-vllm-cache/torch_compile_cache/' in s and '/rank_'+rank+'_0/model' in s for s in rank_hits)
    return proof


def clean_resources(run):
    namespace=run.get('get','namespace',run.ns)
    assert namespace['metadata'].get('labels',{}).get('app.kubernetes.io/managed-by')=='kubecon-dynamo-feature-tests'
    for graph in ['ft-mx-target','ft-mx']:
        base.stop_graph(run,graph)
    for name in ['mx-coordinator','mx-redis','mx-startup-probe','mx-coordinator-client-check']:
        result=run.k('get','pod',name,'-n',run.ns,'-o','json',check=False)
        if result.returncode==0:
            assert json.loads(result.stdout)['metadata'].get('labels',{}).get('feature-test-run')==run.ns
            run.k('delete','pod',name,'-n',run.ns,'--wait=true','--timeout=90s',timeout=120)
    deadline=time.monotonic()+180
    while True:
        objects={k:run.get('get',k,'-n',run.ns) for k in ['pods','resourceclaims','dgd']}
        gpu=[p['metadata']['name'] for p in objects['pods']['items'] if any(c.get('resources',{}).get('claims') or any('gpu' in k for k in c.get('resources',{}).get('limits',{})) for c in p['spec'].get('containers',[]))]
        proof={'at':base.now(),'namespace':run.ns,'gpu_pods':gpu,
               'resourceclaims':[x['metadata']['name'] for x in objects['resourceclaims']['items']],
               'graphs':[x['metadata']['name'] for x in objects['dgd']['items']],
               'coordinator_pods':[x['metadata']['name'] for x in objects['pods']['items'] if x['metadata']['name'] in ['mx-coordinator','mx-redis']]}
        write(run.path/'cleanup-raw.json',objects)
        if not any(proof[k] for k in ['gpu_pods','resourceclaims','graphs','coordinator_pods']):
            break
        if time.monotonic()>=deadline:
            write(run.path/'cleanup-proof.json',dict(proof,verified=False));raise RuntimeError('Owned cleanup not verified')
        time.sleep(5)
    if base.LEASE.exists():
        base.release(run)  # Refuses another owner/run; never deletes another lease.
    proof.update(verified=True,gpu_lease_absent=not base.LEASE.exists())
    assert proof['gpu_lease_absent']
    write(run.path/'cleanup-proof.json',proof)


def batch(run):
    verify_inputs(run)
    assert run.state.get('checks',{}).get('mx-artifact-coordinator',{}).get('status')=='passed'
    assert not (run.path/'batch-started.json').exists(), 'No automatic replay of a started pilot'
    base.acquire(run)
    write(run.path/'batch-started.json',{'at':base.now(),'controller_pid':os.getpid()})
    try:
        source=previous.run_arm(run,'text-only-source-bootstrap','source')
        validate_arm(run,'text-only-source-bootstrap','source',source)
        status('Text-only source Ready; waiting for its compiler-artifact publication')
        previous.await_artifact_publication(run)
        # Keep the same idle source UID alive throughout the receiver arm.
        retained=source['pod_uid']
        target=previous.run_arm(run,'text-only-mx-artifacts','target')
        validate_arm(run,'text-only-mx-artifacts','target',target)
        live=worker_from(run.path/'text-only-mx-artifacts','source')
        assert live['metadata']['uid']==retained and all(c.get('restartCount',0)==0 for c in live['status']['containerStatuses'])
        assert any(c['type']=='Ready' and c['status']=='True' for c in live['status']['conditions'])
        status('Text-only receiver Ready and correct; validating both TP compiler-cache loads')
        cache_proof(run,'text-only-mx-artifacts')
        baseline=json.loads((run.path/'baseline-reference.json').read_text())['result']
        comparison={'candidate':target,'source':source,'historical_full_mm_reference':baseline,
            'historical_ready_seconds_minus_candidate':baseline['apply_to_ready_observed_seconds']-target['apply_to_ready_observed_seconds'],
            'scope':'N=1 text-only pilot versus historical unpaired full-MM reference; capability change, not equivalent vision-serving performance'}
        write(run.path/'comparison.json',comparison)
        run.result('text-only-pilot','passed',candidate_ready_seconds=target['apply_to_ready_observed_seconds'])
    except Exception as error:
        try: base.collect(run,'failed-attempt')
        finally: run.result('text-only-pilot','failed',error=repr(error))
        raise
    finally:
        clean_resources(run)
        seal(run)


def seal(run):
    write(run.path/'evidence-sha256.json',{str(p.relative_to(run.path)):base.digest(p) for p in run.path.rglob('*') if p.is_file() and p.name!='evidence-sha256.json'})


def configure(run):
    global ACTIVE_RUN
    ACTIVE_RUN=run
    base.OWNER=OWNER
    base.REPORT=HERE
    base.status=status
    base.frozen_spec=spec
    base.pull_secret=copy_pull_secret
    base.manifests=frozen_manifests
    base.get_pods=previous.coordinator_healthy_get_pods
    previous.COMPILE_DIGEST=COMPILE_DIGEST
    previous.MODE='artifacts'
    previous.artifact_spec=spec
    previous.central_manifests=frozen_manifests


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['freeze','verify','prepare','batch','cleanup'])
    parser.add_argument('--run',type=Path,required=True)
    args=parser.parse_args()
    run=base.setup_run(args.run)
    configure(run)
    if args.action=='freeze':
        freeze(run)
        return
    verify_inputs(run)
    if args.action=='verify':status('Frozen pilot inputs verified locally; no Kubernetes activity')
    elif args.action=='prepare':
        previous.prepare(run)
        verify_inputs(run)
    elif args.action=='batch':batch(run)
    else:
        clean_resources(run)
        seal(run)


if __name__=='__main__':main()
