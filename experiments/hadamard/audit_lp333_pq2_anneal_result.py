#!/usr/bin/env python3
"""Independently audit an unrestricted LP333 pq^2-compression search result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


LENGTH = 333
HALF = 166
EXPECTED_COMPRESSIONS = ([1, 11, -11], [1, -11, 11])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def paf(sequence: list[int]) -> list[int]:
    negative = sum(
        1 << index
        for index, value in enumerate(sequence)
        if value == -1
    )
    mask = (1 << LENGTH) - 1
    result = []
    for shift in range(LENGTH):
        rotated = (
            negative
            if shift == 0
            else (
                (negative >> shift)
                | (negative << (LENGTH - shift))
            )
            & mask
        )
        result.append(LENGTH - 2 * (negative ^ rotated).bit_count())
    return result


def compression(sequence: list[int]) -> list[int]:
    return [
        sum(sequence[index] for index in range(residue, LENGTH, 3))
        for residue in range(3)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument("--preregistration-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite {args.output}")
    record = json.loads(args.result.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    first = record["a_sequence"]
    second = record["b_sequence"]
    if len(first) != LENGTH or len(second) != LENGTH:
        raise ValueError("candidate sequence length differs")
    if not all(value in (-1, 1) for value in first + second):
        raise ValueError("candidate sequence domain differs")

    first_paf = paf(first)
    second_paf = paf(second)
    residual = [
        first_paf[shift] + second_paf[shift] + 2
        for shift in range(1, LENGTH)
    ]
    independent = residual[:HALF]
    objective = sum(value * value for value in independent)
    l1 = sum(abs(value) for value in independent)
    max_abs = max(map(abs, independent))
    compressed = (compression(first), compression(second))
    negative_counts = [
        [
            sum(
                first[index] == -1
                for index in range(residue, LENGTH, 3)
            )
            for residue in range(3)
        ],
        [
            sum(
                second[index] == -1
                for index in range(residue, LENGTH, 3)
            )
            for residue in range(3)
        ],
    ]
    stored_checks = {
        "a_paf_independent": (
            record["a_paf_independent"] == first_paf[1 : HALF + 1]
        ),
        "b_paf_independent": (
            record["b_paf_independent"] == second_paf[1 : HALF + 1]
        ),
        "combined_residual_independent": (
            record["combined_residual_independent"] == independent
        ),
        "objective": record["best_objective"] == objective,
        "l1": record["best_l1_residual"] == l1,
        "max_abs": record["best_max_abs_residual"] == max_abs,
    }
    mutation = list(first)
    left = next(index for index in range(0, LENGTH, 3) if mutation[index] == 1)
    right = next(
        index for index in range(0, LENGTH, 3) if mutation[index] == -1
    )
    mutation[left] = -1
    mutation[right] = 1
    mutated_paf = paf(mutation)
    mutation_residual = [
        mutated_paf[shift] + second_paf[shift] + 2
        for shift in range(1, LENGTH)
    ]
    mutation_rejected = any(mutation_residual)

    candidate = objective == 0
    candidate_status_consistent = (
        record["status"] == ("candidate" if candidate else "nonterminal")
    )
    all_nonzero_pafs = not any(residual)
    checks = {
        "schema": (
            record["schema"]
            == "frontiermath-lp333-pq2-anneal-result-v1"
        ),
        "incremental_self_test": (
            record["incremental_self_test"] == "PASS"
            and record["incremental_self_test_trials"] == 2000
        ),
        "sequence_domains": True,
        "row_sums": sum(first) == 1 and sum(second) == 1,
        "prescribed_compressions": (
            compressed == EXPECTED_COMPRESSIONS
        ),
        "negative_counts": (
            negative_counts == [[55, 50, 61], [55, 61, 50]]
        ),
        "stored_values": all(stored_checks.values()),
        "full_paf_symmetry": (
            all(
                residual[shift - 1] == residual[LENGTH - shift - 1]
                for shift in range(1, LENGTH)
            )
        ),
        "candidate_status_consistent": candidate_status_consistent,
        "candidate_full_paf_if_claimed": (
            all_nonzero_pafs if candidate else True
        ),
        "same_residue_swap_mutation_rejected": mutation_rejected,
        "source_exists": args.source.is_file(),
        "binary_exists": args.binary.is_file(),
        "preregistration_schema": (
            preregistration.get("schema")
            == "computational-experiment-preregistration/v1"
        ),
        "preregistration_audit": (
            preregistration_audit.get("status") == "pass"
        ),
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-lp333-pq2-anneal-audit-v1",
        "status": status,
        "candidate": candidate,
        "verified_legendre_pair": candidate and all_nonzero_pafs,
        "checks": checks,
        "stored_checks": stored_checks,
        "metrics": {
            "objective": objective,
            "l1_residual": l1,
            "max_abs_residual": max_abs,
            "row_sums": [sum(first), sum(second)],
            "compressions": compressed,
            "negative_counts": negative_counts,
            "full_nonzero_paf_violations": sum(
                value != 0 for value in residual
            ),
        },
        "mutation_control": {
            "swap": [left, right],
            "same_residue_modulo_3": left % 3 == right % 3,
            "compression_preserved": (
                compression(mutation) == compression(first)
            ),
            "rejected": mutation_rejected,
        },
        "bindings": {
            "result": str(args.result),
            "result_sha256": sha256(args.result),
            "source": str(args.source),
            "source_sha256": sha256(args.source),
            "binary": str(args.binary),
            "binary_sha256": sha256(args.binary),
            "preregistration": str(args.preregistration),
            "preregistration_sha256": sha256(args.preregistration),
            "preregistration_audit": str(args.preregistration_audit),
            "preregistration_audit_sha256": sha256(
                args.preregistration_audit
            ),
        },
        "method": (
            "Recompute both complete periodic autocorrelation vectors with an "
            "independent bit-rotation implementation, rederive all prescribed "
            "compression margins and integer scores, and reject a "
            "compression-preserving one-swap mutation."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
