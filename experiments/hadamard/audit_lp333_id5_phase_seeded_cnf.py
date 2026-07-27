#!/usr/bin/env python3
"""Independently audit an LP333 ID5 literal-renamed phase seed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import audit_lp333_id5_orbit_anneal as id5
import audit_lp333_pq2_phase_seeded_cnf as phase_common


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("phase_metadata", type=Path)
    parser.add_argument("--generator", required=True, type=Path)
    parser.add_argument(
        "--shared-generator", required=True, type=Path
    )
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
        and len(a) == id5.LENGTH
        and len(b) == id5.LENGTH
        and set(a) <= {-1, 1}
        and set(b) <= {-1, 1}
    )
    if not domains:
        raise ValueError("heuristic lacks two binary length-333 rows")
    a_paf = id5.paf(a)
    b_paf = id5.paf(b)
    residual = [
        a_paf[shift] + b_paf[shift] + 2
        for shift in range(1, id5.HALF + 1)
    ]
    objective = sum(value * value for value in residual)
    profiles = (id5.invariance_profile(a), id5.invariance_profile(b))
    orbits = metadata["subgroup"]["orbits"]
    orbit_values = [
        [sequence[orbit[0]] for orbit in orbits]
        for sequence in (a, b)
    ]
    orbit_constant = all(
        all(
            len({sequence[index] for index in orbit}) == 1
            for orbit in orbits
        )
        for sequence in (a, b)
    )
    primary = (
        metadata["primary_variables"]["za"]
        + metadata["primary_variables"]["zb"]
    )
    desired = [
        value == -1
        for values in orbit_values
        for value in values
    ]
    phase_mapping = {
        variable: (not True if variable in flipped else True)
        for variable in primary
    }
    mapping_matches = all(
        phase_mapping[variable] == assignment
        for variable, assignment in zip(primary, desired)
    )
    mutation_variable = min(flipped)
    mutated_mapping = dict(phase_mapping)
    mutated_mapping[mutation_variable] = not mutated_mapping[
        mutation_variable
    ]
    mutation_rejected = any(
        mutated_mapping[variable] != assignment
        for variable, assignment in zip(primary, desired)
    )
    formula_audit = phase_common.audit_formula_renaming(
        source_formula, transformed_formula, flipped
    )
    checks = {
        "metadata_schema_and_family": (
            metadata.get("schema")
            == "frontiermath-hadamard-lp333-symmetry-cnf-v1"
            and metadata.get("family_id") == 5
        ),
        "phase_metadata_schema_and_family": (
            phase.get("schema")
            == "frontiermath-lp333-id5-phase-seeded-cnf-v1"
            and phase.get("family_id") == 5
        ),
        "binary_length_333_heuristic": domains,
        "heuristic_id5_invariance": (
            orbit_constant
            and all(profile["invariant"] for profile in profiles)
        ),
        "heuristic_forced_margins": all(
            profile["row_sum"] == 1
            and profile["negative_singletons"] == 1
            and profile["negative_triples"] == 55
            for profile in profiles
        ),
        "heuristic_stored_objective": (
            heuristic.get("best_objective") == objective
            and phase["heuristic"]["objective"] == objective
        ),
        "heuristic_stored_residual": (
            heuristic.get("combined_residual_independent") == residual
        ),
        "primary_map_length": len(primary) == 226,
        "flipped_count": len(flipped) == 114,
        "all_true_phase_maps_to_heuristic": mapping_matches,
        "mapping_mutation_rejected": mutation_rejected,
        "source_formula_hash": (
            id5.sha256_file(source_formula)
            == metadata["cnf"]["sha256"]
            == phase["source_formula"]["sha256"]
        ),
        "transformed_formula_hash": (
            id5.sha256_file(transformed_formula)
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
            == id5.sha256_file(args.encoding_metadata)
        ),
        "heuristic_input_hash": (
            phase["heuristic"]["sha256"]
            == id5.sha256_file(heuristic_path)
        ),
        "generator_hash": (
            phase["inputs"]["generator_sha256"]
            == id5.sha256_file(args.generator)
        ),
        "shared_generator_hash": (
            phase["inputs"]["shared_generator_sha256"]
            == id5.sha256_file(args.shared_generator)
        ),
    }
    status = "pass" if all(checks.values()) else "fail"
    document = {
        "schema": "frontiermath-lp333-id5-phase-seeded-cnf-audit-v1",
        "status": status,
        "family_id": 5,
        "objective": objective,
        "l1_residual": sum(map(abs, residual)),
        "maximum_absolute_residual": max(map(abs, residual)),
        "checks": checks,
        "formula_audit": formula_audit,
        "profiles": profiles,
        "phase_mapping": {
            "primary_variables": len(primary),
            "flipped_variables": len(flipped),
            "unchanged_variables": len(primary) - len(flipped),
            "mutation_variable": mutation_variable,
        },
        "inputs": {
            "encoding_metadata": str(args.encoding_metadata),
            "encoding_metadata_sha256": id5.sha256_file(
                args.encoding_metadata
            ),
            "phase_metadata": str(args.phase_metadata),
            "phase_metadata_sha256": id5.sha256_file(
                args.phase_metadata
            ),
            "heuristic": str(heuristic_path),
            "heuristic_sha256": id5.sha256_file(heuristic_path),
            "source_formula": str(source_formula),
            "source_formula_sha256": id5.sha256_file(
                source_formula
            ),
            "transformed_formula": str(transformed_formula),
            "transformed_formula_sha256": id5.sha256_file(
                transformed_formula
            ),
            "generator": str(args.generator),
            "generator_sha256": id5.sha256_file(args.generator),
            "shared_generator": str(args.shared_generator),
            "shared_generator_sha256": id5.sha256_file(
                args.shared_generator
            ),
            "auditor_sha256": id5.sha256_file(
                Path(__file__).resolve()
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
