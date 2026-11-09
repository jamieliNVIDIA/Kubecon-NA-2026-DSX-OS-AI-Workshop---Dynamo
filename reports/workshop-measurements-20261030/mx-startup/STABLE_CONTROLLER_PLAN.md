# Stable controller handoff

The first C4 arm completed inside the cluster and was recovered unchanged:
122 valid requests, zero errors, original profile/spec and client/worker UIDs.
The next command completes only its original second arm, retaining the first
worker. It does not replay the accepted arm.

## Reviewed payload

- Bundle: `results/workshop-stable-controller-20261103/controller-bundle.tar.gz`.
- SHA256: `4556d4912734832c9c5e85d3a20af66db928ea14749044a9ca582e168bc21741`.
- 314 explicitly listed files, 78,088,392 bytes before compression,
  6,196,153 bytes compressed. See `bundle-manifest.json` for every file/hash.
- Includes the original 128 frozen inputs, current continuation helpers,
  accepted C1 evidence/references, recovered C4 first-arm evidence, current
  state/required CPU qualification and Ready-Pod receipts, consumed MX inputs,
  lease metadata, and PyYAML 6.0.3 pure Python sources.
- Excludes kubeconfigs, AWS/Git directories, model weights, source datasets,
  client virtual environments, Secret manifests and raw get-secret receipts.
  Structured credential checks passed for the selected data files.

## Runtime and authority

Use the existing bastion Docker daemon and its already cached native-amd64
controller image:
`docker.io/library/python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337`.
This is separate from the unchanged inference image.

Bind only the owned staged workspace at the exact original logical path inside
the container: `/Users/nealv/Documents/dynamo/dynamo-kubecon-workshop`. Mount the
bastion's existing Linux kubectl and kubeconfig read-only at the expected paths.
The existing kubeconfig uses embedded certificate/key/CA data and reaches the
internal API directly; no credentials are copied and no RBAC changes are needed.
No Docker socket, SSH directory, model cache or host home directory is mounted.

Before launch, root verifies no local controller remains and explicitly sets
the two gates in `controller-delegation.template.json`. Keep the original local
lease as a delegation sentinel; no local GPU execution or cleanup may compete
with the remote controller. Its copied lease retains the original identity.
Record the image/container ID, Python/PyYAML and Linux kubectl versions/hashes.

The detached container runs the fixed second-arm helper, then the fixed remaining
workflow only on success. It has no automatic restart. API or identity failures
retain ownership/stop further work; later stages require verified cleanup.

## Measurement and result provenance

The cluster-local AIPerf client, serving workers, workload, model and settings
are unchanged. Record the controller move and idle interval between C4 arms.
All MX target arms run on the same stable observer and are compared only within
artifact04. Preserve the original absolute paths and scientific specification
bytes rather than rewriting them for another host.

The bundle is a consumed-input subset, not a replacement for the complete local
evidence archive. After execution, retrieve new results byte-for-byte, validate
their inventories, merge with retained original preflight evidence, and seal
the complete local inventories. Verify remote zero GPU Pods/claims/graphs and
absent lease before removing the local delegation sentinel. Preserve the
detached container's terminal status/logs and never replay completed arms.
