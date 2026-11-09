# Workshop presentation review — November 7 UTC

This pass applies the lessons from the current chat and **Fix demo 1 Kubernetes
connection** across the workshop. It preserves the existing intro/MX servers,
their frozen startup evidence, historical recordings and experimental runtime
contracts. No GPU workload was launched or removed for this review.

## Presentation and sequence

- [Presenter runbook](../../demos/RUNBOOK.md) follows the actual talk order while
  retaining stable demo IDs. It identifies live and recorded stops, offstage
  setup, source dependencies and explicit profile transitions.
- Setup happens before the audience walkthrough. Snapshot, continuity, KVCR and
  Shadow require their primed resources before opening a presentation. P/D now
  has an actual optional `prime` that starts both pools offstage.
- Recorded routing and metrics require offstage validation too. Their pane
  titles describe recorded evidence rather than Kubernetes startup.
- Generic step timers are removed: those timers included presenter keypress
  waits. Actual startup, restore, failover and request measurements remain.
- Snapshot variants share the stage loop and retain absolute stage numbers
  when resuming a replacement. Teaching settings come from effective frozen
  manifests rather than parallel hardcoded examples.
- Commands wrap between shell arguments without changing the executed argv.
  Prompts and generated code display as readable text; full JSON and traces
  remain in run artifacts.

## Shared structure and reliability

- [startup.py](../../demos/common/startup.py) contains pure timing/readiness
  parsing and display. The shared runtime retains public aliases for existing
  callers; the extracted implementation is unchanged and imports only the
  standard library.
- [presentation.py](../../demos/common/presentation.py) shares command, prompt,
  response and prose formatting.
- [status.py](../../demos/common/status.py) powers `uv run python -m demos status`.
  It reports selected runs, recorded state, source/dependent relationships and
  reservations without cluster calls or state writes. Its scope explicitly
  excludes a live readiness check.
- Completed intro startup is revalidated and replayed without rewriting
  `worker.log`, `ready-pods.json` or `timing.json`. Revisiting demo 1 therefore
  preserves the baseline already bound by ModelExpress.
- Shared resource observers use bounded reads, match worker phases by name,
  identify stale saved timings, and handle malformed API snapshots safely.
  Status also distinguishes a pending DGD replacement from its older Ready
  observation.
- Live-only variants give direct guidance to the standard offline demo;
  unsupported rehearsals do not bypass their source/repair/reader checks.

## Validation

Baseline and updated source snapshots, audit notes and detailed rehearsal
captures are retained under `.local/overnight-review-20261107T070128Z/`.

- Baseline: nine canonical rehearsals and 18 resource/log observer checks.
- Updated flow: ten rehearsals, including DGD Snapshot, and 20 observer checks.
  Preparation banners, removed plumbing notes and generic timing footers are
  absent. Observer checks preserved every saved-run file and selected pointer.
- Normal routing and metrics: unprepared run/capture refusal, explicit
  preparation, bare selected playback and recorded-evidence capture all passed.
  The 49 pinned recording/definition files remain byte-identical.
- Independent integration review found no P1 regression. Its two concrete P2
  findings—pending-replacement status and malformed resource metadata—were
  fixed and covered by focused regressions.
- Linux regression suite: **886 tests, successful, with 27 optional archived-data
  skips**, in an isolated source tree with no kubeconfig or Kubernetes client.
- Real Linux tmux: **ten detached walkthroughs and twenty observer panes** passed
  at a 180×50 layout. They survived the first SSH connection ending, retained
  their saved evidence and used the correct recorded-mode pane titles. The
  dedicated QA tmux server was then stopped; production sessions were untouched.
- Live read-only check: completed intro replay preserved its original timing;
  the MX binding and source/target physical GPU identities remained valid.
  Every file in both live run directories, both selections and the reservation
  remained byte-identical. The same four Pods remained Ready without restarts.
- **308 protected inputs** remained unchanged: configurations, demo evidence,
  metric definitions/assets and compatibility protocol sources.

Delivery provenance and Linux logs are retained on the jumpbox under
`/home/ubuntu/workshop-source-backups/20261107T070128Z-overnight/`.
The source update is restricted to the reviewed delivery manifest; it does not
replace environments, credentials, reservations, run results or Git metadata.

## Qualification limits and next preparation

Rehearsal and presentation changes do not establish new GPU startup, throughput,
KV transfer, request continuity or recovery results. Existing source identities,
failed-fault checks, no-fallback checks and experimental feature gates remain.

The intro/MX pair can remain running across the recorded metrics and routing
stops. Later compiled or experimental profiles need their own qualified
workers. Default exclusive reservations and fixed GPU/EFA placements prevent
assuming every live group can remain primed concurrently. The runbook makes
those cleanup boundaries explicit; a fully prewarmed workshop needs a separate,
verified disjoint allocation plan. Some existing prime paths take 25–45 minutes,
so they must be scheduled before the presentation slot.

Changes remain in the working tree for review; this pass does not publish a new
commit or push a branch.
