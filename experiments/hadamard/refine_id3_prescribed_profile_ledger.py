#!/usr/bin/env python3
"""Refine only UNKNOWN cells in an id3 prescribed-profile ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from build_id3_prescribed_profile_ledger import solve_multiset


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_ledger", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds-per-multiset", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    base = json.loads(args.base_ledger.read_text(encoding="utf-8"))
    records = base["records"]
    unknown_before = [
        record["id"] for record in records if record["status"] == "UNKNOWN"
    ]
    started = time.perf_counter()
    refined_records = []
    for record in records:
        if record["status"] != "UNKNOWN":
            refined_records.append(record)
            continue
        counts = {
            int(square): count
            for square, count in record["square_counts"].items()
        }
        refined = solve_multiset(
            record["id"],
            counts,
            args.max_seconds_per_multiset,
            args.workers,
            args.seed,
        )
        refined["prior_attempt"] = {
            "status": record["status"],
            "wall_seconds": record["wall_seconds"],
            "branches": record["branches"],
            "conflicts": record["conflicts"],
        }
        refined_records.append(refined)
        print(
            f"{record['id']:02d} {refined['status']:<10} "
            f"{refined['wall_seconds']:.3f}s",
            flush=True,
        )

    status_counts = Counter(record["status"] for record in refined_records)
    result = {
        **{
            key: value
            for key, value in base.items()
            if key
            not in {
                "status",
                "status_counts",
                "feasible_multiset_ids",
                "unknown_multiset_ids",
                "runtime_seconds",
                "generator_sha256",
                "records",
            }
        },
        "schema": "frontiermath-hadamard-id3-prescribed-profile-ledger-v1-refined",
        "status": "complete" if "UNKNOWN" not in status_counts else "bounded",
        "status_counts": dict(sorted(status_counts.items())),
        "feasible_multiset_ids": [
            record["id"]
            for record in refined_records
            if record.get("feasible") is True
        ],
        "unknown_multiset_ids": [
            record["id"]
            for record in refined_records
            if record.get("feasible") is None
        ],
        "refinement": {
            "base_ledger_sha256": sha256_file(args.base_ledger),
            "unknown_before": unknown_before,
            "max_seconds_per_multiset": args.max_seconds_per_multiset,
            "workers": args.workers,
            "seed_base": args.seed,
            "runtime_seconds": time.perf_counter() - started,
            "refiner_sha256": sha256_file(Path(__file__).resolve()),
        },
        "records": refined_records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: result[key] for key in (
        "status",
        "status_counts",
        "feasible_multiset_ids",
        "unknown_multiset_ids",
        "refinement",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
