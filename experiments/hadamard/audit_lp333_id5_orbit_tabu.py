#!/usr/bin/env python3
"""Independently audit an LP333 ID5 full-neighborhood tabu endpoint."""

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
    "349ca6470670dc9607ff9a6d8c0d309a19524002de2cb1db94344aaa9afe6fcd"
)
EXPECTED_BASELINE_SHA256 = (
    "7a3bf72d06023658850d9e95ebc4d4eb0b3ba885da6d748a78abd5c297df486d"
)
EXPECTED_BINARY_SHA256 = (
    "a34ba7551eb64815c63fb0d2c1858d728bdd82d3c2270c00c90a766c01d40161"
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


def pair_measurements(document: dict[str, Any]) -> dict[str, Any]:
    a = document.get("a_sequence")
    b = document.get("b_sequence")
    domains = (
        isinstance(a, list)
        and isinstance(b, list)
        and len(a) == LENGTH
        and len(b) == LENGTH
        and set(a) <= {-1, 1}
        and set(b) <= {-1, 1}
    )
    if not domains:
        raise ValueError("document lacks two binary length-333 rows")
    a_paf = paf(a)
    b_paf = paf(b)
    residual = [
        a_paf[shift] + b_paf[shift] + 2
        for shift in range(1, HALF + 1)
    ]
    return {
        "domains": domains,
        "a": a,
        "b": b,
        "a_paf": a_paf,
        "b_paf": b_paf,
        "residual": residual,
        "objective": sum(value * value for value in residual),
        "l1": sum(abs(value) for value in residual),
        "maximum": max(map(abs, residual)),
        "a_profile": invariance_profile(a),
        "b_profile": invariance_profile(b),
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
    parser.add_argument("--mechanism", required=True, type=Path)
    parser.add_argument("--start", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument(
        "--preregistration-audit", required=True, type=Path
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    result = json.loads(args.result.read_text())
    mechanism = json.loads(args.mechanism.read_text())
    start = json.loads(args.start.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    measured = pair_measurements(result)
    start_measured = pair_measurements(start)
    candidate = measured["objective"] == 0
    mutation = mutation_control(measured["a"], measured["a_paf"])

    profiles = (measured["a_profile"], measured["b_profile"])
    checks = {
        "result_schema": (
            result.get("schema")
            == "frontiermath-lp333-id5-orbit-tabu-result-v1"
        ),
        "family_and_subgroup": (
            result.get("family_id") == 5
            and result.get("subgroup") == list(SUBGROUP)
        ),
        "binary_length_333_rows": measured["domains"],
        "row_sums_one": all(
            profile["row_sum"] == 1 for profile in profiles
        ),
        "id5_invariance": all(
            profile["invariant"] for profile in profiles
        ),
        "forced_orbit_margins": all(
            profile["negative_singletons"] == 1
            and profile["negative_triples"] == 55
            for profile in profiles
        ),
        "stored_a_paf": (
            result.get("a_paf_independent")
            == measured["a_paf"][1 : HALF + 1]
        ),
        "stored_b_paf": (
            result.get("b_paf_independent")
            == measured["b_paf"][1 : HALF + 1]
        ),
        "stored_residual": (
            result.get("combined_residual_independent")
            == measured["residual"]
        ),
        "stored_objective": (
            result.get("best_objective") == measured["objective"]
        ),
        "stored_l1": (
            result.get("best_l1_residual") == measured["l1"]
        ),
        "stored_maximum": (
            result.get("best_max_abs_residual")
            == measured["maximum"]
        ),
        "status_matches_candidate": (
            result.get("status")
            == ("candidate" if candidate else "nonterminal")
        ),
        "full_paf_symmetry": all(
            measured["a_paf"][shift]
            == measured["a_paf"][LENGTH - shift]
            and measured["b_paf"][shift]
            == measured["b_paf"][LENGTH - shift]
            for shift in range(1, LENGTH)
        ),
        "start_state_is_id5": (
            start_measured["a_profile"]["invariant"]
            and start_measured["b_profile"]["invariant"]
            and start_measured["a_profile"]["row_sum"] == 1
            and start_measured["b_profile"]["row_sum"] == 1
        ),
        "start_objective_reconstructed": (
            mechanism.get("start_objective")
            == start_measured["objective"]
        ),
        "best_not_worse_than_start": (
            measured["objective"] <= start_measured["objective"]
        ),
        "mechanism_schema": (
            mechanism.get("schema")
            == "frontiermath-lp333-id5-full-neighborhood-tabu-v1"
        ),
        "full_neighborhood_mechanism": (
            mechanism.get("legal_neighbors_per_state") == 6054
            and mechanism.get("full_neighborhood_sweeps")
            == mechanism.get("applied_moves")
            and mechanism.get("tabu_tenure_min") == 7
            and mechanism.get("tabu_tenure_max") == 14
            and mechanism.get("stagnation_restart_sweeps") == 5000
            and mechanism.get("perturbation_moves") == 64
            and mechanism.get("full_neighborhood_self_test") == "PASS"
        ),
        "source_pin": (
            sha256_file(args.source) == EXPECTED_SOURCE_SHA256
        ),
        "baseline_pin": (
            sha256_file(args.baseline) == EXPECTED_BASELINE_SHA256
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
        "schema": "frontiermath-lp333-id5-orbit-tabu-audit-v1",
        "status": status,
        "family_id": 5,
        "candidate": candidate,
        "objective": measured["objective"],
        "l1_residual": measured["l1"],
        "maximum_absolute_residual": measured["maximum"],
        "start_objective": start_measured["objective"],
        "a_profile": measured["a_profile"],
        "b_profile": measured["b_profile"],
        "mutation_control": mutation,
        "checks": checks,
        "inputs": {
            "result": str(args.result),
            "result_sha256": sha256_file(args.result),
            "mechanism": str(args.mechanism),
            "mechanism_sha256": sha256_file(args.mechanism),
            "start": str(args.start),
            "start_sha256": sha256_file(args.start),
            "source": str(args.source),
            "source_sha256": sha256_file(args.source),
            "baseline": str(args.baseline),
            "baseline_sha256": sha256_file(args.baseline),
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
