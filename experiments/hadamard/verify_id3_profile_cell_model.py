#!/usr/bin/env python3
"""Independently check a SAT model for an id3 profile-cell CNF."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import time
from collections import Counter
from pathlib import Path


P = 37
Q = 3
K37 = (1, 10, 26)
LENGTH = 9
TARGET_NORM = 594
TARGET_PAF = -74


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_dimacs(path: Path) -> tuple[int, list[list[int]]]:
    variable_count = None
    declared_clause_count = None
    clauses: list[list[int]] = []
    pending: list[int] = []
    with path.open("r", encoding="ascii") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("c"):
                continue
            if stripped.startswith("p"):
                fields = stripped.split()
                if (
                    len(fields) != 4
                    or fields[0] != "p"
                    or fields[1] != "cnf"
                ):
                    raise ValueError(f"bad DIMACS header on line {line_number}")
                if variable_count is not None:
                    raise ValueError("multiple DIMACS headers")
                variable_count = int(fields[2])
                declared_clause_count = int(fields[3])
                continue
            if variable_count is None:
                raise ValueError("clause appears before DIMACS header")
            for token in stripped.split():
                literal = int(token)
                if literal == 0:
                    if not pending:
                        raise ValueError("empty DIMACS clause")
                    clauses.append(pending)
                    pending = []
                else:
                    if abs(literal) > variable_count:
                        raise ValueError("literal exceeds DIMACS variable count")
                    pending.append(literal)
    if variable_count is None or declared_clause_count is None:
        raise ValueError("missing DIMACS header")
    if pending:
        raise ValueError("unterminated DIMACS clause")
    if len(clauses) != declared_clause_count:
        raise ValueError(
            f"found {len(clauses)} clauses, expected {declared_clause_count}"
        )
    return variable_count, clauses


def parse_model(path: Path, variable_count: int) -> dict[int, bool]:
    status = None
    assignment: dict[int, bool] = {}
    with path.open("r", encoding="ascii") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("c"):
                continue
            if stripped.startswith("s "):
                status = stripped[2:].strip()
                continue
            if not stripped.startswith("v "):
                continue
            for token in stripped[2:].split():
                literal = int(token)
                if literal == 0:
                    continue
                variable = abs(literal)
                if not 1 <= variable <= variable_count:
                    raise ValueError(
                        f"model literal out of range on line {line_number}"
                    )
                value = literal > 0
                previous = assignment.get(variable)
                if previous is not None and previous != value:
                    raise ValueError("contradictory model literals")
                assignment[variable] = value
    if status != "SATISFIABLE":
        raise ValueError(f"model status is {status!r}, expected SATISFIABLE")
    missing = [
        variable
        for variable in range(1, variable_count + 1)
        if variable not in assignment
    ]
    if missing:
        raise ValueError(
            f"model omits {len(missing)} variables; first is {missing[0]}"
        )
    return assignment


def legendre_symbol(value: int) -> int:
    residue = pow(value % P, (P - 1) // 2, P)
    return 0 if residue == 0 else (1 if residue == 1 else -1)


def k37_orbits() -> list[list[int]]:
    unseen = set(range(P))
    orbits = []
    while unseen:
        seed = min(unseen)
        orbit = sorted({(multiplier * seed) % P for multiplier in K37})
        unseen.difference_update(orbit)
        orbits.append(orbit)
    return orbits


def prescribed_nonzero_column_degrees(sign: int) -> list[int]:
    return [
        (LENGTH + sign * Q * legendre_symbol(orbit[0])) // 2
        for orbit in k37_orbits()[1:]
    ]


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[(index + shift) % len(sequence)]
        for index in range(len(sequence))
    )


def value_degree(value: int) -> tuple[int, int]:
    singleton = 1 if value % 3 == 1 else -1
    numerator = (value - singleton) // 3 + 12
    if numerator % 2:
        raise ValueError(f"value {value} has nonintegral degree")
    return singleton, numerator // 2


def selected_values(
    raw_value_variables: object,
    assignment: dict[int, bool],
) -> list[list[int]]:
    if not isinstance(raw_value_variables, list) or len(raw_value_variables) != 2:
        raise ValueError("metadata value map must contain two sequences")
    result = []
    for sequence in raw_value_variables:
        if not isinstance(sequence, list) or len(sequence) != LENGTH:
            raise ValueError("metadata sequence map must contain nine rows")
        decoded = []
        for row in sequence:
            if not isinstance(row, dict):
                raise ValueError("metadata value row is not an object")
            chosen = [
                int(value)
                for value, variable in row.items()
                if assignment[int(variable)]
            ]
            if len(chosen) != 1:
                raise ValueError(f"value row selects {len(chosen)} values")
            decoded.append(chosen[0])
        result.append(decoded)
    return result


def selected_margins(
    raw_margin_variables: object,
    assignment: dict[int, bool],
) -> list[list[list[int]]]:
    if not isinstance(raw_margin_variables, list) or len(raw_margin_variables) != 2:
        raise ValueError("metadata margin map must contain two sequences")
    margins = []
    for sequence in raw_margin_variables:
        if not isinstance(sequence, list) or len(sequence) != LENGTH:
            raise ValueError("metadata margin sequence must contain nine rows")
        rows = []
        for row in sequence:
            if not isinstance(row, list) or len(row) != 12:
                raise ValueError("metadata margin row must contain 12 columns")
            rows.append([int(assignment[int(variable)]) for variable in row])
        margins.append(rows)
    return margins


def verify_arithmetic(
    values: list[list[int]],
    margins: list[list[list[int]]],
    epsilon_variables: object,
    assignment: dict[int, bool],
    square_counts: dict[int, int],
) -> tuple[list[str], dict[str, object]]:
    problems: list[str] = []
    a, b = values
    flat = a + b
    actual_counts = Counter(value * value for value in flat)
    if actual_counts != Counter(square_counts):
        problems.append(
            f"square counts are {dict(sorted(actual_counts.items()))}"
        )
    if sum(value * value for value in flat) != TARGET_NORM:
        problems.append("combined norm is not 594")
    if [sum(a), sum(b)] != [1, 1]:
        problems.append(f"row sums are {[sum(a), sum(b)]}")

    pafs = [
        periodic_autocorrelation(a, shift)
        + periodic_autocorrelation(b, shift)
        for shift in range(1, LENGTH)
    ]
    if pafs != [TARGET_PAF] * (LENGTH - 1):
        problems.append(f"combined PAF profile is {pafs}")

    if not isinstance(epsilon_variables, list) or len(epsilon_variables) != 2:
        raise ValueError("metadata epsilon map must contain two sequences")
    singleton_signs = []
    recomputed_row_degrees = []
    recomputed_column_degrees = []
    sign_tables = []
    for sequence_index in range(2):
        eps_vars = epsilon_variables[sequence_index]
        if not isinstance(eps_vars, list) or len(eps_vars) != LENGTH:
            raise ValueError("metadata epsilon sequence must have nine rows")
        signs = [
            1 if assignment[int(variable)] else -1
            for variable in eps_vars
        ]
        singleton_signs.append(signs)
        if sum(signs) != 1:
            problems.append(
                f"sequence {sequence_index} singleton sum is {sum(signs)}"
            )

        row_degrees = [sum(row) for row in margins[sequence_index]]
        recomputed_row_degrees.append(row_degrees)
        expected_row_degrees = []
        for row, value in enumerate(values[sequence_index]):
            singleton, degree = value_degree(value)
            expected_row_degrees.append(degree)
            if signs[row] != singleton:
                problems.append(
                    f"sequence {sequence_index} row {row} singleton mismatch"
                )
        if row_degrees != expected_row_degrees:
            problems.append(
                f"sequence {sequence_index} margin row degrees mismatch"
            )

        column_degrees = [
            sum(margins[sequence_index][row][column] for row in range(LENGTH))
            for column in range(12)
        ]
        recomputed_column_degrees.append(column_degrees)
        expected_columns = prescribed_nonzero_column_degrees(
            1 if sequence_index == 0 else -1
        )
        if column_degrees != expected_columns:
            problems.append(
                f"sequence {sequence_index} margin column degrees mismatch"
            )
        sign_tables.append(
            [
                [signs[row]]
                + [
                    1 if entry else -1
                    for entry in margins[sequence_index][row]
                ]
                for row in range(LENGTH)
            ]
        )

    mutated = [list(a), list(b)]
    mutated[0][0] = -mutated[0][0]
    mutated_pafs = [
        periodic_autocorrelation(mutated[0], shift)
        + periodic_autocorrelation(mutated[1], shift)
        for shift in range(1, LENGTH)
    ]
    adversarial_rejected = (
        [sum(mutated[0]), sum(mutated[1])] != [1, 1]
        or mutated_pafs != [TARGET_PAF] * (LENGTH - 1)
        or Counter(value * value for sequence in mutated for value in sequence)
        != Counter(square_counts)
    )
    if not adversarial_rejected:
        problems.append("single-entry adversarial mutation was not rejected")

    details = {
        "a_tilde": a,
        "b_tilde": b,
        "square_counts": {
            str(square): count for square, count in sorted(actual_counts.items())
        },
        "combined_norm": sum(value * value for value in flat),
        "row_sums": [sum(a), sum(b)],
        "combined_paf": pafs,
        "singleton_signs": singleton_signs,
        "margin_row_degrees": recomputed_row_degrees,
        "margin_column_degrees": recomputed_column_degrees,
        "sign_tables_9_by_13": sign_tables,
        "adversarial_single_entry_mutation_rejected": adversarial_rejected,
    }
    return problems, details


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--cnf", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--witness-output", type=Path)
    args = parser.parse_args()

    started = time.perf_counter()
    try:
        metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
        if metadata.get("cnf_sha256") != sha256_file(args.cnf):
            raise ValueError("CNF hash does not match encoding metadata")
        variable_count, clauses = parse_dimacs(args.cnf)
        if variable_count != metadata.get("variables"):
            raise ValueError("DIMACS variable count does not match metadata")
        if len(clauses) != metadata.get("clauses"):
            raise ValueError("DIMACS clause count does not match metadata")
        assignment = parse_model(args.model, variable_count)
        unsatisfied = [
            index
            for index, clause in enumerate(clauses)
            if not any(
                assignment[abs(literal)] == (literal > 0)
                for literal in clause
            )
        ]
        problems = []
        if unsatisfied:
            problems.append(
                f"model falsifies {len(unsatisfied)} clauses; "
                f"first is {unsatisfied[0]}"
            )

        variable_map = metadata.get("variable_map")
        if not isinstance(variable_map, dict):
            raise ValueError("encoding metadata has no variable map")
        values = selected_values(
            variable_map.get("value_variables"), assignment
        )
        margins = selected_margins(
            variable_map.get("margin_variables"), assignment
        )
        raw_counts = metadata.get("square_counts")
        if not isinstance(raw_counts, dict):
            raise ValueError("encoding metadata has no square counts")
        square_counts = {
            int(square): int(count) for square, count in raw_counts.items()
        }
        arithmetic_problems, details = verify_arithmetic(
            values,
            margins,
            variable_map.get("epsilon_plus_variables"),
            assignment,
            square_counts,
        )
        problems.extend(arithmetic_problems)
        passed = not problems
        result = {
            "schema": "frontiermath-hadamard-id3-profile-model-check-v1",
            "status": "pass" if passed else "fail",
            "claim_status": (
                "compressed-profile-cell-feasible" if passed else "rejected"
            ),
            "cell_id": metadata.get("cell_id"),
            "refined_ledger_sha256": metadata.get(
                "refined_ledger_sha256"
            ),
            "metadata_sha256": sha256_file(args.metadata),
            "cnf_sha256": sha256_file(args.cnf),
            "model_sha256": sha256_file(args.model),
            "checker_sha256": sha256_file(Path(__file__).resolve()),
            "cnf_model_satisfied": not unsatisfied,
            "problems": problems,
            "checked_predicates": [
                "complete-DIMACS-model-satisfaction",
                "one-selected-value-per-position",
                "exact-square-multiset-and-norm",
                "both-row-sums",
                "all-eight-combined-periodic-autocorrelations",
                "singleton-sign-margins",
                "explicit-nonzero-orbit-margin-row-degrees",
                "prescribed-nonzero-orbit-margin-column-degrees",
                "single-entry-adversarial-control",
            ],
            "unchecked_predicates": [
                "decompression-full-LP333-autocorrelations",
                "construction-of-Hadamard-order-668",
            ],
            "witness": details,
            "runtime_seconds": time.perf_counter() - started,
            "environment": {
                "python": platform.python_version(),
                "machine": platform.machine(),
            },
        }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        result = {
            "schema": "frontiermath-hadamard-id3-profile-model-check-v1",
            "status": "error",
            "error": str(error),
            "checker_sha256": sha256_file(Path(__file__).resolve()),
            "runtime_seconds": time.perf_counter() - started,
        }

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    if result["status"] == "pass" and args.witness_output is not None:
        witness = result["witness"]
        assert isinstance(witness, dict)
        args.witness_output.parent.mkdir(parents=True, exist_ok=True)
        args.witness_output.write_text(
            json.dumps(
                {
                    "schema": "frontiermath-hadamard-id3-compression-v1",
                    "family_id": 3,
                    "source": "proof-producing profile-cell SAT model",
                    "cell_id": result["cell_id"],
                    "refined_ledger_sha256": result[
                        "refined_ledger_sha256"
                    ],
                    "witness": {
                        "a_tilde": witness["a_tilde"],
                        "b_tilde": witness["b_tilde"],
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    print(rendered, end="")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
