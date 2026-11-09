# Development MX RAM cache

This package contains the MX RAM-cache tooling used during development to speed
up repeated runs, including the dec-only setup. It is separate from the
[ModelExpress presenter](../../../demos/modelexpress/README.md), which demonstrates
peer weight loading against a matched storage baseline.

| Module | Role |
| --- | --- |
| [workflow.py](workflow.py) | Bind the cache to an exact producer, render a CPU staging probe and validate its qualification evidence |
| [render_server.py](render_server.py) | Render the owned RAM-backed server, Redis and immutable seed inputs |
| [render_probe.py](render_probe.py) | Render the initial CPU client/server capability probe |
| [seed.py](seed.py) | Populate the server cache from pinned HF files and verify their Git/LFS content identities |
| [stage.py](stage.py) | Stage files from the exact qualified producer into a client cache with hash and resource checks |
| [probe.py](probe.py) | Exercise the MX RPC/file-stream contract from the CPU probe container |

Inspect the host tool interfaces from the repository root:

```bash
uv run python -m scripts.development.mx_cache.render_server --help
uv run python -m scripts.development.mx_cache.workflow --help
```

Rendering writes a fresh output directory. Review its manifests and frozen
inputs before applying them. The seed, stage and RPC probe modules are also
embedded in generated container workloads; those workloads supply their paths,
environment and memory limits.

Development-only Shadow candidates can pass the workflow's accepted receipt to
`shadow-composed freeze --dev-cache-qualification RECEIPT.json`. This optional
compatibility argument is omitted from presenter help; its source, producer and
hash checks still apply. Ordinary presenter preparation does not require the
RAM cache.

A reusable cache needs the exact model revision, complete file inventory,
content hashes, producer Pod identity and passed CPU staging evidence. RAM
contents disappear when the server Pod is replaced. Preserve the owned
resource lifecycle and requalify a changed producer or source. Cached loading
alone does not qualify a new performance result or Shadow recovery.
