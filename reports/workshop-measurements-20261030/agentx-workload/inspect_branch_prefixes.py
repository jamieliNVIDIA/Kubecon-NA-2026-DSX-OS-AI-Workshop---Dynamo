#!/usr/bin/env python3
"""Compare exact trace-local leading hashes using existing replay metadata.

No tokenizer, inference, corpus download, or workload changes. Timestamp/branch
mapping comes from the completed full-corpus CPU preparation receipt.
"""

import argparse
import collections
import hashlib
import itertools
import json
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def leading_equal(left, right):
    for i, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return i
    return min(len(left), len(right))


def source_request(trace, turn):
    outer = turn.get("source_outer_idx")
    if outer is None or outer < 0:
        return None, 0
    entry = trace["requests"][outer]
    inner = turn.get("source_inner_idx")
    if inner is not None:
        return entry["requests"][inner], entry.get("tool_tokens", 0) + entry.get("system_tokens", 0)
    if entry["type"] == "subagent":
        return None, 0
    return entry, trace.get("tool_tokens", 0) + trace.get("system_tokens", 0)


def request_window(turn):
    start = turn.get("timestamp_ms")
    duration = turn.get("api_time_ms")
    if start is None or duration is None:
        return None
    return (start, start + max(duration, 0))


def overlap(left, right):
    if left is None or right is None:
        return None
    return max(0, min(left[1], right[1]) - max(left[0], right[0]))


def describe(conv, turn, request, declared_prefix):
    return {
        "conversation_id": conv["conversation_id"],
        "source_kind": turn.get("source_kind"),
        "source_outer_idx": turn.get("source_outer_idx"),
        "source_inner_idx": turn.get("source_inner_idx"),
        "recorded_input_tokens": request["in"],
        "recorded_output_tokens": request["out"],
        "timestamp_ms": turn.get("timestamp_ms"),
        "api_time_ms": turn.get("api_time_ms"),
        "declared_tools_plus_system_tokens": declared_prefix,
        "subagent_type": conv.get("subagent_type"),
    }


def recorded_named_child(conv):
    suffix = conv["conversation_id"].split("::sa:", 1)
    # :fa:, :aux:, and :wg: qualify inferred streams inside a recorded
    # subagent entry; only its unqualified session is the named main chain.
    return len(suffix) == 2 and ":" not in suffix[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new immutable output path")
    receipt = json.loads(args.receipt.read_text())
    metadata = json.loads(receipt["cache_manifest"]["dataset_metadata_json"])
    convs = {c["conversation_id"]: c for c in metadata["conversations"]}
    by_trace = collections.defaultdict(list)
    for conv in convs.values():
        by_trace[conv.get("replay_scope_id") or conv["conversation_id"]].append(conv)

    stats = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(lambda: {"largest_prefix": [], "largest_prefix_with_first_request_overlap": []})
    thresholds = (1, 1024, 8192, 32768, 65536, 131072)

    def record(kind, example):
        counter = stats[kind]
        counter["comparisons"] += 1
        tokens = example["identical_leading_block_tokens"]
        for threshold in thresholds:
            if tokens >= threshold:
                counter[f"prefix_ge_{threshold}_tokens"] += 1
        if tokens > example["max_declared_tools_plus_system_tokens"]:
            counter["prefix_exceeds_declared_tools_plus_system"] += 1
        if example.get("first_requests_overlap_ms", 0) and tokens >= 32768:
            counter["prefix_ge_32768_and_first_requests_overlap"] += 1
        example["comparison_category"] = kind
        targets = [examples[kind]["largest_prefix"]]
        if (example.get("first_requests_overlap_ms") or 0) > 0:
            targets.append(examples[kind]["largest_prefix_with_first_request_overlap"])
        for target in targets:
            target.append(example)
            target.sort(key=lambda e: e["identical_leading_block_tokens"], reverse=True)
            del target[5:]

    source_hash = hashlib.sha256()
    with args.corpus.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            source_hash.update(raw)
            trace = json.loads(raw)
            bs = trace["block_size"]
            root = trace["id"]
            for parent in by_trace[root]:
                groups = collections.defaultdict(list)
                for branch in parent["branches"]:
                    spawning = [(i, t) for i, t in enumerate(parent["turns"]) if branch["branch_id"] in t["branch_ids"]]
                    if not spawning:
                        continue
                    parent_turn_idx, parent_turn = spawning[0]
                    parent_req, parent_declared = source_request(trace, parent_turn)
                    join_turns = [i for i, t in enumerate(parent["turns"]) if any(p.get("branch_id") == branch["branch_id"] for p in t["prerequisites"])]
                    for child_id in branch["child_conversation_ids"]:
                        child = convs[child_id]
                        first = next((t for t in child["turns"] if not t["no_request"]), None)
                        if first is None:
                            continue
                        child_req, child_declared = source_request(trace, first)
                        if child_req is None:
                            continue
                        item = (branch, child, first, child_req, child_declared, join_turns)
                        groups[parent_turn_idx].append(item)
                        if parent_req is not None:
                            blocks = leading_equal(parent_req.get("hash_ids", []), child_req.get("hash_ids", []))
                            example = {
                                "trace_id": root, "corpus_line": line_number,
                                "branch_id": branch["branch_id"], "branch_mode": branch["mode"],
                                "parent_turn_index": parent_turn_idx, "join_turn_indices": join_turns,
                                "identical_leading_blocks": blocks,
                                "identical_leading_block_tokens": blocks * bs,
                                "max_declared_tools_plus_system_tokens": max(parent_declared, child_declared),
                                "parent": describe(parent, parent_turn, parent_req, parent_declared),
                                "child": describe(child, first, child_req, child_declared),
                                "first_requests_overlap_ms": overlap(request_window(parent_turn), request_window(first)),
                            }
                            suffix = "recorded_named_subagent_main" if recorded_named_child(child) else "inferred_context_chain"
                            record("parent_child_" + suffix, example)
                for parent_turn_idx, children in groups.items():
                    for left, right in itertools.combinations(children, 2):
                        lb, lc, lt, lr, ld, lj = left
                        rb, rc, rt, rr, rd, rj = right
                        blocks = leading_equal(lr.get("hash_ids", []), rr.get("hash_ids", []))
                        example = {
                            "trace_id": root, "corpus_line": line_number,
                            "parent_conversation_id": parent["conversation_id"],
                            "parent_turn_index": parent_turn_idx,
                            "branch_ids": [lb["branch_id"], rb["branch_id"]],
                            "branch_modes": [lb["mode"], rb["mode"]],
                            "branch_start_timestamps_ms": [lb["start_timestamp_ms"], rb["start_timestamp_ms"]],
                            "join_turn_indices": [lj, rj],
                            "identical_leading_blocks": blocks,
                            "identical_leading_block_tokens": blocks * bs,
                            "max_declared_tools_plus_system_tokens": max(ld, rd),
                            "left": describe(lc, lt, lr, ld),
                            "right": describe(rc, rt, rr, rd),
                            "first_requests_overlap_ms": overlap(request_window(lt), request_window(rt)),
                        }
                        suffix = "both_recorded_named_subagent_mains" if recorded_named_child(lc) and recorded_named_child(rc) else "includes_inferred_context_chain"
                        record("siblings_" + suffix, example)

    output = {
        "purpose": "Structural exact-prefix and replay-scheduling evidence, not observed server cache hits or GPU performance",
        "corpus_path": str(args.corpus.resolve()), "corpus_sha256": source_hash.hexdigest(),
        "preparation_receipt": str(args.receipt.resolve()), "preparation_receipt_sha256": digest(args.receipt),
        "helper_sha256": digest(Path(__file__)), "metadata_conversations": len(convs),
        "stats": dict(stats), "examples": examples,
        "method": "Within each trace namespace, compare ordered hash_ids from the actual replay child's first request with its spawning parent turn, and with sibling first requests attached to that same parent turn. Full matching blocks times recorded block_size. No substring or semantic similarity comparison. Overlap uses recorded canonical request timestamp and api_time_ms; dispatch permits overlap but live overlap depends on response times and scheduling.",
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output["stats"], indent=2))
    for kind, records in examples.items():
        best = records["largest_prefix_with_first_request_overlap"]
        if best:
            e = best[0]
            print(kind, e["trace_id"], e["identical_leading_block_tokens"], e["first_requests_overlap_ms"])


if __name__ == "__main__":
    main()
