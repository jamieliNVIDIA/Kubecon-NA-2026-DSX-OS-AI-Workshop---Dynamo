#!/usr/bin/env python3
"""Fetch the pinned public AgentX corpus and summarize its recorded lengths."""

import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path

DATASET = "semianalysisai/cc-traces-weka-062126"
REVISION = "23f152f6f0f9399a85901b89a6458def0ef16729"
EXPECTED_BYTES = 1847151435
EXPECTED_SHA256 = "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276"
URL = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/traces.jsonl"


def summarize(path):
    digest = hashlib.sha256()
    counts = {"traces": 0, "main_requests": 0, "subagent_groups": 0, "child_requests": 0}
    inputs, outputs, contexts, peaks, trace_ids = [], [], [], [], []
    with path.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            trace = json.loads(raw)
            counts["traces"] += 1
            trace_ids.append(trace["id"])
            peak = 0
            for entry in trace["requests"]:
                if entry["type"] == "subagent":
                    counts["subagent_groups"] += 1
                    requests = entry["requests"]
                    counts["child_requests"] += len(requests)
                else:
                    requests = [entry]
                    counts["main_requests"] += 1
                for request in requests:
                    isl, osl = int(request["in"]), int(request["out"])
                    inputs.append(isl)
                    outputs.append(osl)
                    contexts.append(isl + osl)
                    peak = max(peak, isl + osl)
            peaks.append(peak)
    actual_hash = digest.hexdigest()
    assert actual_hash == EXPECTED_SHA256, actual_hash
    assert path.stat().st_size == EXPECTED_BYTES, path.stat().st_size
    return {
        "dataset": DATASET,
        "revision": REVISION,
        "source_url": URL,
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": actual_hash,
        "counts": counts,
        "max_recorded_input_tokens": max(inputs),
        "max_recorded_output_tokens": max(outputs),
        "max_recorded_input_plus_output_tokens": max(contexts),
        "total_recorded_input_tokens": sum(inputs),
        "total_recorded_output_tokens": sum(outputs),
        "eligible_full_trajectories_by_context_limit": {
            str(cap): sum(peak <= cap for peak in peaks)
            for cap in (8192, 32768, 131072, 262144, 1048576)
        },
        "trace_ids_sha256": hashlib.sha256("\n".join(trace_ids).encode()).hexdigest(),
        "note": "Recorded proxy-tokenizer lengths, before reconstruction with the served model tokenizer.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    target = args.directory / "traces.jsonl"
    if not target.exists():
        partial = args.directory / "traces.jsonl.partial"
        print(f"Fetching {EXPECTED_BYTES} bytes from pinned corpus {REVISION}", flush=True)
        started = last_report = time.monotonic()
        downloaded = partial.stat().st_size if partial.exists() else 0
        if not partial.exists():
            with urllib.request.urlopen(URL, timeout=60) as source, partial.open("xb") as output:
                while chunk := source.read(4 * 1024 * 1024):
                    output.write(chunk)
                    downloaded += len(chunk)
                    if time.monotonic() - last_report >= 15:
                        print(f"Downloaded {downloaded}/{EXPECTED_BYTES} bytes", flush=True)
                        last_report = time.monotonic()
        assert downloaded == EXPECTED_BYTES, downloaded
        digest = hashlib.sha256()
        with partial.open("rb") as stream:
            while chunk := stream.read(4 * 1024 * 1024):
                digest.update(chunk)
        actual = digest.hexdigest()
        assert actual == EXPECTED_SHA256, actual
        partial.rename(target)
        print(f"Download verified in {time.monotonic() - started:.1f}s", flush=True)
    summary = summarize(target)
    (args.directory / "corpus-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
