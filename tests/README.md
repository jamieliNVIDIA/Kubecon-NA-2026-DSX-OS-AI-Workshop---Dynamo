# Regression tests

Run tests from the repository root with the same environment as the demos:

```bash
uv run python -B -m tests
uv run python -B -m tests shadow -v
uv run python -B -m tests development.mx_cache
```

The optional group selects one feature. `--pattern 'test_reader*.py'` narrows
filenames within that group; `-q` prints only the result summary. Groups accept
either dots or slashes, such as `development.mx_cache` or `development/mx_cache`.

The equivalent standard-library command is:

```bash
uv run python -B -m unittest discover -s tests -t .
```

Keep `-t .` when using discovery: it ensures test modules and shared fixtures
use the same fully qualified `tests.*` imports. The runner sets this automatically
and exits unsuccessfully when tests fail.

## Layout

Feature packages mirror the demo folders: `single_replica/`, `modelexpress/`,
`disaggregated/`, `snapshot/`, `request_continuity/`, `routing/`, `kvcr/`, `shadow/`
and `metrics/`. `common/` covers shared presenter behavior. `platform/` covers
cluster and upgrade guards, while `take_home/` covers attendee bundles.

Development-only cache and campaign tools have their own tests under
`development/mx_cache/` and `development/disaggregated/`. Test filenames describe
the behavior being checked rather than an implementation iteration or review
pass.

`support.py` defines the repository root and enables imports of the legacy
qualification tools in `scripts/` once. Test modules import `ROOT` from that
module and use qualified imports for other test helpers.

These are offline regression tests with mocked cluster operations. A few
streaming tests bind temporary localhost ports. Existing checks of archived
qualification evidence still run when their ignored `results/` inputs are
available and skip when those inputs are absent; they do not rerun a live
qualification or change the archived evidence.
