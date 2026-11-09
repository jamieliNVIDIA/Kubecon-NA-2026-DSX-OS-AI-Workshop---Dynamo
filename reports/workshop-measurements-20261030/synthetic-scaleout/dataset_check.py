#!/usr/bin/env python3
"""Generate one sealed profile's synthetic dataset with the pinned AIPerf, without sending a request.

Times tokenizer loading and dataset generation and summarizes the realized session shape, so CPU
qualification measures the per-cell setup cost before any GPU is reserved. `--tokenizer` replaces the
profile's tokenizer for an offline code-path check only; campaign qualification never passes it.
"""
import argparse
import json
from pathlib import Path
import resource
import statistics
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--tokenizer')
    args = parser.parse_args()

    import aiperf
    from aiperf.cli_runner import _make_benchmark_run
    from aiperf.common import random_generator as rng
    from aiperf.common.tokenizer import Tokenizer
    from aiperf.config import load_config
    from aiperf.config.dataset.resolver import DatasetResolver
    from aiperf.config.loader import build_benchmark_plan
    from aiperf.config.resolution.resolvers import ScenarioResolver, TimingResolver
    from aiperf.plugin import plugins
    from aiperf.plugin.enums import ComposerType, PluginType

    cfg = load_config(args.profile)
    build_benchmark_plan(cfg)
    run = _make_benchmark_run(cfg.benchmark, random_seed=cfg.random_seed)
    for resolver in [DatasetResolver(), ScenarioResolver(), TimingResolver()]:
        resolver.resolve(run)
    rng.init(run.random_seed)  # as the service bootstrap does before composing
    tokenizer_cfg = run.cfg.tokenizer
    name = args.tokenizer or tokenizer_cfg.get_tokenizer_name_for_model(run.cfg.get_model_names()[0])
    started = time.monotonic()
    tokenizer = Tokenizer.from_pretrained(name, trust_remote_code=tokenizer_cfg.trust_remote_code,
                                          revision=None if args.tokenizer else tokenizer_cfg.revision,
                                          resolve_alias=tokenizer_cfg.should_resolve_alias)
    loaded = time.monotonic()
    composer = plugins.get_class(PluginType.DATASET_COMPOSER, ComposerType.SYNTHETIC)(run=run, tokenizer=tokenizer)
    conversations = composer.create_dataset()
    generated = time.monotonic()
    turns = [len(c.turns) for c in conversations]
    print(json.dumps({'profile': str(args.profile), 'aiperf_module': aiperf.__file__,
                      'tokenizer': name, 'tokenizer_override': bool(args.tokenizer),
                      'tokenizer_seconds': round(loaded - started, 2), 'dataset_seconds': round(generated - loaded, 2),
                      'conversations': len(conversations), 'turns_mean': round(statistics.mean(turns), 2),
                      'turns_max': max(turns), 'max_rss_mib': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}))


if __name__ == '__main__':
    main()
