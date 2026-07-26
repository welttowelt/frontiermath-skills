#!/usr/bin/env python3
"""Audit the independent ID3 full-profile arithmetic kernel.

The kernel is artifact-independent.  This harness separately loads the pinned
LP(333) arithmetic and cross-checks 1,000 deterministic random invariant
assignments at every shift-orbit representative.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from id3_full_profile_arithmetic import (
    LENGTH,
    MOD9,
    MULTIPLIER_GENERATOR,
    TARGET_COMBINED_PAF,
    compress_residue_classes,
    crt_grid_orbits,
    crt_pair_to_index,
    cyclic_subgroup,
    multiplication_orbits,
    orbit_signature,
    orbit_values_from_sequence,
    orbit_values_to_sequence,
    periodic_autocorrelations_bitset,
    periodic_autocorrelations_naive,
    prescribed_q2_pair,
    sequence_to_sign_table,
    sign_table_to_sequence,
    validate_crt_grid_against_orbits,
    validate_orbit_partition,
)


FAMILY_ID = 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sign_matrix(record: dict[str, Any], name: str) -> list[list[int]]:
    compressed = list(record[f"{name}_tilde"])
    binary = record[f"{name}_margin_9_by_12"]
    if len(compressed) != MOD9 or len(binary) != MOD9:
        raise ValueError(f"profile {name} data does not have nine rows")
    result: list[list[int]] = []
    for row, entries in enumerate(binary):
        if len(entries) != 12 or any(entry not in (0, 1) for entry in entries):
            raise ValueError(f"profile {name} margin row {row} is not binary")
        singleton = 1 if compressed[row] % 3 == 1 else -1
        result.append(
            [singleton] + [1 if entry == 1 else -1 for entry in entries]
        )
    return result


def load_artifact_modules(source_repo: Path):
    code_dir = source_repo.resolve() / "lp333" / "code"
    if not code_dir.is_dir():
        raise ValueError(f"missing pinned arithmetic directory: {code_dir}")
    sys.path.insert(0, str(code_dir))
    core = importlib.import_module("core")
    search_common = importlib.import_module("search_common")
    return core, search_common, code_dir


def sparse_artifact_paf(spec: dict[str, Any]):
    sparse = []
    for matrix in spec["W"]:
        entries = []
        for left in range(spec["r"]):
            for right in range(left + 1, spec["r"]):
                coefficient = matrix[left][right]
                if coefficient:
                    entries.append((left, right, coefficient))
        sparse.append(entries)
    return sparse


def artifact_paf(
    spec: dict[str, Any],
    sparse: list[list[tuple[int, int, int]]],
    orbit_values: list[int],
    representative_index: int,
) -> int:
    return spec["const"][representative_index] + sum(
        coefficient * orbit_values[left] * orbit_values[right]
        for left, right, coefficient in sparse[representative_index]
    )


def profile_arithmetic(
    ledger: dict[str, Any],
    profile_id: int,
    independent_orbits: list[list[int]],
) -> dict[str, Any]:
    record = next(
        (item for item in ledger["records"] if item["id"] == profile_id),
        None,
    )
    if record is None or record.get("feasible") is not True:
        raise ValueError("selected profile has no feasible margin witness")

    prescribed_a, prescribed_b = prescribed_q2_pair()
    table_a = sign_matrix(record, "a")
    table_b = sign_matrix(record, "b")
    sequence_a = sign_table_to_sequence(table_a)
    sequence_b = sign_table_to_sequence(table_b)

    # The round trip checks both CRT directions and table invariance.
    table_round_trip = (
        sequence_to_sign_table(sequence_a) == table_a
        and sequence_to_sign_table(sequence_b) == table_b
    )
    orbit_values_from_sequence(independent_orbits, sequence_a)
    orbit_values_from_sequence(independent_orbits, sequence_b)

    compression9_a = compress_residue_classes(sequence_a, 9)
    compression9_b = compress_residue_classes(sequence_b, 9)
    compression37_a = compress_residue_classes(sequence_a, 37)
    compression37_b = compress_residue_classes(sequence_b, 37)

    bitset_a = periodic_autocorrelations_bitset(sequence_a)
    bitset_b = periodic_autocorrelations_bitset(sequence_b)
    naive_a = periodic_autocorrelations_naive(sequence_a)
    naive_b = periodic_autocorrelations_naive(sequence_b)
    if bitset_a != naive_a or bitset_b != naive_b:
        raise ValueError("naive and bitset PAF implementations disagree")
    combined = [
        first + second for first, second in zip(bitset_a, bitset_b)
    ]
    violating = [
        {"shift": shift, "combined_paf": combined[shift]}
        for shift in range(1, LENGTH)
        if combined[shift] != TARGET_COMBINED_PAF
    ]

    structural_checks = {
        "table_round_trip": table_round_trip,
        "a_compression9_matches": compression9_a == record["a_tilde"],
        "b_compression9_matches": compression9_b == record["b_tilde"],
        "a_compression37_matches": compression37_a == prescribed_a,
        "b_compression37_matches": compression37_b == prescribed_b,
        "a_row_sum_is_one": sum(sequence_a) == 1,
        "b_row_sum_is_one": sum(sequence_b) == 1,
        "naive_bitset_paf_agree": True,
    }
    if not all(structural_checks.values()):
        raise ValueError(f"profile structural check failed: {structural_checks}")

    histogram = Counter(combined[1:])
    return {
        "profile_id": profile_id,
        "square_counts": record["square_counts"],
        "structural_checks": structural_checks,
        "compression9": {
            "a": compression9_a,
            "b": compression9_b,
        },
        "compression37": {
            "a": compression37_a,
            "b": compression37_b,
        },
        "full_paf": {
            "target": TARGET_COMBINED_PAF,
            "matching_nonzero_shifts": LENGTH - 1 - len(violating),
            "violating_nonzero_shifts": len(violating),
            "minimum": min(combined[1:]),
            "maximum": max(combined[1:]),
            "histogram": {
                str(value): count for value, count in sorted(histogram.items())
            },
            "first_violations": violating[:12],
            "is_legendre_pair": not violating,
        },
    }


def random_crosscheck(
    trials: int,
    seed: int,
    independent_orbits: list[list[int]],
    artifact_spec: dict[str, Any],
) -> dict[str, Any]:
    independent_lookup = {
        frozenset(orbit): index
        for index, orbit in enumerate(independent_orbits)
    }
    try:
        artifact_to_independent = [
            independent_lookup[frozenset(orbit)]
            for orbit in artifact_spec["orbits"]
        ]
    except KeyError as error:
        raise ValueError("artifact and independent orbit partitions differ") from error

    sparse = sparse_artifact_paf(artifact_spec)
    rng = random.Random(seed)
    mismatches: list[dict[str, Any]] = []
    representative_comparisons = 0
    shift_invariance_checks = 0
    sequence_mapping_checks = 0
    naive_bitset_trials = 0

    for trial in range(trials):
        values = [
            -1 if rng.getrandbits(1) else 1
            for _ in independent_orbits
        ]
        sequence = orbit_values_to_sequence(independent_orbits, values)
        table = sequence_to_sign_table(sequence)
        if sign_table_to_sequence(table) != sequence:
            mismatches.append(
                {"trial": trial, "kind": "CRT table sequence round trip"}
            )

        direct_paf = periodic_autocorrelations_bitset(sequence)
        if trial < 10:
            naive_bitset_trials += 1
            if periodic_autocorrelations_naive(sequence) != direct_paf:
                mismatches.append(
                    {"trial": trial, "kind": "naive versus bitset PAF"}
                )

        for orbit in independent_orbits:
            observed = {direct_paf[shift] for shift in orbit}
            shift_invariance_checks += max(0, len(orbit) - 1)
            if len(observed) != 1:
                mismatches.append(
                    {
                        "trial": trial,
                        "kind": "PAF not constant on multiplier shift orbit",
                        "orbit": orbit,
                    }
                )

        artifact_values = [
            values[independent_index]
            for independent_index in artifact_to_independent
        ]
        for position in range(LENGTH):
            sequence_mapping_checks += 1
            if (
                artifact_values[artifact_spec["idx"][position]]
                != sequence[position]
            ):
                mismatches.append(
                    {
                        "trial": trial,
                        "kind": "artifact index map",
                        "position": position,
                    }
                )
                break

        for representative_index, shift in enumerate(artifact_spec["reps"]):
            expected = artifact_paf(
                artifact_spec,
                sparse,
                artifact_values,
                representative_index,
            )
            actual = direct_paf[shift]
            representative_comparisons += 1
            if expected != actual:
                mismatches.append(
                    {
                        "trial": trial,
                        "kind": "artifact PAF",
                        "shift": shift,
                        "expected": expected,
                        "actual": actual,
                    }
                )
        if len(mismatches) > 20:
            break

    return {
        "requested_trials": trials,
        "completed_trials": trials if not mismatches else trial + 1,
        "seed": seed,
        "representative_comparisons": representative_comparisons,
        "shift_invariance_checks": shift_invariance_checks,
        "sequence_mapping_checks": sequence_mapping_checks,
        "naive_bitset_trials": naive_bitset_trials,
        "mismatch_count": len(mismatches),
        "first_mismatches": mismatches[:20],
        "status": "pass" if not mismatches else "fail",
    }


def corrupted_orbit_control(
    independent_orbits: list[list[int]], subgroup: tuple[int, ...]
) -> dict[str, Any]:
    corrupted = [list(orbit) for orbit in independent_orbits]
    candidates = [
        index for index, orbit in enumerate(corrupted) if len(orbit) == 3
    ]
    first, second = candidates[:2]
    corrupted[first][0], corrupted[second][0] = (
        corrupted[second][0],
        corrupted[first][0],
    )
    try:
        validate_orbit_partition(corrupted, subgroup, LENGTH)
    except ValueError as error:
        return {
            "rejected": True,
            "error": str(error),
            "mutation": "swapped one residue between two size-three orbits",
        }
    return {
        "rejected": False,
        "error": None,
        "mutation": "swapped one residue between two size-three orbits",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_ledger", type=Path)
    parser.add_argument("--profile-id", type=int, default=73)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()
    if args.trials < 1:
        raise ValueError("trials must be positive")

    ledger = json.loads(args.profile_ledger.read_text(encoding="utf-8"))
    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    independent_orbits = multiplication_orbits(subgroup, LENGTH)
    validate_crt_grid_against_orbits(independent_orbits)
    grid_orbits = crt_grid_orbits()
    crt_round_trips = sum(
        crt_pair_to_index(row, residue) % 9 == row
        and crt_pair_to_index(row, residue) % 37 == residue
        for row in range(9)
        for residue in range(37)
    )

    core, search_common, code_dir = load_artifact_modules(args.source_repo)
    artifact_subgroup, artifact_record = search_common.subgroup_by_id(FAMILY_ID)
    artifact_spec = search_common.build_spec(artifact_subgroup)
    if set(artifact_subgroup) != set(subgroup):
        raise ValueError("pinned artifact selected a different ID3 subgroup")

    profile = profile_arithmetic(ledger, args.profile_id, independent_orbits)
    crosscheck = random_crosscheck(
        args.trials,
        args.seed,
        independent_orbits,
        artifact_spec,
    )
    corrupted = corrupted_orbit_control(independent_orbits, subgroup)
    gate_checks = {
        "subgroup_is_order_three": len(subgroup) == 3,
        "orbit_signature_is_9_singletons_108_triples": (
            orbit_signature(independent_orbits) == {1: 9, 3: 108}
        ),
        "crt_grid_has_117_cells": len(grid_orbits) == 117,
        "all_333_crt_pairs_round_trip": crt_round_trips == LENGTH,
        "profile_structural_checks_pass": all(
            profile["structural_checks"].values()
        ),
        "random_crosscheck_passes": crosscheck["status"] == "pass",
        "corrupted_orbit_map_rejected": corrupted["rejected"] is True,
    }
    status = "pass" if all(gate_checks.values()) else "fail"

    source_repo = args.source_repo.resolve()
    try:
        source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=source_repo,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        source_commit = None

    output = {
        "schema": "frontiermath-hadamard-id3-full-profile-arithmetic-audit-v1",
        "status": status,
        "scope": (
            "independent ID3 orbit/CRT/compression/full-PAF arithmetic plus "
            "a separately loaded pinned-artifact cross-check"
        ),
        "claim_boundary": (
            "passing this audit validates the arithmetic kernel; the stored "
            "profile-73 margin witness is not asserted to be an LP(333)"
        ),
        "gate_checks": gate_checks,
        "independent_reconstruction": {
            "subgroup": list(subgroup),
            "orbit_count": len(independent_orbits),
            "orbit_signature": {
                str(size): count
                for size, count in orbit_signature(independent_orbits).items()
            },
            "crt_grid_cells": len(grid_orbits),
            "crt_round_trips": crt_round_trips,
        },
        "profile": profile,
        "random_crosscheck": crosscheck,
        "corrupted_orbit_control": corrupted,
        "inputs": {
            "profile_ledger": str(args.profile_ledger),
            "profile_ledger_sha256": sha256_file(args.profile_ledger),
            "profile_id": args.profile_id,
        },
        "source": {
            "artifact_repository": str(source_repo),
            "artifact_commit": source_commit,
            "artifact_family_record": artifact_record,
            "artifact_core_sha256": sha256_file(code_dir / "core.py"),
            "artifact_search_common_sha256": sha256_file(
                code_dir / "search_common.py"
            ),
            "kernel_sha256": sha256_file(
                Path(__file__).with_name("id3_full_profile_arithmetic.py")
            ),
            "auditor_sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

