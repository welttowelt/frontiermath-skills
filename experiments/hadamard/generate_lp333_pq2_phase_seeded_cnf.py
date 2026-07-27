#!/usr/bin/env python3
"""Rename LP333 pq2 primary literals around a heuristic phase seed."""

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


def compression(sequence: list[int]) -> list[int]:
    return [
        sum(sequence[residue::37]) for residue in range(37)
    ]


def check_heuristic(
    result: dict[str, object], metadata: dict[str, object]
) -> dict[str, object]:
    a = result.get("a_sequence")
    b = result.get("b_sequence")
    if not (
        isinstance(a, list)
        and isinstance(b, list)
        and len(a) == LENGTH
        and len(b) == LENGTH
        and set(a) <= {-1, 1}
        and set(b) <= {-1, 1}
    ):
        raise ValueError("heuristic lacks two binary length-333 rows")
    a_paf = paf(a)
    b_paf = paf(b)
    residual = [
        a_paf[shift] + b_paf[shift] + 2
        for shift in range(1, HALF + 1)
    ]
    objective = sum(value * value for value in residual)
    expected = metadata["controls"]["compressed_seed_identity"][
        "compressed_rows"
    ]
    checks = {
        "row_sums_one": sum(a) == sum(b) == 1,
        "prescribed_compressions": (
            [compression(a), compression(b)] == expected
        ),
        "stored_objective": result.get("best_objective") == objective,
        "stored_residual": (
            result.get("combined_residual_independent") == residual
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"heuristic binding failed: {checks}")
    return {
        "checks": checks,
        "objective": objective,
        "l1_residual": sum(map(abs, residual)),
        "maximum_absolute_residual": max(map(abs, residual)),
        "a_sequence": a,
        "b_sequence": b,
    }


def rename_formula(
    source: Path, destination: Path, flipped: set[int]
) -> tuple[int, int]:
    declared_variables = None
    declared_clauses = None
    clauses = 0
    with source.open("r", encoding="ascii") as input_handle, (
        destination.open("w", encoding="ascii")
    ) as output_handle:
        for line_number, line in enumerate(input_handle, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("c"):
                output_handle.write(line)
                continue
            if stripped.startswith("p "):
                fields = stripped.split()
                if len(fields) != 4 or fields[1] != "cnf":
                    raise ValueError("invalid DIMACS header")
                declared_variables = int(fields[2])
                declared_clauses = int(fields[3])
                output_handle.write(
                    f"p cnf {declared_variables} {declared_clauses}\n"
                )
                continue
            literals = [int(token) for token in stripped.split()]
            if not literals or literals[-1] != 0:
                raise ValueError(
                    f"unterminated clause at line {line_number}"
                )
            transformed = [
                -literal if abs(literal) in flipped else literal
                for literal in literals[:-1]
            ]
            output_handle.write(
                " ".join(map(str, transformed)) + " 0\n"
            )
            clauses += 1
    if declared_variables is None or declared_clauses is None:
        raise ValueError("DIMACS header missing")
    if clauses != declared_clauses:
        raise ValueError(
            f"clause count {clauses} differs from {declared_clauses}"
        )
    return declared_variables, declared_clauses


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("heuristic_result", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    metadata = json.loads(args.encoding_metadata.read_text())
    if (
        metadata.get("schema")
        != "frontiermath-hadamard-lp333-pq2-cnf-v1"
        or metadata.get("family_id") != 0
    ):
        raise ValueError("metadata is not the unrestricted pq2 formula")
    source_formula = Path(metadata["cnf"]["path"])
    if sha256_file(source_formula) != metadata["cnf"]["sha256"]:
        raise ValueError("source formula hash does not match metadata")
    result = json.loads(args.heuristic_result.read_text())
    heuristic = check_heuristic(result, metadata)

    primary = metadata["primary_variables"]
    za = primary["za"]
    zb = primary["zb"]
    if len(za) != LENGTH or len(zb) != LENGTH:
        raise ValueError("primary variable map has wrong length")
    desired = [
        value == -1
        for value in heuristic["a_sequence"] + heuristic["b_sequence"]
    ]
    variables = za + zb
    flipped = {
        variable
        for variable, assignment in zip(variables, desired)
        if not assignment
    }
    if len(flipped) != 334:
        raise ValueError("row sums should produce 334 positive signs")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    destination = args.output_dir / "lp333-pq2-phase-seeded.cnf"
    variable_count, clause_count = rename_formula(
        source_formula, destination, flipped
    )
    output = {
        "schema": "frontiermath-lp333-pq2-phase-seeded-cnf-v1",
        "status": "generated",
        "scope": "literal-renamed unrestricted pq2 formula",
        "semantics": (
            "Original primary x equals renamed y when the heuristic sign "
            "is -1, and equals not-y when the heuristic sign is +1. "
            "Thus renamed phase true maps to the heuristic primary state."
        ),
        "source_formula": {
            "path": str(source_formula),
            "sha256": sha256_file(source_formula),
            "variables": metadata["cnf"]["variables"],
            "clauses": metadata["cnf"]["clauses"],
        },
        "phase_seeded_formula": {
            "path": str(destination),
            "sha256": sha256_file(destination),
            "bytes": destination.stat().st_size,
            "variables": variable_count,
            "clauses": clause_count,
        },
        "literal_renaming": {
            "default_renamed_phase": True,
            "flipped_primary_variables": sorted(flipped),
            "flipped_primary_count": len(flipped),
            "unchanged_primary_count": len(variables) - len(flipped),
            "auxiliary_variables_unchanged": True,
        },
        "heuristic": {
            "path": str(args.heuristic_result),
            "sha256": sha256_file(args.heuristic_result),
            "objective": heuristic["objective"],
            "l1_residual": heuristic["l1_residual"],
            "maximum_absolute_residual": (
                heuristic["maximum_absolute_residual"]
            ),
            "checks": heuristic["checks"],
        },
        "inputs": {
            "encoding_metadata": str(args.encoding_metadata),
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "generator_sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    output_path = args.output_dir / "encoding.json"
    output_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
