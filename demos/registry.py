"""Demo identities, entry points and CLI names shared by presenters and capture."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DemoSpec:
    id: str
    module: str
    selection_key: str
    title: str

    @property
    def selector(self) -> str:
        return self.id.split('-', 1)[1].replace('shadow-engine', 'shadow').replace('agentx-metrics', 'metrics')

    @property
    def path(self) -> Path:
        return ROOT.joinpath(*self.module.split('.')).with_suffix('.py')

    @property
    def command(self) -> str:
        return 'python -m demos ' + self.selector

    @property
    def aliases(self) -> tuple[str, ...]:
        names = [self.selector, self.id, self.id.split('-', 1)[1]]
        if self.selector not in ('snapshot-dgd', 'kvcr-prepared', 'shadow-composed'):
            number = self.id.split('-', 1)[0]
            names.extend((number, str(int(number))))
        return tuple(dict.fromkeys(names))


_SPECS = (
    DemoSpec('01-single-replica', 'demos.single_replica.demo', 'workshop_demo', 'Single replica'),
    DemoSpec('02-modelexpress', 'demos.modelexpress.demo', 'workshop_modelexpress_demo', 'ModelExpress weight loading'),
    DemoSpec('03-disaggregated', 'demos.disaggregated.demo', 'workshop_disagg_demo', 'Disaggregated serving'),
    DemoSpec('04-snapshot', 'demos.snapshot.demo', 'workshop_snapshot_demo', 'Snapshot native Pod recovery'),
    DemoSpec('04-snapshot-dgd', 'demos.snapshot.dgd_demo', 'workshop_snapshot_dgd_demo', 'Snapshot DGD recovery'),
    DemoSpec('05-request-continuity', 'demos.request_continuity.demo', 'workshop_migration_demo', 'Request continuity'),
    DemoSpec('06-routing', 'demos.routing.demo', 'workshop_routing_demo', 'Recorded routing comparison'),
    DemoSpec('07-kvcr', 'demos.kvcr.demo', 'workshop_kvcr_demo', 'KVCR peer reuse'),
    DemoSpec('07-kvcr-prepared', 'demos.kvcr.prepared', 'workshop_kvcr_prepared', 'KVCR prepared workers'),
    DemoSpec('08-shadow-engine', 'demos.shadow.demo', 'workshop_shadow_demo', 'Shadow Engine'),
    DemoSpec('08-shadow-engine-composed', 'demos.shadow.composed', 'workshop_shadow_composed', 'Shadow Engine composed recovery'),
    DemoSpec('09-agentx-metrics', 'demos.metrics.demo', 'workshop_metrics_demo', 'Recorded AgentX metrics'),
)

DEMOS = MappingProxyType({spec.id: spec for spec in _SPECS})
_ALIASES = {alias: spec for spec in _SPECS for alias in spec.aliases}


def get_demo(selector: str) -> DemoSpec:
    try:
        return _ALIASES[selector]
    except KeyError:
        raise ValueError(f'Unknown demo {selector!r}. Run python -m demos list to see available demos.') from None


def by_script(script: str | Path) -> DemoSpec:
    script = Path(script).resolve()
    for spec in _SPECS:
        if spec.path == script:
            return spec
    raise ValueError(f'Unknown demo entry point: {script}')
