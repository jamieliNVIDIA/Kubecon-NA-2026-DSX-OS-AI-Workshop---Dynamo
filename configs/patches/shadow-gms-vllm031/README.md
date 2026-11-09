# Shadow-only GMS / vLLM 0.31 compatibility overlay

The qualified common image contains a GMS `request_memory` wrapper with two
arguments. vLLM `0.31.1rc1.dev23+g43b4aaea3` calls it with a third
`external_weight_memory` argument. The unmodified preferred-model Shadow worker
failed before loading weights with:

```
TypeError: patch_request_memory.<locals>.patched_request_memory() takes 2 positional arguments but 3 were given
```

`patches.py` is the installed GMS module with a narrow compatibility change:
accept the optional third argument, subtract external weights from the private
engine budget, and reject an exhausted budget. The existing Shadow behavior
that bypasses the ordinary free-memory check is retained. Source license
headers are preserved. Four offline tests exercise the modified function
without importing CUDA.

The live harness saves the original module under its private `runtime-sources/`
evidence directory, records both module hashes, and installs an immutable
ConfigMap. The DGD mounts the patched module read-only into the owned engine
containers using a subPath; a Pod annotation identifies its SHA-256. The
underlying image, GMS sidecar and shared cluster components are not modified.

Prepare this overlay only after capturing the failing runtime's source:

```sh
.local/venv/bin/python scripts/shadow_live_tests.py sources --run results/<shadow-run>
.local/venv/bin/python scripts/shadow_live_tests.py prepare-patch --run results/<shadow-run>
.local/venv/bin/python scripts/shadow_failover_tests.py dry-run --run results/<shadow-run>
```

This is experimental test instrumentation. It does not by itself qualify
Nemotron GMS startup, parked-standby behavior or recovery; those need separate
live receipts. A passing overlay test must be identified as image plus overlay,
rather than a pass of the unmodified common image.
