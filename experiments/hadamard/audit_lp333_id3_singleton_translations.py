#!/usr/bin/env python3
"""Independently audit the ID3 singleton translation canonicalization block."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from itertools import product
import json
from pathlib import Path


LENGTH = 333


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_translate(
    pattern: tuple[int, ...], offset: int
) -> tuple[int, ...]:
    return tuple(
        pattern[(index + offset) % len(pattern)] ^ pattern[offset]
        for index in range(len(pattern))
    )


def parse_clause(line: str) -> tuple[int, ...]:
    values = tuple(int(item) for item in line.split())
    if not values or values[-1] != 0:
        raise ValueError("invalid DIMACS clause")
    return values[:-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite {args.output}")
    metadata = json.loads(args.metadata.read_text())
    block = metadata["id3_singleton_translation_canonicalization"]
    control = metadata["controls"][
        "id3_normalized_translation_automorphism"
    ]
    elements = metadata["subgroup"]["elements"]
    translations = [
        translation
        for translation in range(LENGTH)
        if all(
            ((unit - 1) * translation) % LENGTH == 0
            for unit in elements
        )
    ]
    if translations != list(range(0, LENGTH, 37)):
        raise ValueError("ID3 translation annihilator changed")

    patterns = [(0,) + suffix for suffix in product((0, 1), repeat=8)]
    orbit_by_pattern = {}
    unique_orbits = set()
    for pattern in patterns:
        orbit = tuple(
            sorted(
                {
                    normalized_translate(pattern, offset)
                    for offset in range(9)
                }
            )
        )
        orbit_by_pattern[pattern] = orbit
        unique_orbits.add(orbit)
    histogram = Counter(len(orbit) for orbit in unique_orbits)
    if len(unique_orbits) != 30 or histogram != Counter(
        {1: 1, 3: 1, 9: 28}
    ):
        raise ValueError("independent singleton partition changed")
    row_feasible = [
        pattern
        for pattern in patterns
        if any(
            sum(pattern) + 3 * triple_count in (166, 167)
            for triple_count in range(109)
        )
    ]
    feasible_orbits = {orbit_by_pattern[pattern] for pattern in row_feasible}
    if (
        len(row_feasible) != 171
        or len(feasible_orbits) != 19
        or any(len(orbit) != 9 for orbit in feasible_orbits)
    ):
        raise ValueError("row-feasible singleton factor is not exactly nine")
    canonical = sorted(min(orbit) for orbit in unique_orbits)
    noncanonical = sorted(
        pattern
        for pattern in patterns
        if pattern != min(orbit_by_pattern[pattern])
    )
    if (
        [list(pattern) for pattern in canonical]
        != block["canonical_patterns"]
        or [list(pattern) for pattern in noncanonical]
        != block["noncanonical_patterns"]
    ):
        raise ValueError("metadata singleton representatives differ")

    expected_clauses = []
    for record in block["sequence_records"]:
        variables = record["singleton_variables"]
        if len(variables) != 9 or variables[0] not in (
            metadata["primary_variables"]["za"][0],
            metadata["primary_variables"]["zb"][0],
        ):
            raise ValueError("singleton primary variable binding changed")
        for pattern in noncanonical:
            expected_clauses.append(
                tuple(
                    -variable if value else variable
                    for variable, value in zip(variables[1:], pattern[1:])
                )
            )
    if len(expected_clauses) != 452:
        raise ValueError("expected 452 singleton blocking clauses")

    formula = Path(metadata["cnf"]["path"])
    if sha256(formula) != metadata["cnf"]["sha256"]:
        raise ValueError("formula hash mismatch")
    actual_clauses = []
    start = block["serialized_clause_start"]
    end = start + block["serialized_clauses"] - 1
    with formula.open("r", encoding="ascii") as handle:
        header = handle.readline().split()
        if header != [
            "p",
            "cnf",
            str(metadata["cnf"]["variables"]),
            str(metadata["cnf"]["clauses"]),
        ]:
            raise ValueError("DIMACS header mismatch")
        for clause_number, line in enumerate(handle, start=1):
            if start <= clause_number <= end:
                actual_clauses.append(parse_clause(line))
    if actual_clauses != expected_clauses:
        raise ValueError("serialized singleton block differs from reconstruction")
    digest = hashlib.sha256()
    for clause in actual_clauses:
        digest.update(
            (" ".join(map(str, clause)) + " 0\n").encode("ascii")
        )
    if digest.hexdigest() != block["serialized_block_sha256"]:
        raise ValueError("singleton block hash mismatch")
    mutation = list(expected_clauses)
    mutation[0] = (-mutation[0][0],) + mutation[0][1:]
    if mutation == actual_clauses:
        raise ValueError("one-literal singleton mutation was not rejected")

    if (
        control["result"] != "PASS"
        or control["translations"] != translations
        or control["direct_paf_equalities"] != 8 * 9 * 332
        or control["row_feasible_patterns"] != 171
        or control["row_feasible_orbits"] != 19
    ):
        raise ValueError("generator automorphism control is incomplete")
    parent = metadata["controls"]["id3_static_parent_binding"]
    parent_path = Path(parent["path"])
    if (
        sha256(parent_path) != parent["metadata_sha256"]
        or json.loads(parent_path.read_text())["cnf"]["sha256"]
        != parent["formula_sha256"]
    ):
        raise ValueError("ID3 parent binding failed")
    result = {
        "schema": "frontiermath-hadamard-id3-singleton-translation-audit-v1",
        "status": "pass",
        "family_id": 3,
        "formula_sha256": metadata["cnf"]["sha256"],
        "metadata_sha256": sha256(args.metadata),
        "checks": {
            "annihilator": translations,
            "normalized_patterns": 256,
            "all_orbits": 30,
            "all_orbit_size_histogram": dict(sorted(histogram.items())),
            "row_feasible_patterns": 171,
            "row_feasible_orbits": 19,
            "row_feasible_orbit_size_histogram": {"9": 19},
            "independent_pair_action_order": 81,
            "blocking_clauses_reconstructed": len(actual_clauses),
            "serialized_block_sha256": digest.hexdigest(),
            "one_literal_mutation_rejected": True,
            "direct_paf_automorphism_checks": control[
                "direct_paf_equalities"
            ],
            "parent_metadata_bound": True,
        },
        "method": (
            "Recompute the modular annihilator and all 256 normalized "
            "singleton patterns, reconstruct the 452 exact blocking clauses, "
            "and compare the DIMACS block without importing the generator or "
            "proof encoder."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
