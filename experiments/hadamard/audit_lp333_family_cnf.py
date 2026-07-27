#!/usr/bin/env python3
"""Independent arithmetic and serialization audit for an LP333 family CNF."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from py39_compat import int_bit_count, strict_zip

LENGTH = 333
TARGET_PAF = -2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_encoder(source_repo: Path):
    proof_dir = source_repo.resolve() / "lp333" / "proof_phase2"
    encoder_path = proof_dir / "lp333_cnf.py"
    sys.path.insert(0, str(proof_dir))
    return importlib.import_module("lp333_cnf"), encoder_path


def multiplication_orbits(
    group: tuple[int, ...], modulus: int
) -> list[list[int]]:
    unseen = set(range(modulus))
    result = []
    while unseen:
        start = min(unseen)
        orbit = sorted({start * element % modulus for element in group})
        unseen.difference_update(orbit)
        result.append(orbit)
    return sorted(result, key=lambda orbit: (len(orbit), orbit[0]))


def validate_orbits(
    orbits: list[list[int]], group: tuple[int, ...]
) -> None:
    flattened = [position for orbit in orbits for position in orbit]
    if sorted(flattened) != list(range(LENGTH)):
        raise ValueError("orbits do not partition Z_333")
    for orbit in orbits:
        expected = {
            orbit[0] * element % LENGTH for element in group
        }
        if set(orbit) != expected:
            raise ValueError("stored orbit is not a subgroup orbit")


def orbit_signature(orbits: list[list[int]]) -> list[list[int]]:
    counts = Counter(map(len, orbits))
    return [[size, counts[size]] for size in sorted(counts)]


def sequence_from_orbits(
    orbits: list[list[int]], values: list[int]
) -> list[int]:
    if len(orbits) != len(values):
        raise ValueError("orbit values have the wrong length")
    sequence = [0] * LENGTH
    for orbit, value in strict_zip(orbits, values):
        if value not in (-1, 1):
            raise ValueError("orbit value is not a sign")
        for position in orbit:
            sequence[position] = value
    if any(value == 0 for value in sequence):
        raise ValueError("orbit map omitted a coordinate")
    return sequence


def paf_bitset(sequence: list[int]) -> list[int]:
    negative = sum(
        1 << position
        for position, value in enumerate(sequence)
        if value == -1
    )
    mask = (1 << LENGTH) - 1
    result = []
    for shift in range(LENGTH):
        if shift:
            rotated = (
                (negative >> shift)
                | (negative << (LENGTH - shift))
            ) & mask
        else:
            rotated = negative
        mismatches = int_bit_count(negative ^ rotated)
        result.append(LENGTH - 2 * mismatches)
    return result


def direct_legendre_value(first: list[int], second: list[int]) -> bool:
    if sum(first) not in (-1, 1) or sum(second) not in (-1, 1):
        return False
    first_paf = paf_bitset(first)
    second_paf = paf_bitset(second)
    return all(
        first_paf[shift] + second_paf[shift] == TARGET_PAF
        for shift in range(1, LENGTH)
    )


def inspect_dimacs(path: Path) -> dict[str, int]:
    variables = None
    declared_clauses = None
    clauses = 0
    maximum_variable = 0
    maximum_clause_length = 0
    empty_clauses = 0
    with path.open("r", encoding="ascii") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("c"):
                continue
            if stripped.startswith("p "):
                fields = stripped.split()
                if len(fields) != 4 or fields[1] != "cnf":
                    raise ValueError("invalid DIMACS header")
                variables = int(fields[2])
                declared_clauses = int(fields[3])
                continue
            literals = [int(token) for token in stripped.split()]
            if not literals or literals[-1] != 0:
                raise ValueError("unterminated DIMACS clause")
            clause = literals[:-1]
            clauses += 1
            maximum_clause_length = max(
                maximum_clause_length, len(clause)
            )
            empty_clauses += int(not clause)
            for literal in clause:
                maximum_variable = max(maximum_variable, abs(literal))
    if variables is None or declared_clauses is None:
        raise ValueError("DIMACS header missing")
    return {
        "declared_variables": variables,
        "declared_clauses": declared_clauses,
        "parsed_clauses": clauses,
        "maximum_variable": maximum_variable,
        "maximum_clause_length": maximum_clause_length,
        "empty_clauses": empty_clauses,
    }


def random_arithmetic_audit(
    encoder,
    model,
    orbits: list[list[int]],
    samples: int,
    seed: int,
    cnf_samples: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    paf_checks = 0
    sequence_checks = 0
    row_sum_checks = 0
    semantic_checks = 0
    cnf_checks = 0
    semantic_true = 0
    for sample in range(samples):
        za = [rng.randrange(2) for _ in orbits]
        zb = [rng.randrange(2) for _ in orbits]
        values_a = [1 - 2 * value for value in za]
        values_b = [1 - 2 * value for value in zb]
        first = sequence_from_orbits(orbits, values_a)
        second = sequence_from_orbits(orbits, values_b)
        first_paf = paf_bitset(first)
        second_paf = paf_bitset(second)
        sequence_checks += 2 * LENGTH

        for equation, shift in enumerate(model.spec["reps"]):
            encoded_a = encoder.paf_from_spec(
                model.spec, values_a, equation
            )
            encoded_b = encoder.paf_from_spec(
                model.spec, values_b, equation
            )
            if encoded_a != first_paf[shift]:
                raise AssertionError("A orbit PAF disagrees with direct PAF")
            if encoded_b != second_paf[shift]:
                raise AssertionError("B orbit PAF disagrees with direct PAF")
            paf_checks += 2

        weighted_a = sum(
            len(orbit) * value
            for orbit, value in strict_zip(orbits, values_a)
        )
        weighted_b = sum(
            len(orbit) * value
            for orbit, value in strict_zip(orbits, values_b)
        )
        if weighted_a != sum(first) or weighted_b != sum(second):
            raise AssertionError("weighted orbit row sum disagrees")
        row_sum_checks += 2

        direct = direct_legendre_value(first, second)
        semantic = model.semantic_value(za, zb)
        if direct != semantic:
            raise AssertionError("direct and model semantics disagree")
        semantic_true += int(semantic)
        semantic_checks += 1

        if sample < cnf_samples:
            cnf_value, extension = model.canonical_cnf_value(za, zb)
            model.audit_extension(za, zb, extension)
            if semantic != cnf_value:
                raise AssertionError("semantic and canonical CNF disagree")
            cnf_checks += 1
    return {
        "samples": samples,
        "seed": seed,
        "direct_paf_checks": paf_checks,
        "sequence_coordinate_checks": sequence_checks,
        "row_sum_checks": row_sum_checks,
        "semantic_checks": semantic_checks,
        "canonical_cnf_checks": cnf_checks,
        "semantic_true": semantic_true,
        "result": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--random-samples", type=int, default=1000)
    parser.add_argument("--cnf-samples", type=int, default=20)
    args = parser.parse_args()
    if args.random_samples <= 0 or not 0 < args.cnf_samples <= args.random_samples:
        raise ValueError("invalid sample counts")

    metadata = json.loads(
        args.encoding_metadata.read_text(encoding="utf-8")
    )
    cnf_path = Path(metadata["cnf"]["path"])
    encoder, encoder_path = load_encoder(args.source_repo)
    group = tuple(metadata["subgroup"]["elements"])
    stored_orbits = [list(orbit) for orbit in metadata["subgroup"]["orbits"]]
    validate_orbits(stored_orbits, group)
    independent_orbits = multiplication_orbits(group, LENGTH)
    model, source_record = encoder.build_lp333_model(metadata["family_id"])

    random_audit = random_arithmetic_audit(
        encoder,
        model,
        stored_orbits,
        args.random_samples,
        20260726 + metadata["family_id"],
        args.cnf_samples,
    )
    rebuilt_hash = encoder.dimacs_sha256(
        model.builder, split_unit_clauses=True
    )
    dimacs = inspect_dimacs(cnf_path)
    transformation = encoder.transformation_truth_table_audit()
    small_model = encoder.build_singleton_model(7)
    small_exhaustive = encoder.exhaustive_small_audit(small_model)
    small_a, small_b = encoder.find_small_legendre_pair(7)
    small_za = [0 if value == 1 else 1 for value in small_a]
    small_zb = [0 if value == 1 else 1 for value in small_b]
    small_cnf, small_extension = small_model.canonical_cnf_value(
        small_za, small_zb
    )
    small_model.audit_extension(small_za, small_zb, small_extension)

    corrupted = [list(orbit) for orbit in stored_orbits]
    first, second = next(
        (left, right)
        for left in range(len(corrupted))
        for right in range(left + 1, len(corrupted))
        if len(corrupted[left]) == len(corrupted[right]) > 1
    )
    corrupted[first][0], corrupted[second][0] = (
        corrupted[second][0],
        corrupted[first][0],
    )
    corruption_rejected = False
    try:
        validate_orbits(corrupted, group)
    except ValueError:
        corruption_rejected = True

    checks = {
        "metadata_generated": metadata.get("status") == "generated",
        "cnf_hash": sha256_file(cnf_path) == metadata["cnf"]["sha256"],
        "encoder_hash": (
            sha256_file(encoder_path)
            == metadata["inputs"]["proof_encoder_sha256"]
        ),
        "source_family": source_record["id"] == metadata["family_id"],
        "subgroup_elements": source_record["elements"] == list(group),
        "independent_orbit_partition": (
            {tuple(orbit) for orbit in independent_orbits}
            == {tuple(orbit) for orbit in stored_orbits}
        ),
        "orbit_signature": (
            orbit_signature(independent_orbits)
            == metadata["subgroup"]["orbit_signature"]
        ),
        "shift_representatives": (
            model.spec["reps"]
            == metadata["subgroup"]["shift_representatives"]
        ),
        "random_direct_arithmetic": random_audit["result"] == "PASS",
        "deterministic_cnf_rebuild": rebuilt_hash == metadata["cnf"]["sha256"],
        "dimacs_variables": (
            dimacs["declared_variables"] == metadata["cnf"]["variables"]
        ),
        "dimacs_clauses": (
            dimacs["declared_clauses"] == metadata["cnf"]["clauses"]
            and dimacs["parsed_clauses"] == dimacs["declared_clauses"]
        ),
        "dimacs_variable_range": (
            dimacs["maximum_variable"] <= dimacs["declared_variables"]
        ),
        "dimacs_no_empty_clause": dimacs["empty_clauses"] == 0,
        "transformation_truth_tables": transformation["result"] == "PASS",
        "small_exhaustive": small_exhaustive["result"] == "PASS",
        "small_positive_fixture": (
            encoder.direct_is_legendre_pair(small_a, small_b) and small_cnf
        ),
        "corrupted_orbit_map_rejected": corruption_rejected,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-hadamard-lp333-family-cnf-audit-v1",
        "status": status,
        "family_id": metadata["family_id"],
        "checks": checks,
        "random_arithmetic_audit": random_audit,
        "dimacs": dimacs,
        "deterministic_rebuild_sha256": rebuilt_hash,
        "transformation_audit": transformation,
        "small_exhaustive_audit": small_exhaustive,
        "positive_fixture": {
            "length": 7,
            "a": small_a,
            "b": small_b,
            "direct": True,
            "canonical_cnf": small_cnf,
        },
        "adversarial_control": {
            "mutation": "swapped one coordinate across equal-sized orbits",
            "rejected": corruption_rejected,
        },
        "inputs": {
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "cnf_sha256": sha256_file(cnf_path),
            "proof_encoder_sha256": sha256_file(encoder_path),
        },
        "auditor_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": status,
                "family_id": metadata["family_id"],
                "checks": checks,
                "random_arithmetic_audit": random_audit,
                "dimacs": dimacs,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
