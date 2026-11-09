# Take home: deploy a Dynamo-managed coding service

**Tested baseline candidate.** The unmodified public nightly below passed
cached Super VL serving on two H100s using GPU DRA, an explicit UID 0 cache
profile and a Dynamo-managed frontend/worker. The actual coding response and
scoped cleanup passed. [Qualification evidence](QUALIFICATION.md) separates the
failed attempts and the tested Service-selector correction.

This is a pinned nightly candidate, not a stable production release. Fresh
network weight download, device-plugin serving and attendee storage/Pod-policy
combinations still need their own checks. No advanced feature composition is
implied by the baseline result.

The first investigation is deliberately small: one CPU HTTP frontend and one
vLLM replica using two GPUs, managed by the Dynamo operator. Send a coding
request, identify the resources the operator created, and explain where startup
time went. [Later investigations](INVESTIGATIONS.md) build on this service.

## 1. Check your environment

An administrator must provide these prerequisites. This exercise does not
install or upgrade shared operators, drivers or GPU allocation services.

| Requirement | Baseline used by this workshop |
| --- | --- |
| Model | `nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4`, revision `8a115b9d966adce8c059a7bcf47f49a1e57957d8`; text-only input |
| GPUs | Two H100 80 GB GPUs on one node per replica; TP2. Other GPU models or parallelism need qualification. |
| Serving resources | Worker requests 8 CPU / 128 GiB host RAM, memory limit 256 GiB; frontend requests 1 CPU / 4 GiB, limit 8 GiB. These inherited bounds are not measured minimums. |
| Cache | Existing dedicated ReadWriteMany PVC in your namespace, accessible by frontend, worker and downloader. Weights alone occupy approximately 75 GB; 120 GiB is a suggested starting allocation, not a measured minimum. Download/JIT/temp space needs headroom. |
| Dynamo | Operator supporting `nvidia.com/v1beta1` DGDs with `spec.components`; access to its service-discovery dependencies and compatible runtime version |
| Runtime | The same accessible, digest-pinned image for frontend, worker and downloader, supporting this model, `nemotron_v3`, `--language-model-only` and the rendered flags |
| GPU allocation | Either an existing NVIDIA device plugin exposing `nvidia.com/gpu`, or an existing GPU DRA driver exposing `gpu.nvidia.com` and `resource.k8s.io/v1` claims. Choose your cluster's mode. |
| Access | Namespace-scoped rights to create DGDs, Pods/Jobs and Services; existing registry pull secret if required; outbound Hugging Face access during download |

The renderer retains the tested H100 node-product affinity and GPU taint
toleration. Confirm your cluster uses those labels/taints. It also retains the
worker's root/IPC-lock/resource capabilities; the administrator must check the
Pod policy before deployment. RWO cache storage needs a different placement or
cache-distribution plan; it is not the shared-PVC profile below.

Use your normal `kubectl` context. **Do not source `scripts/kubecon-env.sh`** for
an attendee cluster: that file selects the presenters' private cluster.

```bash
kubectl config current-context
kubectl api-resources --api-group=nvidia.com
kubectl explain dynamographdeployment.spec.components
kubectl get nodes -L nvidia.com/gpu.product
```

Set the namespace and choose an image and operator-compatible `X.Y.Z` version
provided by the release owner. A nightly package version such as
`1.7.0.dev20261103` is distinct from the CRD compatibility override `1.7.0`;
the renderer rejects prerelease suffixes in that override.
The image/version below are the tested candidate. Replace the namespace/PVC
with your own values. The tested cached profile uses UID 0; the PVC must be
writable by that identity and the Pod policy must permit it. Other identities
need compatible cache permissions and their own serving check. The renderer
never changes file ownership, substitutes an image or switches models.

```bash
ATTENDEE_NS=your-workshop-namespace
DYNAMO_IMAGE='nvcr.io/nvidia/ai-dynamo/vllm-runtime-nightly@sha256:c186817f4669d615d2b14bee5a6119d35d4d0fe186fdfab69920da8de9d09337'
DYNAMO_RUNTIME_VERSION='1.7.0'
MODEL_CACHE_PVC=your-model-cache
CACHE_UID=0
kubectl -n "$ATTENDEE_NS" get pvc "$MODEL_CACHE_PVC"
```

## 2. Generate and inspect your manifests

From a clone of this repository, install its small Python dependency locally:

```bash
uv sync --locked
uv run python take-home/render.py \
  --namespace "$ATTENDEE_NS" \
  --runtime-image "$DYNAMO_IMAGE" \
  --runtime-version "$DYNAMO_RUNTIME_VERSION" \
  --cache-pvc "$MODEL_CACHE_PVC" \
  --run-as-user "$CACHE_UID" \
  --gpu-mode dra \
  --output results/my-take-home
```

Kubernetes 1.34+ and a working GPU DRA installation are the live-tested
combination. For an existing device-plugin cluster, use `--gpu-mode device-plugin`
instead; that generated profile passed dry-runs but has not been served on this
DRA-only workshop cluster. This changes only the generated GPU request. It does not install a driver or disable another
allocator. If registry authentication is required, add
`--image-pull-secret YOUR_EXISTING_SECRET_NAME`.

If a prepared cache lives in an existing directory within the PVC, add
`--cache-subpath prepared/model-cache`. This must be a relative path without
`.` or `..` segments; the directory must already exist. All three components
then mount that same directory at `/model-cache`, so its Hugging Face cache
must be under `prepared/model-cache/hf`. Kubernetes rejects unsafe subPath
mounts, including symlink escapes. A cached deployment does not measure a fresh
download or its storage requirements.

The downloader and frontend otherwise use the image's default UID; the worker
retains the template's explicit security settings. The PVC directory must be
readable by serving components and writable by the downloader. If your
administrator supplies a specific identity, use `--run-as-user UID` to set it
consistently for all three components. This option changes Pod execution identity,
not file ownership or permissions. The qualification reused a root-owned cache
with explicit UID 0; that is an environment-specific profile, not a requirement
to make attendee caches root-owned.

The default resource name is `coding-agent`; `--name` selects another. The
remaining commands assume the default. The output directory must be new.
`profile.json` records model/image identity and hashes of sources and generated
files. The renderer never contacts Kubernetes and never modifies workshop locks.
Presenter-only `WORKSHOP_ALLOCATION` settings are deliberately ignored, including
stale or missing assignment files. No workshop node name or physical GPU UUID
is copied into the attendee manifests.

```bash
cat results/my-take-home/deployment.yaml
cat results/my-take-home/profile.json
kubectl -n "$ATTENDEE_NS" apply --dry-run=client \
  -f results/my-take-home/deployment.yaml
kubectl -n "$ATTENDEE_NS" apply --dry-run=server \
  -f results/my-take-home/deployment.yaml
```

For DRA, also dry-run `gpu-claim-template.yaml`. Dry-run the download Job and
frontend Service as well. Resolve schema, Pod-policy, storage and image-access
errors before continuing. Dry-runs do not establish available HBM or compatible
inference kernels.

## 3. Download the exact checkpoint before serving

The CPU-only Job writes the Hugging Face cache under `/model-cache/hf`, which
is the path used by both serving components. It downloads the frozen revision,
checks metadata hashes and weight-file presence, then checks the runtime's actual
model-metadata resolver in an offline subprocess. It does not allocate GPUs or
benchmark storage.

The current workshop runtime registers model metadata without carrying the
engine's explicit revision through every lookup. The Job therefore pins the
dedicated cache's `refs/main` to the same revision. It refuses a different existing
reference and never overwrites it. This is a compatibility workaround for this
exercise; revision-aware registration is tracked upstream in
[Dynamo #11369](https://github.com/ai-dynamo/dynamo/pull/11369). A newer runtime
still needs the offline check before this workaround can be removed.

```bash
kubectl -n "$ATTENDEE_NS" apply -f results/my-take-home/download-job.yaml
kubectl -n "$ATTENDEE_NS" logs -f job/coding-agent-download
kubectl -n "$ATTENDEE_NS" wait --for=condition=complete \
  job/coding-agent-download --timeout=4h
```

The model is marked ungated in the workshop lock. Verify current model terms
and access on Hugging Face. The generated manifests contain no tokens. If your
environment requires authentication, provision it through your normal secret
workflow for all components that access model metadata.

The serving Pods use `HF_HUB_OFFLINE=1`; a missing cache file is a preparation
failure, rather than an invitation to silently download a different revision.

## 4. Let the operator create the service

For **DRA only**, apply the generated claim template before the DGD:

```bash
kubectl -n "$ATTENDEE_NS" apply -f results/my-take-home/gpu-claim-template.yaml
```

For either GPU mode:

```bash
kubectl -n "$ATTENDEE_NS" apply -f results/my-take-home/deployment.yaml
kubectl -n "$ATTENDEE_NS" apply -f results/my-take-home/frontend-service.yaml
kubectl -n "$ATTENDEE_NS" get dgd,deployments,pods,services
kubectl -n "$ATTENDEE_NS" logs -f -l workshop-service=coding-agent,workshop-role=worker \
  -c main --timestamps --prefix
```

After inspecting the logs, stop log-following with Ctrl-C and wait for Pod
readiness. Model loading and engine initialization can take several minutes;
the intro profile uses eager execution but still performs kernel warm-up.

```bash
kubectl -n "$ATTENDEE_NS" wait --for=condition=Ready pod \
  -l workshop-service=coding-agent,workshop-role --timeout=30m
kubectl -n "$ATTENDEE_NS" port-forward service/coding-agent-http 18000:8000
```

Keep the port-forward running. In another terminal, from the repository root:

```bash
curl --fail-with-body --silent --show-error http://127.0.0.1:18000/v1/models \
  > results/my-take-home/models.json
curl --fail-with-body --silent --show-error http://127.0.0.1:18000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  --data-binary @results/my-take-home/request.json \
  > results/my-take-home/response.json
uv run python take-home/check-response.py results/my-take-home
```

Pod Running is insufficient. Require the expected model in `/v1/models`,
nonempty assistant content, the expected response model and normal completion.
The check does not execute generated code or establish performance/correctness.

Save the observed Pods, runtime image IDs and timestamped worker logs beside
the profile. Separate checkpoint download, image pull, scheduling, weight loading,
initialization and readiness when explaining startup; overlapping phases do not
sum to a useful total. Never copy registry credentials into shared recordings.

## 5. Stop the service; retain the checkpoint intentionally

Stop the port-forward with Ctrl-C. Delete the DGD first so its controller stops
recreating workers. These commands target only the named take-home resources;
they keep the namespace, PVC and downloaded checkpoint.

```bash
kubectl -n "$ATTENDEE_NS" delete -f results/my-take-home/deployment.yaml
kubectl -n "$ATTENDEE_NS" delete -f results/my-take-home/frontend-service.yaml
kubectl -n "$ATTENDEE_NS" delete -f results/my-take-home/download-job.yaml
kubectl -n "$ATTENDEE_NS" get pods -l workshop-service=coding-agent
```

For DRA, inspect the remaining ResourceClaims and wait for the owned Pods/claims
to disappear, then delete `gpu-claim-template.yaml`. Do not remove other users'
claims or delete a namespace containing resources you did not create.

## Release questions before this becomes attendee-ready

- Select the release runtime and supported operator matrix. The pinned public
  nightly/cached DRA baseline is tested; stable-release, device-plugin and other
  cluster profiles remain separate qualifications.
- Confirm model redistribution/access, downloadable trace rights, cache
  preparation duration and practical storage capacity.
- Qualify the storage/Pod-policy profile outside the presenters' EFS cluster.
- Decide whether this model's two-H100 baseline is an acceptable attendee
  requirement. A smaller alternate exercise would need its own model identity,
  instructions and validation; it must not inherit Super VL performance claims.

For workshop evidence and its exact scope, see the
[first-deployment guide](../demos/single_replica/README.md) and
[recordings status](../reports/workshop-demo-recordings/STATUS.md).

Maintainer validation uses a separate [qualification harness](QUALIFICATION.md)
with exact test GPU fencing. It is not an attendee prerequisite and does not
change the portable manifests' default allocation behavior.
