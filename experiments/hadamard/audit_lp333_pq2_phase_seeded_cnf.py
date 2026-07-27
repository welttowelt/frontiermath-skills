#!/usr/bin/env python3
"""Independently audit an LP333 pq2 literal-renamed phase seed."""

from __future__ import annotations

import argparse
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
from typing import Any


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


def compression(sequence: list[int]) -> list[int]:
    return [
        sum(sequence[residue::37]) for residue in range(37)
    ]


def clause_literals(line: str) -> list[int] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("c"):
        return None
    if stripped.startswith("p "):
        return None
    values = [int(token) for token in stripped.split()]
    if not values or values[-1] != 0:
        raise ValueError("unterminated DIMACS clause")
    return values[:-1]


def audit_formula_renaming(
    source: Path, transformed: Path, flipped: set[int]
) -> dict[str, Any]:
    lines = 0
    clauses = 0
    literals = 0
    changed_literals = 0
    source_header = None
    transformed_header = None
    exact = True
    with source.open("r", encoding="ascii") as left, (
        transformed.open("r", encoding="ascii")
    ) as right:
        for source_line, transformed_line in zip_longest(left, right):
            lines += 1
            if source_line is None or transformed_line is None:
                exact = False
                break
            source_stripped = source_line.strip()
            transformed_stripped = transformed_line.strip()
            if source_stripped.startswith("p "):
                source_header = source_stripped.split()
                transformed_header = transformed_stripped.split()
                if source_header != transformed_header:
                    exact = False
                continue
            source_clause = clause_literals(source_line)
            transformed_clause = clause_literals(transformed_line)
            if source_clause is None:
                if transformed_clause is not None:
                    exact = False
                continue
            if transformed_clause is None:
                exact = False
                continue
            expected = [
                -literal if abs(literal) in flipped else literal
                for literal in source_clause
            ]
            if transformed_clause != expected:
                exact = False
            clauses += 1
            literals += len(source_clause)
            changed_literals += sum(
                left_literal != right_literal
                for left_literal, right_literal in zip(
                    source_clause, transformed_clause
                )
            )
    return {
        "exact_literal_renaming": exact,
        "streamed_lines": lines,
        "streamed_clauses": clauses,
        "streamed_literals": literals,
        "changed_literal_occurrences": changed_literals,
        "source_header": source_header,
        "transformed_header": transformed_header,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("phase_metadata", type=Path)
    parser.add_argument("--generator", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    metadata = json.loads(args.encoding_metadata.read_text())
    phase = json.loads(args.phase_metadata.read_text())
    heuristic_path = Path(phase["heuristic"]["path"])
    heuristic = json.loads(heuristic_path.read_text())
    source_formula = Path(phase["source_formula"]["path"])
    transformed_formula = Path(
        phase["phase_seeded_formula"]["path"]
    )
    flipped = set(
        phase["literal_renaming"]["flipped_primary_variables"]
    )

    a = heuristic.get("a_sequence")
    b = heuristic.get("b_sequence")
    domains = (
        isinstance(a, list)
        and isinstance(b, list)
        and len(a) == LENGTH
        and len(b) == LENGTH
        and set(a) <= {-1, 1}
        and set(b) <= {-1, 1}
    )
    if not domains:
        raise ValueError("heuristic lacks two binary length-333 rows")
    a_paf = paf(a)
    b_paf = paf(b)
    residual = [
        a_paf[shift] + b_paf[shift] + 2
        for shift in range(1, HALF + 1)
    ]
    objective = sum(value * value for value in residual)
    expected_compressions = metadata["controls"][
        "compressed_seed_identity"
    ]["compressed_rows"]
    primary = (
        metadata["primary_variables"]["za"]
        + metadata["primary_variables"]["zb"]
    )
    desired = [value == -1 for value in a + b]
    phase_mapping = {
        variable: (not True if variable in flipped else True)
        for variable in primary
    }
    mapping_matches = all(
        phase_mapping[variable] == assignment
        for variable, assignment in zip(primary, desired)
    )
    mutation_variable = min(flipped)
    mutated_flipped = flipped - {mutation_variable}
    mutated_mapping = {
        variable: (
            not True if variable in mutated_flipped else True
        )
        for variable in primary
    }
    mutation_rejected = any(
        mutated_mapping[variable] != assignment
        for variable, assignment in zip(primary, desired)
    )
    formula_audit = audit_formula_renaming(
        source_formula, transformed_formula, flipped
    )
    checks = {
        "metadata_schema": (
            metadata.get("schema")
            == "frontiermath-hadamard-lp333-pq2-cnf-v1"
        ),
        "phase_metadata_schema": (
            phase.get("schema")
            == "frontiermath-lp333-pq2-phase-seeded-cnf-v1"
        ),
        "binary_length_333_heuristic": domains,
        "heuristic_row_sums_one": sum(a) == sum(b) == 1,
        "heuristic_prescribed_compressions": (
            [compression(a), compression(b)] == expected_compressions
        ),
        "heuristic_stored_objective": (
            heuristic.get("best_objective") == objective
            and phase["heuristic"]["objective"] == objective
        ),
        "heuristic_stored_residual": (
            heuristic.get("combined_residual_independent") == residual
        ),
        "primary_map_length": len(primary) == 2 * LENGTH,
        "flipped_count": len(flipped) == 334,
        "all_true_phase_maps_to_heuristic": mapping_matches,
        "mapping_mutation_rejected": mutation_rejected,
        "source_formula_hash": (
            sha256_file(source_formula)
            == metadata["cnf"]["sha256"]
            == phase["source_formula"]["sha256"]
        ),
        "transformed_formula_hash": (
            sha256_file(transformed_formula)
            == phase["phase_seeded_formula"]["sha256"]
        ),
        "formula_dimensions_preserved": (
            phase["source_formula"]["variables"]
            == phase["phase_seeded_formula"]["variables"]
            == metadata["cnf"]["variables"]
            and phase["source_formula"]["clauses"]
            == phase["phase_seeded_formula"]["clauses"]
            == metadata["cnf"]["clauses"]
        ),
        "full_stream_literal_renaming": (
            formula_audit["exact_literal_renaming"]
            and formula_audit["streamed_clauses"]
            == metadata["cnf"]["clauses"]
        ),
        "metadata_input_hash": (
            phase["inputs"]["encoding_metadata_sha256"]
            == sha256_file(args.encoding_metadata)
        ),
        "heuristic_input_hash": (
            phase["heuristic"]["sha256"]
            == sha256_file(heuristic_path)
        ),
        "generator_hash": (
            phase["inputs"]["generator_sha256"]
            == sha256_file(args.generator)
        ),
    }
    status = "pass" if all(checks.values()) else "fail"
    document = {
        "schema": "frontiermath-lp333-pq2-phase-seeded-cnf-audit-v1",
        "status": status,
        "objective": objective,
        "l1_residual": sum(map(abs, residual)),
        "maximum_absolute_residual": max(map(abs, residual)),
        "checks": checks,
        "formula_audit": formula_audit,
        "phase_mapping": {
            "primary_variables": len(primary),
            "flipped_variables": len(flipped),
            "unchanged_variables": len(primary) - len(flipped),
            "mutation_variable": mutation_variable,
        },
        "inputs": {
            "encoding_metadata": str(args.encoding_metadata),
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "phase_metadata": str(args.phase_metadata),
            "phase_metadata_sha256": sha256_file(
                args.phase_metadata
            ),
            "heuristic": str(heuristic_path),
            "heuristic_sha256": sha256_file(heuristic_path),
            "source_formula": str(source_formula),
            "source_formula_sha256": sha256_file(source_formula),
            "transformed_formula": str(transformed_formula),
            "transformed_formula_sha256": sha256_file(
                transformed_formula
            ),
            "generator": str(args.generator),
            "generator_sha256": sha256_file(args.generator),
            "auditor_sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
