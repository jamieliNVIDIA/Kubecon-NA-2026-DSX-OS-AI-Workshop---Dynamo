#!/usr/bin/env python3
"""Exercise the pinned AIPerf dataset/cache pipeline without inference workers.

Version-specific CPU preparation, not a benchmark. The DatasetManager is never
initialized or started as a service; its notifications are consumed locally.
No controller, timing manager, transport, or inference worker is constructed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import resource
import shutil
import sys
import time
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def cgroup_memory() -> dict[str, str]:
    out = {}
    for name in ("memory.current", "memory.peak", "memory.max", "memory.events"):
        path = Path("/sys/fs/cgroup") / name
        if path.exists():
            out[name] = path.read_text().strip()
    return out


def process_memory() -> dict[str, int]:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS reports bytes.
    return {"process_peak_rss_bytes": int(value * (1024 if sys.platform != "darwin" else 1))}


async def prepare(args: argparse.Namespace) -> None:
    import aiperf
    from aiperf.cli_runner import _make_benchmark_run
    from aiperf.common import random_generator as rng
    from aiperf.common.control_structs import Command
    from aiperf.common.enums import CommandType
    from aiperf.common.environment import Environment
    from aiperf.config import load_config
    from aiperf.config.dataset.resolver import DatasetResolver
    from aiperf.config.resolution.resolvers import ScenarioResolver, TimingResolver
    from aiperf.dataset import mmap_cache
    from aiperf.dataset.dataset_manager import DatasetManager
    from aiperf.dataset.loader.semianalysis_cc_traces_weka import SemiAnalysisCCTracesWekaLoader

    if SemiAnalysisCCTracesWekaLoader.hf_revision != "23f152f6f0f9399a85901b89a6458def0ef16729":
        raise RuntimeError("The frozen dataset-revision patch is missing")
    if not mmap_cache.cache_enabled():
        raise RuntimeError("Enable the mmap cache for this preparation step")
    if Environment.DATASET.WEKA_PARALLEL_WORKERS != 1:
        raise RuntimeError("Set AIPERF_DATASET_WEKA_PARALLEL_WORKERS=1 before starting")

    config = load_config(args.config)
    run = _make_benchmark_run(
        config.benchmark,
        random_seed=config.random_seed,
        artifact_dir=args.receipt.parent,
    )
    for resolver in (DatasetResolver(), ScenarioResolver(), TimingResolver()):
        resolver.resolve(run)
    rng.init(run.random_seed)
    manager = DatasetManager(run=run, service_id="agentx-cpu-cache-preparation")
    if manager._compress_only:
        raise RuntimeError("Use local/subprocess client mode inside the CPU Pod; do not select AIPerf's Kubernetes service-run plugin")

    notifications = []

    async def capture_notification(message):
        notifications.append(type(message).__name__)

    manager.publish = capture_notification
    initial_hit = manager._try_cache_lookup()
    source_root = Path(aiperf.__file__).resolve().parent
    receipt = {
        "purpose": "CPU-only full-corpus dataset/mmap qualification; no inference requests",
        "status": "running",
        "profile_path": str(args.config.resolve()),
        "profile_sha256": sha256(args.config),
        "helper_sha256": sha256(Path(__file__)),
        "source_root": str(source_root),
        "source_file_sha256": {
            str(path.relative_to(source_root)): sha256(path)
            for path in (
                source_root / "dataset/dataset_manager.py",
                source_root / "dataset/loader/weka_trace.py",
                source_root / "dataset/loader/semianalysis_cc_traces_weka.py",
                source_root / "dataset/memory_map_utils.py",
                source_root / "dataset/mmap_cache.py",
            )
        },
        "python": sys.version,
        "platform": platform.platform(),
        "benchmark_id": run.benchmark_id,
        "seed": run.random_seed,
        "cache_key": manager._cache_key_for_run,
        "initial_cache_hit": initial_hit is not None,
        "cpu_count_visible": os.cpu_count(),
        "environment": {
            key: value for key, value in os.environ.items()
            if key.startswith(("AIPERF_DATASET_", "HF_", "TOKENIZERS_", "TMPDIR"))
            and not any(secret in key.upper() for secret in ("TOKEN", "SECRET", "PASSWORD"))
        },
        "cgroup_before": cgroup_memory(),
        "rss_before": process_memory(),
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)

    def write_receipt():
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")

    write_receipt()
    started = time.monotonic()
    try:
        if not args.check_cache_only:
            await manager._do_profile_configure(
                Command(cid="cpu-only-cache-preparation", cmd=CommandType.PROFILE_CONFIGURE)
            )
        final_hit = manager._try_cache_lookup()
        if final_hit is None:
            raise RuntimeError("No reusable mmap cache entry exists after preparation")
        receipt["cache_manifest"] = final_hit.manifest.model_dump(mode="json")
        receipt["cache_files"] = {
            str(path): {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (final_hit.data_path, final_hit.index_path)
        }
        receipt["cache_disk_free_bytes"] = shutil.disk_usage(final_hit.data_path.parent).free
        receipt["status"] = "cache_verified" if args.check_cache_only else "prepared"
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - started
        receipt["rss_after"] = process_memory()
        receipt["cgroup_after"] = cgroup_memory()
        receipt["notifications_consumed_locally"] = notifications
        receipt["cache_key"] = manager._cache_key_for_run
        write_receipt()
        # Remove only this disposable run's mmap copy; keep its content cache.
        await manager._cleanup()
    print(json.dumps({"status": receipt["status"], "receipt": str(args.receipt), "cache_key": receipt["cache_key"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--check-cache-only", action="store_true")
    args = parser.parse_args()
    if args.receipt.exists():
        parser.error("Use a new immutable receipt path")
    asyncio.run(prepare(args))


if __name__ == "__main__":
    main()
