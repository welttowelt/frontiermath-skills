#!/usr/bin/env python3
"""Repair two mis-bound derived fields in an ID5 orbit-anneal result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


LENGTH = 333
HALF = 166


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def paf(sequence: list[int]) -> list[int]:
    return [
        sum(
            sequence[index] * sequence[(index + shift) % LENGTH]
            for index in range(LENGTH)
        )
        for shift in range(LENGTH)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_result", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw = json.loads(args.raw_result.read_text())
    if (
        raw.get("schema")
        != "frontiermath-lp333-id5-orbit-anneal-result-v1"
    ):
        raise ValueError("unexpected raw result schema")
    a = raw.get("a_sequence")
    b = raw.get("b_sequence")
    if not (
        isinstance(a, list)
        and isinstance(b, list)
        and len(a) == LENGTH
        and len(b) == LENGTH
        and set(a) <= {-1, 1}
        and set(b) <= {-1, 1}
    ):
        raise ValueError("raw result lacks two binary length-333 rows")
    a_paf = paf(a)
    b_paf = paf(b)
    residual = [
        a_paf[shift] + b_paf[shift] + 2
        for shift in range(1, HALF + 1)
    ]
    objective = sum(value * value for value in residual)
    l1 = sum(map(abs, residual))
    maximum = max(map(abs, residual))
    checks = {
        "stored_a_paf": (
            raw.get("a_paf_independent") == a_paf[1 : HALF + 1]
        ),
        "stored_b_paf": (
            raw.get("b_paf_independent") == b_paf[1 : HALF + 1]
        ),
        "stored_residual": (
            raw.get("combined_residual_independent") == residual
        ),
        "stored_objective": raw.get("best_objective") == objective,
        "status": (
            raw.get("status")
            == ("candidate" if objective == 0 else "nonterminal")
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"raw mathematical payload failed: {checks}")
    normalized = dict(raw)
    raw_l1 = normalized["best_l1_residual"]
    raw_maximum = normalized["best_max_abs_residual"]
    normalized["best_l1_residual"] = l1
    normalized["best_max_abs_residual"] = maximum
    normalized["serialization_normalization"] = {
        "schema": "frontiermath-derived-field-normalization-v1",
        "raw_result": str(args.raw_result),
        "raw_result_sha256": sha256_file(args.raw_result),
        "mathematical_payload_checks": checks,
        "corrected_fields": {
            "best_l1_residual": {"raw": raw_l1, "recomputed": l1},
            "best_max_abs_residual": {
                "raw": raw_maximum,
                "recomputed": maximum,
            },
        },
        "unchanged_fields": sorted(
            key
            for key in raw
            if key
            not in {"best_l1_residual", "best_max_abs_residual"}
        ),
        "normalizer_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.write_text(
        json.dumps(normalized, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "status": "normalized",
                "raw_result_sha256": sha256_file(args.raw_result),
                "output": str(args.output),
                "output_sha256": sha256_file(args.output),
                "objective": objective,
                "l1_residual": l1,
                "maximum_absolute_residual": maximum,
                "corrected_fields": normalized[
                    "serialization_normalization"
                ]["corrected_fields"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
