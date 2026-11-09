# Development tools

These tools support demo development, repeated experiments and evidence
recovery. The presenter walkthroughs remain under [demos/](../../demos/README.md).

| Tool set | Purpose |
| --- | --- |
| [mx_cache/](mx_cache/README.md) | The development-only MX RAM cache used to shorten repeated weight loading, including the dec-only setup |
| [disaggregated/](disaggregated/README.md) | Standalone aggregate-versus-P/D campaigns, client handoff, inspection, analysis and recovery |

Run packaged tools from the repository root. For example:

```bash
uv run python -m scripts.development.mx_cache.workflow --help
uv run python -m scripts.development.disaggregated.benchmark --help
```

The RAM cache is optional development infrastructure, not a workshop
prerequisite or a presenter step. Its existence does not establish startup
performance or successful peer loading. Experiments retain their own frozen
inputs, source hashes, placement, resource ownership and qualification receipts.
Use fresh run directories after changing a frozen input or source.
