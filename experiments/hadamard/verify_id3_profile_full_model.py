#!/usr/bin/env python3
"""Independently verify a SAT model for the full profile-ID3 CNF."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from id3_full_profile_arithmetic import (
    LENGTH,
    MULTIPLIER_GENERATOR,
    TARGET_COMBINED_PAF,
    combined_paf_profile,
    compress_residue_classes,
    cyclic_subgroup,
    multiplication_orbits,
    orbit_values_to_sequence,
    prescribed_q2_pair,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_model(path: Path, variable_count: int) -> list[bool]:
    assignments: list[bool | None] = [None] * (variable_count + 1)
    status = None
    with path.open("r", encoding="ascii") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("c"):
                continue
            if stripped.startswith("s "):
                status = stripped[2:].strip()
                continue
            if not stripped.startswith("v "):
                raise ValueError(f"unexpected model line: {stripped[:80]}")
            for token in stripped[2:].split():
                literal = int(token)
                if literal == 0:
                    continue
                variable = abs(literal)
                if not 1 <= variable <= variable_count:
                    raise ValueError(f"model variable {variable} is out of range")
                value = literal > 0
                prior = assignments[variable]
                if prior is not None and prior != value:
                    raise ValueError(f"model assigns variable {variable} twice")
                assignments[variable] = value
    if status != "SATISFIABLE":
        raise ValueError(f"model status is {status!r}, not SATISFIABLE")
    missing = [
        variable
        for variable in range(1, variable_count + 1)
        if assignments[variable] is None
    ]
    if missing:
        raise ValueError(f"model omits variables, first missing: {missing[:5]}")
    return [False] + [bool(value) for value in assignments[1:]]


def stream_check_cnf(
    cnf_path: Path,
    assignments: list[bool],
) -> dict[str, int | bool]:
    variable_count = None
    declared_clauses = None
    clauses = 0
    unsatisfied = 0
    maximum_clause_length = 0
    with cnf_path.open("r", encoding="ascii") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("c"):
                continue
            if stripped.startswith("p "):
                fields = stripped.split()
                if len(fields) != 4 or fields[1] != "cnf":
                    raise ValueError("invalid DIMACS header")
                variable_count = int(fields[2])
                declared_clauses = int(fields[3])
                if variable_count != len(assignments) - 1:
                    raise ValueError("model and DIMACS variable counts differ")
                continue
            if variable_count is None:
                raise ValueError("DIMACS clause appears before the header")
            tokens = [int(token) for token in stripped.split()]
            if not tokens or tokens[-1] != 0:
                raise ValueError("DIMACS clause is not zero-terminated")
            literals = tokens[:-1]
            maximum_clause_length = max(maximum_clause_length, len(literals))
            clauses += 1
            if not any(
                assignments[abs(literal)] == (literal > 0)
                for literal in literals
            ):
                unsatisfied += 1
                if unsatisfied >= 10:
                    break
    if declared_clauses is None:
        raise ValueError("DIMACS header is missing")
    if unsatisfied == 0 and clauses != declared_clauses:
        raise ValueError(
            f"parsed {clauses} clauses, expected {declared_clauses}"
        )
    return {
        "declared_variables": variable_count,
        "declared_clauses": declared_clauses,
        "clauses_checked": clauses,
        "maximum_clause_length": maximum_clause_length,
        "unsatisfied_clauses": unsatisfied,
        "satisfied": unsatisfied == 0,
    }


def direct_profile_checks(
    first: list[int],
    second: list[int],
    record: dict[str, Any],
) -> dict[str, Any]:
    prescribed_a, prescribed_b = prescribed_q2_pair()
    compression9_a = compress_residue_classes(first, 9)
    compression9_b = compress_residue_classes(second, 9)
    compression37_a = compress_residue_classes(first, 37)
    compression37_b = compress_residue_classes(second, 37)
    combined = combined_paf_profile(first, second)
    violations = [
        {"shift": shift, "value": combined[shift]}
        for shift in range(1, LENGTH)
        if combined[shift] != TARGET_COMBINED_PAF
    ]
    checks = {
        "a_domain": all(value in (-1, 1) for value in first),
        "b_domain": all(value in (-1, 1) for value in second),
        "a_row_sum": sum(first) == 1,
        "b_row_sum": sum(second) == 1,
        "a_compression9": compression9_a == record["a_tilde"],
        "b_compression9": compression9_b == record["b_tilde"],
        "a_compression37": compression37_a == prescribed_a,
        "b_compression37": compression37_b == prescribed_b,
        "all_nonzero_combined_paf": not violations,
    }
    return {
        "checks": checks,
        "compression9": {"a": compression9_a, "b": compression9_b},
        "compression37": {"a": compression37_a, "b": compression37_b},
        "combined_paf_violation_count": len(violations),
        "first_combined_paf_violations": violations[:12],
        "verified_legendre_pair": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("profile_ledger", type=Path)
    parser.add_argument("--cnf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    encoding = json.loads(
        args.encoding_metadata.read_text(encoding="utf-8")
    )
    ledger = json.loads(args.profile_ledger.read_text(encoding="utf-8"))
    if encoding.get("status") != "generated":
        raise ValueError("encoding metadata is not generated")
    if encoding["cnf"]["sha256"] != sha256_file(args.cnf):
        raise ValueError("CNF hash does not match encoding metadata")
    if encoding["inputs"]["profile_ledger_sha256"] != sha256_file(
        args.profile_ledger
    ):
        raise ValueError("ledger hash does not match encoding metadata")
    record = next(
        item
        for item in ledger["records"]
        if item["id"] == encoding["profile_id"]
    )

    variable_count = encoding["cnf"]["variables"]
    assignments = parse_model(args.model, variable_count)
    cnf_check = stream_check_cnf(args.cnf, assignments)

    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    primary = encoding["primary_variables"]
    first_orbit_values = [
        -1 if assignments[variable] else 1 for variable in primary["za"]
    ]
    second_orbit_values = [
        -1 if assignments[variable] else 1 for variable in primary["zb"]
    ]
    first = orbit_values_to_sequence(orbits, first_orbit_values)
    second = orbit_values_to_sequence(orbits, second_orbit_values)
    direct = direct_profile_checks(first, second, record)

    mutated = list(first)
    mutated_orbit = next(orbit for orbit in orbits if len(orbit) == 3)
    for position in mutated_orbit:
        mutated[position] *= -1
    mutated_direct = direct_profile_checks(mutated, second, record)
    mutation_rejected = not mutated_direct["verified_legendre_pair"]

    checks = {
        "complete_model": True,
        "cnf_model_satisfied": cnf_check["satisfied"],
        "direct_profile_and_full_paf": direct["verified_legendre_pair"],
        "single_orbit_mutation_rejected": mutation_rejected,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-hadamard-id3-profile-full-model-audit-v1",
        "status": status,
        "checks": checks,
        "cnf_check": cnf_check,
        "direct": direct,
        "mutation_control": {
            "mutation": "flipped the first size-three multiplier orbit in A",
            "rejected": mutation_rejected,
            "mutated_direct_checks": mutated_direct["checks"],
        },
        "candidate": {
            "a_orbit_values": first_orbit_values,
            "b_orbit_values": second_orbit_values,
            "a_sequence": first,
            "b_sequence": second,
        }
        if status == "pass"
        else None,
        "inputs": {
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "model_sha256": sha256_file(args.model),
            "cnf_sha256": sha256_file(args.cnf),
            "profile_ledger_sha256": sha256_file(args.profile_ledger),
        },
        "auditor_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

