#!/usr/bin/env python3
"""Rename LP333 ID5 primary literals around an invariant heuristic state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import generate_lp333_pq2_phase_seeded_cnf as common


def invariant_orbit_values(
    sequence: list[int], orbits: list[list[int]]
) -> list[int]:
    values = []
    for orbit in orbits:
        signs = {sequence[index] for index in orbit}
        if len(signs) != 1:
            raise ValueError("heuristic is not ID5-invariant")
        values.append(next(iter(signs)))
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("heuristic_result", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    metadata = json.loads(args.encoding_metadata.read_text())
    if (
        metadata.get("schema")
        != "frontiermath-hadamard-lp333-symmetry-cnf-v1"
        or metadata.get("family_id") != 5
        or metadata["subgroup"]["elements"] != [1, 211, 232]
    ):
        raise ValueError("metadata is not the ID5 symmetry formula")
    source_formula = Path(metadata["cnf"]["path"])
    if common.sha256_file(source_formula) != metadata["cnf"]["sha256"]:
        raise ValueError("source formula hash does not match metadata")
    result = json.loads(args.heuristic_result.read_text())
    a = result.get("a_sequence")
    b = result.get("b_sequence")
    if not (
        isinstance(a, list)
        and isinstance(b, list)
        and len(a) == common.LENGTH
        and len(b) == common.LENGTH
        and set(a) <= {-1, 1}
        and set(b) <= {-1, 1}
    ):
        raise ValueError("heuristic lacks two binary length-333 rows")
    a_paf = common.paf(a)
    b_paf = common.paf(b)
    residual = [
        a_paf[shift] + b_paf[shift] + 2
        for shift in range(1, common.HALF + 1)
    ]
    objective = sum(value * value for value in residual)
    orbits = metadata["subgroup"]["orbits"]
    a_values = invariant_orbit_values(a, orbits)
    b_values = invariant_orbit_values(b, orbits)
    if (
        sum(a) != 1
        or sum(b) != 1
        or result.get("best_objective") != objective
        or result.get("combined_residual_independent") != residual
    ):
        raise ValueError("heuristic score or row sums do not bind")

    primary = metadata["primary_variables"]
    variables = primary["za"] + primary["zb"]
    desired = [
        value == -1 for value in a_values + b_values
    ]
    if len(variables) != 226 or len(desired) != 226:
        raise ValueError("ID5 primary map has wrong length")
    flipped = {
        variable
        for variable, assignment in zip(variables, desired)
        if not assignment
    }
    if len(flipped) != 114:
        raise ValueError("forced ID5 margins should give 114 positives")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    destination = args.output_dir / "lp333-id5-phase-seeded.cnf"
    variable_count, clause_count = common.rename_formula(
        source_formula, destination, flipped
    )
    output = {
        "schema": "frontiermath-lp333-id5-phase-seeded-cnf-v1",
        "status": "generated",
        "family_id": 5,
        "subgroup": [1, 211, 232],
        "scope": "literal-renamed ID5 symmetry formula",
        "semantics": (
            "Original orbit-sign x equals renamed y when the heuristic "
            "orbit sign is -1, and equals not-y when it is +1. Thus "
            "renamed phase true maps to the heuristic orbit state."
        ),
        "source_formula": {
            "path": str(source_formula),
            "sha256": common.sha256_file(source_formula),
            "variables": metadata["cnf"]["variables"],
            "clauses": metadata["cnf"]["clauses"],
        },
        "phase_seeded_formula": {
            "path": str(destination),
            "sha256": common.sha256_file(destination),
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
            "sha256": common.sha256_file(args.heuristic_result),
            "objective": objective,
            "l1_residual": sum(map(abs, residual)),
            "maximum_absolute_residual": max(map(abs, residual)),
            "row_sums": [sum(a), sum(b)],
            "orbit_values_per_row": [len(a_values), len(b_values)],
        },
        "inputs": {
            "encoding_metadata": str(args.encoding_metadata),
            "encoding_metadata_sha256": common.sha256_file(
                args.encoding_metadata
            ),
            "generator_sha256": common.sha256_file(
                Path(__file__).resolve()
            ),
            "shared_generator_sha256": common.sha256_file(
                Path(common.__file__).resolve()
            ),
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
