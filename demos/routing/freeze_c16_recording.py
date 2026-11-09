#!/usr/bin/env python3
"""Freeze the independently accepted C16 cells; no network or cluster operations."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import demos.common.runtime as ui
import demos.routing.demo as base
import demos.routing.recording as c16

COLLECTION = ROOT / 'results/workshop-routing-overnight-collection-recovered-20261105-0739'
PREPARATION = ROOT / 'results/workshop-routing-overnight-controller-prep-20261105-a1'
RUN = 'results/workshop-routing-overnight-20261105-a1'


def freeze(destination, collection=COLLECTION, preparation=PREPARATION):
    base.require(not destination.exists(), 'Recording destinations are immutable; use a fresh output path.')
    verification = ui.read_json(collection / 'verification.json')
    acceptance = ui.read_json(collection / 'independent-acceptance-and-cleanup.json')
    base.require(verification['verified'] and verification['files'] == acceptance['transport_files_verified'] == 1040 and
                 ui.digest(collection / 'evidence.tar.gz') == verification['archive_sha256'], 'Accepted C16 transport changed.')
    transported = ui.read_json(collection / 'verified/collection-manifest.json')
    for name, record in transported['files'].items():
        path = base.relative_file(collection / 'verified', name)
        base.require(path.stat().st_size == record['bytes'] and ui.digest(path) == record['sha256'],
                     'Transported C16 bytes changed: ' + name)
    payload = ui.read_json(preparation / 'payload-manifest.json')
    plan = ui.read_json(preparation / 'plan.json')
    base.require(ui.digest(preparation / 'plan.json') == acceptance['plan_sha256'] == payload['plan_sha256'],
                 'Accepted C16 frozen launch plan changed.')
    written_plan = None
    with tarfile.open(preparation / 'payload.tar.gz') as archive:
        for name, record in payload['files'].items():
            members = [member for member in archive.getmembers() if member.name == name and member.isfile()]
            base.require(len(members) == 1, 'Missing or ambiguous frozen payload member: ' + name)
            raw = archive.extractfile(members[0]).read()
            base.require(len(raw) == record['bytes'] and hashlib.sha256(raw).hexdigest() == record['sha256'],
                         'C16 frozen payload changed: ' + name)
            if name in plan['source_sha256']:
                base.require(record['sha256'] == plan['source_sha256'][name], 'C16 frozen source changed: ' + name)
            else:
                base.require(name in {payload['plan'], plan['run'] + '/state.json'}, 'Unexpected unplanned payload member.')
                if name == payload['plan']:
                    base.require(record['sha256'] == payload['plan_sha256'], 'Payload plan bytes changed.')
            if name == 'reports/overnight-2026-11-04/routing-sweep/PLAN.md':
                written_plan = raw
    base.require(written_plan is not None and len(payload['files']) == acceptance['frozen_payload_files_verified'] == 47,
                 'C16 frozen payload/experiment plan is incomplete.')
    source = collection / 'verified' / RUN
    sources = {'analysis.json': collection / 'analysis.json', 'collection-verification.json': collection / 'verification.json',
        'independent-acceptance.json': collection / 'independent-acceptance-and-cleanup.json',
        'campaign.json': source / 'campaign.json', 'inputs-sha256.json': source / 'inputs-sha256.json',
        'plan.json': preparation / 'plan.json', 'payload-manifest.json': preparation / 'payload-manifest.json',
        'deployment-one-rr.json': source / 'deployment-one-rr.json',
        'policy-round-robin-deployment.json': source / 'deployment-two-rr.json',
        'policy-kv-deployment.json': source / 'deployment-two-kv.json'}
    for arm in c16.ARMS:
        for name in c16.CELL_FILES:
            if name == 'pod-identities.json':
                continue
            original = f'raw/{arm}/artifacts/profile_export_aiperf.json' if name == 'aiperf.json' else name
            sources[f'cells/{arm}/{name}'] = source / arm / original
    destination.mkdir(parents=True)
    for name, path in sources.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(path.read_bytes())
    (destination / 'frozen-plan.md').write_bytes(written_plan)
    for arm in c16.ARMS:
        original = source / arm / 'pods.json'
        pods = ui.read_json(original)['items']
        identities = {'source_file_sha256': ui.digest(original), 'scope': 'Identity/runtime excerpt; Pod environment omitted.',
            'items': [{'metadata': {key: pod['metadata'][key] for key in ('name', 'uid')},
                       'spec': {'nodeName': pod['spec']['nodeName'], 'containers': [
                           {key: container.get(key) for key in ('name', 'image', 'args')}
                           for container in pod['spec']['containers']]},
                       'status': {'podIP': pod['status'].get('podIP'), 'containerStatuses': [
                           {key: status.get(key) for key in ('name', 'imageID', 'ready', 'restartCount')}
                           for status in pod['status'].get('containerStatuses', [])]}}
                      for pod in pods]}
        ui.write_json(destination / f'cells/{arm}/pod-identities.json', identities)
    metadata = {'schema': 2, 'profile': c16.PROFILE, 'measurement_class': 'fixed-order-c16-observation',
        'frozen_at': ui.now(), 'source_archive_sha256': verification['archive_sha256'],
        'sources': {name: str(path.relative_to(ROOT)) for name, path in sources.items()},
        'identity_excerpt_sources': {f'cells/{arm}/pod-identities.json': str((source / arm / 'pods.json').relative_to(ROOT))
                                    for arm in c16.ARMS},
        'files_sha256': {name: ui.digest(destination / name) for name in sorted(c16.FILES)},
        'import_verification': {'transport_files_rechecked': len(transported['files']),
                                'frozen_payload_members_rechecked': len(payload['files'])},
        'scope': 'Three accepted AgentX C16 cells, N=1 fixed order, fresh workers per cell, engine cap128. '
                 'Realized mixes differ; concurrent disjoint GPU tests share CPU/storage/network. No capacity-knee claim. '
                 'C32 failed before profiling and is not a performance result.'}
    ui.write_json(destination / 'recording.json', metadata)
    c16.load_recording(destination)
    print(json.dumps({'recording': str(destination), 'source_files': len(c16.FILES),
        'transport_files_rechecked': len(transported['files']), 'frozen_payload_members_rechecked': len(payload['files']),
        'recording_sha256': ui.digest(destination / 'recording.json')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--collection', type=Path, default=COLLECTION)
    parser.add_argument('--preparation', type=Path, default=PREPARATION)
    args = parser.parse_args()
    freeze(args.output.resolve(), args.collection.resolve(), args.preparation.resolve())
