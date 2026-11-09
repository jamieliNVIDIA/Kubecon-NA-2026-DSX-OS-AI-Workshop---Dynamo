#!/usr/bin/env python3
"""Generate and scenario-validate AgentX templates without contacting a server."""

import json
from pathlib import Path

from ruamel.yaml import YAML

from aiperf.cli_runner import _make_benchmark_run
from aiperf.config.flags.cli_config import CLIConfig
from aiperf.config.flags.converter import _assemble_envelope_dict, convert_cli_to_aiperf
from aiperf.config.dataset.resolver import DatasetResolver
from aiperf.config.resolution.resolvers import ScenarioResolver, TimingResolver


def main():
    out = Path(__file__).resolve().parent
    for concurrency in (1, 4):
        cli = CLIConfig(
            model_names=["nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4"],
            urls=["http://127.0.0.1:8000"],
            endpoint_type="chat",
            streaming=True,
            scenario="inferencex-agentx-mvp",
            public_dataset="semianalysis_cc_traces_weka_062126",
            max_context_length=1048576,
            concurrency=concurrency,
            use_server_token_count=True,
            extra_inputs={"ignore_eos": True},
            cache_bust="first_turn_prefix",
            system_idle_gap_cap_seconds=10,
            trajectory_start_min_ratio=0.0,
            trajectory_start_max_ratio=1.0,
            benchmark_duration=900,
            random_seed=20261030,
            ui_type="none",
            no_gpu_telemetry=True,
            tokenizer_name="nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4",
            tokenizer_revision="8a115b9d966adce8c059a7bcf47f49a1e57957d8",
            timeout_seconds=1800,
            agentic_warmup_grace_period=1800,
            benchmark_grace_period=300,
            artifact_directory=Path(f"./artifacts/agentx-c{concurrency}"),
        )
        config = convert_cli_to_aiperf(cli)
        run = _make_benchmark_run(config.benchmark, random_seed=config.random_seed)
        for resolver in (DatasetResolver(), ScenarioResolver(), TimingResolver()):
            resolver.resolve(run)
        print(
            f"Validated C={concurrency}: "
            f"{run.resolved.scenario_outcome.model_dump(mode='json')}"
        )
        envelope = json.loads(json.dumps(_assemble_envelope_dict(cli), default=str))
        yaml = YAML()
        yaml.default_flow_style = False
        with (out / f"profile-c{concurrency}.yaml").open("w") as stream:
            yaml.dump(envelope, stream)
        (out / f"resolved-c{concurrency}.json").write_text(
            json.dumps(run.model_dump(mode="json"), indent=2) + "\n"
        )
        (out / f"cli-fields-c{concurrency}.json").write_text(
            json.dumps(cli.model_dump(mode="json", exclude_unset=True), indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
