#!/usr/bin/env python3
"""Directly verify a SAT model for an LP333 multiplier-family CNF."""

from __future__ import annotations

import argparse
import hashlib
import json
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


def parse_model(path: Path, variable_count: int) -> list[bool]:
    values: list[bool | None] = [None] * (variable_count + 1)
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
                    raise ValueError("model variable is out of range")
                assignment = literal > 0
                if (
                    values[variable] is not None
                    and values[variable] != assignment
                ):
                    raise ValueError("model assigns a variable inconsistently")
                values[variable] = assignment
    if status != "SATISFIABLE":
        raise ValueError(f"model status is {status!r}")
    missing = [
        variable
        for variable in range(1, variable_count + 1)
        if values[variable] is None
    ]
    if missing:
        raise ValueError(f"model omits variables: {missing[:5]}")
    return [False] + [bool(value) for value in values[1:]]


def stream_check_cnf(
    path: Path, assignments: list[bool]
) -> dict[str, int | bool]:
    variables = None
    declared_clauses = None
    clauses = 0
    unsatisfied = 0
    maximum_clause_length = 0
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
                if variables != len(assignments) - 1:
                    raise ValueError("model and CNF variable counts differ")
                continue
            literals = [int(token) for token in stripped.split()]
            if not literals or literals[-1] != 0:
                raise ValueError("unterminated DIMACS clause")
            clause = literals[:-1]
            clauses += 1
            maximum_clause_length = max(
                maximum_clause_length, len(clause)
            )
            if not any(
                assignments[abs(literal)] == (literal > 0)
                for literal in clause
            ):
                unsatisfied += 1
                if unsatisfied >= 10:
                    break
    if variables is None or declared_clauses is None:
        raise ValueError("DIMACS header missing")
    if unsatisfied == 0 and clauses != declared_clauses:
        raise ValueError("DIMACS clause count differs from its header")
    return {
        "declared_variables": variables,
        "declared_clauses": declared_clauses,
        "clauses_checked": clauses,
        "maximum_clause_length": maximum_clause_length,
        "unsatisfied_clauses": unsatisfied,
        "satisfied": unsatisfied == 0,
    }


def sequence_from_orbits(
    orbits: list[list[int]], orbit_values: list[int]
) -> list[int]:
    sequence = [0] * LENGTH
    for orbit, value in strict_zip(orbits, orbit_values):
        for position in orbit:
            if sequence[position] != 0:
                raise ValueError("orbits overlap")
            sequence[position] = value
    if any(value == 0 for value in sequence):
        raise ValueError("orbits do not cover the sequence")
    return sequence


def paf(sequence: list[int]) -> list[int]:
    negative = sum(
        1 << index
        for index, value in enumerate(sequence)
        if value == -1
    )
    mask = (1 << LENGTH) - 1
    result = []
    for shift in range(LENGTH):
        rotated = (
            negative
            if shift == 0
            else (
                (negative >> shift)
                | (negative << (LENGTH - shift))
            )
            & mask
        )
        result.append(LENGTH - 2 * int_bit_count(negative ^ rotated))
    return result


def direct_checks(
    first: list[int],
    second: list[int],
    subgroup: list[int],
) -> dict[str, Any]:
    first_paf = paf(first)
    second_paf = paf(second)
    violations = [
        {
            "shift": shift,
            "a": first_paf[shift],
            "b": second_paf[shift],
            "combined": first_paf[shift] + second_paf[shift],
        }
        for shift in range(1, LENGTH)
        if first_paf[shift] + second_paf[shift] != TARGET_PAF
    ]
    invariance_errors = []
    for name, sequence in (("a", first), ("b", second)):
        for multiplier in subgroup:
            for position in range(LENGTH):
                if sequence[position] != sequence[
                    multiplier * position % LENGTH
                ]:
                    invariance_errors.append(
                        {
                            "sequence": name,
                            "multiplier": multiplier,
                            "position": position,
                        }
                    )
                    break
            if invariance_errors:
                break
    checks = {
        "a_domain": all(value in (-1, 1) for value in first),
        "b_domain": all(value in (-1, 1) for value in second),
        "a_row_sum": sum(first) in (-1, 1),
        "b_row_sum": sum(second) in (-1, 1),
        "subgroup_invariance": not invariance_errors,
        "all_nonzero_combined_paf": not violations,
    }
    return {
        "checks": checks,
        "row_sums": {"a": sum(first), "b": sum(second)},
        "combined_paf_violation_count": len(violations),
        "first_combined_paf_violations": violations[:12],
        "invariance_error_count": len(invariance_errors),
        "first_invariance_errors": invariance_errors[:12],
        "verified_legendre_pair": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("--cnf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    metadata = json.loads(
        args.encoding_metadata.read_text(encoding="utf-8")
    )
    if metadata.get("status") != "generated":
        raise ValueError("encoding metadata is not generated")
    if metadata["cnf"]["sha256"] != sha256_file(args.cnf):
        raise ValueError("CNF hash does not match metadata")
    assignments = parse_model(args.model, metadata["cnf"]["variables"])
    cnf_check = stream_check_cnf(args.cnf, assignments)

    primary = metadata["primary_variables"]
    first_values = [
        -1 if assignments[variable] else 1
        for variable in primary["za"]
    ]
    second_values = [
        -1 if assignments[variable] else 1
        for variable in primary["zb"]
    ]
    orbits = metadata["subgroup"]["orbits"]
    first = sequence_from_orbits(orbits, first_values)
    second = sequence_from_orbits(orbits, second_values)
    direct = direct_checks(
        first, second, metadata["subgroup"]["elements"]
    )

    mutated = list(first)
    row_sum = sum(mutated)
    target_value = -row_sum
    position = next(
        index
        for index, value in enumerate(mutated)
        if value == target_value
    )
    mutated[position] *= -1
    mutated_direct = direct_checks(
        mutated, second, metadata["subgroup"]["elements"]
    )
    mutation_rejected = not mutated_direct["verified_legendre_pair"]

    checks = {
        "complete_model": True,
        "cnf_model_satisfied": cnf_check["satisfied"],
        "direct_full_lp333": direct["verified_legendre_pair"],
        "single_coordinate_mutation_rejected": mutation_rejected,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-hadamard-lp333-family-model-audit-v1",
        "status": status,
        "family_id": metadata["family_id"],
        "checks": checks,
        "cnf_check": cnf_check,
        "direct": direct,
        "mutation_control": {
            "mutation": (
                f"flipped A coordinate {position} chosen to force row sum "
                "outside +/-1"
            ),
            "rejected": mutation_rejected,
            "mutated_checks": mutated_direct["checks"],
        },
        "candidate": {
            "a_orbit_values": first_values,
            "b_orbit_values": second_values,
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
