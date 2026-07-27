#!/usr/bin/env python3
"""Independently audit an LP333 ID5 orbit-anneal endpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LENGTH = 333
HALF = 166
SUBGROUP = (1, 211, 232)
EXPECTED_SOURCE_SHA256 = (
    "6d90f65980de930c66aa9e091f9fa0c329c0abb5248e07a7e8f5a2ebe81caad0"
)
EXPECTED_BINARY_SHA256 = (
    "cc2ebe205655ce9decab81f7e884e95303f5b6a1f1899a30f9d3c936c40c4938"
)


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


def orbits() -> list[list[int]]:
    unseen = set(range(LENGTH))
    result = []
    while unseen:
        seed = min(unseen)
        orbit = sorted({seed * unit % LENGTH for unit in SUBGROUP})
        unseen.difference_update(orbit)
        result.append(orbit)
    return result


def invariance_profile(sequence: list[int]) -> dict[str, Any]:
    orbit_list = orbits()
    invariant = all(
        len({sequence[index] for index in orbit}) == 1
        for orbit in orbit_list
    )
    negative_singletons = sum(
        len(orbit) == 1 and sequence[orbit[0]] == -1
        for orbit in orbit_list
    )
    negative_triples = sum(
        len(orbit) == 3 and sequence[orbit[0]] == -1
        for orbit in orbit_list
    )
    return {
        "orbits": len(orbit_list),
        "orbit_size_histogram": {
            "1": sum(len(orbit) == 1 for orbit in orbit_list),
            "3": sum(len(orbit) == 3 for orbit in orbit_list),
        },
        "invariant": invariant,
        "negative_singletons": negative_singletons,
        "negative_triples": negative_triples,
        "row_sum": sum(sequence),
    }


def mutation_control(
    sequence: list[int], original_paf: list[int]
) -> dict[str, Any]:
    orbit_list = orbits()
    negative = next(
        orbit
        for orbit in orbit_list
        if len(orbit) == 3 and sequence[orbit[0]] == -1
    )
    positive = next(
        orbit
        for orbit in orbit_list
        if len(orbit) == 3 and sequence[orbit[0]] == 1
    )
    mutated = list(sequence)
    for index in negative + positive:
        mutated[index] *= -1
    mutated_paf = paf(mutated)
    profile = invariance_profile(mutated)
    return {
        "flipped_orbits": [negative, positive],
        "preserves_id5_invariance": profile["invariant"],
        "preserves_row_sum": profile["row_sum"] == 1,
        "changes_full_paf": mutated_paf != original_paf,
        "changed_shifts": sum(
            left != right
            for left, right in zip(original_paf, mutated_paf)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument("--preregistration-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    result = json.loads(args.result.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    a = result.get("a_sequence")
    b = result.get("b_sequence")
    domains = (
        isinstance(a, list)
        and isinstance(b, list)
        and len(a) == LENGTH
        and len(b) == LENGTH
        and set(a) <= {-1, 1}
        and set(b) <= {-1, 1}
    )
    if not domains:
        raise ValueError("result does not contain two binary length-333 rows")

    a_paf = paf(a)
    b_paf = paf(b)
    residual = [
        a_paf[shift] + b_paf[shift] + 2
        for shift in range(1, HALF + 1)
    ]
    objective = sum(value * value for value in residual)
    l1 = sum(abs(value) for value in residual)
    maximum = max(map(abs, residual))
    candidate = objective == 0
    a_profile = invariance_profile(a)
    b_profile = invariance_profile(b)
    mutation = mutation_control(a, a_paf)

    checks = {
        "result_schema": (
            result.get("schema")
            == "frontiermath-lp333-id5-orbit-anneal-result-v1"
        ),
        "family_and_subgroup": (
            result.get("family_id") == 5
            and result.get("subgroup") == list(SUBGROUP)
        ),
        "binary_length_333_rows": domains,
        "row_sums_one": (
            a_profile["row_sum"] == b_profile["row_sum"] == 1
        ),
        "id5_invariance": (
            a_profile["invariant"] and b_profile["invariant"]
        ),
        "forced_orbit_margins": all(
            profile["negative_singletons"] == 1
            and profile["negative_triples"] == 55
            for profile in (a_profile, b_profile)
        ),
        "stored_a_paf": (
            result.get("a_paf_independent") == a_paf[1 : HALF + 1]
        ),
        "stored_b_paf": (
            result.get("b_paf_independent") == b_paf[1 : HALF + 1]
        ),
        "stored_residual": (
            result.get("combined_residual_independent") == residual
        ),
        "stored_objective": result.get("best_objective") == objective,
        "stored_l1": result.get("best_l1_residual") == l1,
        "stored_maximum": (
            result.get("best_max_abs_residual") == maximum
        ),
        "status_matches_candidate": (
            result.get("status")
            == ("candidate" if candidate else "nonterminal")
        ),
        "full_paf_symmetry": all(
            a_paf[shift] == a_paf[LENGTH - shift]
            and b_paf[shift] == b_paf[LENGTH - shift]
            for shift in range(1, LENGTH)
        ),
        "source_pin": (
            sha256_file(args.source) == EXPECTED_SOURCE_SHA256
        ),
        "binary_pin": (
            sha256_file(args.binary) == EXPECTED_BINARY_SHA256
        ),
        "preregistration_schema": (
            preregistration.get("schema")
            == "computational-experiment-preregistration/v1"
        ),
        "preregistration_audit": (
            preregistration_audit.get("status") == "pass"
        ),
        "mutation_preserves_slice_and_changes_paf": (
            mutation["preserves_id5_invariance"]
            and mutation["preserves_row_sum"]
            and mutation["changes_full_paf"]
        ),
    }
    status = "pass" if all(checks.values()) else "fail"
    document = {
        "schema": "frontiermath-lp333-id5-orbit-anneal-audit-v1",
        "status": status,
        "family_id": 5,
        "candidate": candidate,
        "objective": objective,
        "l1_residual": l1,
        "maximum_absolute_residual": maximum,
        "a_profile": a_profile,
        "b_profile": b_profile,
        "mutation_control": mutation,
        "checks": checks,
        "inputs": {
            "result": str(args.result),
            "result_sha256": sha256_file(args.result),
            "source": str(args.source),
            "source_sha256": sha256_file(args.source),
            "binary": str(args.binary),
            "binary_sha256": sha256_file(args.binary),
            "preregistration": str(args.preregistration),
            "preregistration_sha256": sha256_file(
                args.preregistration
            ),
            "preregistration_audit": str(
                args.preregistration_audit
            ),
            "preregistration_audit_sha256": sha256_file(
                args.preregistration_audit
            ),
        },
    }
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
