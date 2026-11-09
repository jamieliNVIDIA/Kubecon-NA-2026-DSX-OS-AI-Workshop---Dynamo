# Connectivity outage before the first AgentX profile

No AgentX inference profile or performance request ran. The first RR worker was
deployed at 00:59:06 UTC on October 31, 2026, but API connectivity failed while
the controller waited for serving readiness. The first arm directory
`results/workshop-rr-20261030-prep-1705/c1-r1-a2/` remains empty. The second
replica, C4 pair, and matched routing-policy extension were not started.

The controller's durable failure at 01:27:53 UTC records TLS handshake timeouts,
followed by loopback connection refusal. Its cleanup also failed to reach the
API, so it correctly retained the exclusive GPU lease. No RR controller remains
running. The lease must remain until owned DGD/Pod/ResourceClaim cleanup is
verified; elapsed Pod deadlines alone do not prove that a controller has not
replaced a failed worker.

Recovery probes could not reach the same workshop jump host `3.238.63.5:22`.
Direct SSH timed out; the repository's documented Gemini jump path timed out
during banner exchange. The current route uses home interface `en0` and gateway
`192.168.68.1`; a prior successful repository diagnostic used the corporate VPN
interface `utun4`. Restoring the workshop VPN/jump-host network path is the
external gate. No alternate cluster/model or global network setting was used.

The CPU-only full-corpus qualification remains valid historical evidence:
393 roots, 9,450 reconstructed children, 98,827 turns, 484.70 seconds, and
31,983,284,224-byte container peak. It does not establish that the expired
client's local mmap still exists. The short native-context correctness proof
from the MX source also remains valid; it is not an AgentX performance result.

## Recovery after the same workshop host becomes reachable

1. Restore the existing tunnel with `bash scripts/kubecon-tunnel.sh start`.
2. Confirm no earlier controller is running. Keep this workstream's retained
   lease while gathering the owned workload state.
3. Collect current logs/state and clean only the owned GPU resources:

   ```bash
   .local/venv/bin/python \
     reports/workshop-measurements-20261030/round-robin/recover_owned_resources.py \
     --run results/workshop-rr-20261030-prep-1705 \
     --label UNIQUE-LOWERCASE-LABEL --cleanup
   ```

4. Recheck the CPU client, its actual image/environment and cache hashes. Its
   eight-hour deadline may have expired. If recreation is needed, use a fresh
   ignored run/namespace and repeat full CPU qualification with the same pinned
   source/corpus/seed and serial reconstruction settings. Do not trust the old
   local `client-precache.json` marker for a replacement Pod.
5. Coordinate the next GPU lease with MX. Start a fresh immutable C1 attempt;
   preserve the interrupted attempt and all original C1/C4/router-policy
   settings. Resolve endpoint semantics and seal fresh per-arm specs as planned.

The old worker had a four-hour Pod deadline. Current liveness, GPU claims,
readiness and cache availability remain unverified during the outage.
