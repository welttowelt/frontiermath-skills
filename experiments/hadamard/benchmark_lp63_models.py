#!/usr/bin/env python3
"""Benchmark pairwise-XOR versus CRT column-type models on prescribed LP(63)."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import ortools
from ortools.sat.python import cp_model

from py39_compat import int_bit_count


LENGTH = 63
ROWS = 9
COLUMNS = 7
TARGET_A = (1, 3, 3, -3, 3, -3, -3)
TARGET_B = (1, -3, -3, 3, -3, 3, 3)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[(index + shift) % len(sequence)]
        for index in range(len(sequence))
    )


def verify_pair(a: list[int], b: list[int]) -> bool:
    return (
        len(a) == LENGTH
        and len(b) == LENGTH
        and all(value in {-1, 1} for value in a + b)
        and all(
            periodic_autocorrelation(a, shift)
            + periodic_autocorrelation(b, shift)
            == -2
            for shift in range(1, LENGTH)
        )
        and [
            sum(a[index] for index in range(LENGTH) if index % COLUMNS == column)
            for column in range(COLUMNS)
        ]
        == list(TARGET_A)
        and [
            sum(b[index] for index in range(LENGTH) if index % COLUMNS == column)
            for column in range(COLUMNS)
        ]
        == list(TARGET_B)
    )


def solve_baseline(
    max_seconds: float, workers: int, seed: int
) -> dict[str, object]:
    model = cp_model.CpModel()
    za = [model.NewBoolVar(f"za_{index}") for index in range(LENGTH)]
    zb = [model.NewBoolVar(f"zb_{index}") for index in range(LENGTH)]
    for variables, targets in ((za, TARGET_A), (zb, TARGET_B)):
        for column, target in enumerate(targets):
            positions = [
                index for index in range(LENGTH) if index % COLUMNS == column
            ]
            model.Add(
                sum(variables[index] for index in positions)
                == (ROWS - target) // 2
            )

    xor_variables = []
    for shift in range(1, (LENGTH + 1) // 2):
        shift_xors = []
        for name, variables in (("a", za), ("b", zb)):
            for index in range(LENGTH):
                other = (index + shift) % LENGTH
                xor = model.NewBoolVar(f"xor_{name}_{shift}_{index}")
                model.Add(xor <= variables[index] + variables[other])
                model.Add(xor >= variables[index] - variables[other])
                model.Add(xor >= variables[other] - variables[index])
                model.Add(
                    xor <= 2 - variables[index] - variables[other]
                )
                shift_xors.append(xor)
                xor_variables.append(xor)
        # Combined PAF = 126 - 2 * (# unequal directed pairs) = -2.
        model.Add(sum(shift_xors) == 64)

    proto = model.Proto()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    started = time.perf_counter()
    status = solver.Solve(model)
    elapsed = time.perf_counter() - started
    result: dict[str, object] = {
        "model": "pairwise-xor",
        "status": solver.StatusName(status),
        "primary_variables": 2 * LENGTH,
        "auxiliary_xor_variables": len(xor_variables),
        "proto_variables": len(proto.variables),
        "proto_constraints": len(proto.constraints),
        "wall_seconds": elapsed,
        "branches": solver.NumBranches(),
        "conflicts": solver.NumConflicts(),
    }
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        a = [1 - 2 * solver.Value(variable) for variable in za]
        b = [1 - 2 * solver.Value(variable) for variable in zb]
        result.update(
            {
                "sat": True,
                "verified_legendre_pair": verify_pair(a, b),
                "a_sequence": a,
                "b_sequence": b,
            }
        )
    elif status == cp_model.INFEASIBLE:
        result["sat"] = False
    else:
        result["sat"] = None
    return result


def patterns_with_sum(target: int) -> list[tuple[int, ...]]:
    return [
        tuple(
            -1 if (mask >> row) & 1 else 1 for row in range(ROWS)
        )
        for mask in range(1 << ROWS)
        if ROWS - 2 * int_bit_count(mask) == target
    ]


def shifted_inner_product(
    left: tuple[int, ...], right: tuple[int, ...], shift: int
) -> int:
    return sum(
        left[row] * right[(row + shift) % ROWS]
        for row in range(ROWS)
    )


def solve_block(
    max_seconds: float, workers: int, seed: int
) -> dict[str, object]:
    model = cp_model.CpModel()
    pattern_cache = {
        target: patterns_with_sum(target)
        for target in {-3, 1, 3}
    }
    variables = []
    targets_by_sequence = (TARGET_A, TARGET_B)
    for sequence_index, targets in enumerate(targets_by_sequence):
        sequence_variables = []
        for column, target in enumerate(targets):
            domain_size = len(pattern_cache[target])
            sequence_variables.append(
                model.NewIntVar(
                    0,
                    domain_size - 1,
                    f"type_{sequence_index}_{column}",
                )
            )
        variables.append(sequence_variables)

    contribution_variables = []
    table_entries = 0
    for shift in range(1, (LENGTH + 1) // 2):
        row_shift = shift % ROWS
        column_shift = shift % COLUMNS
        contributions = []
        for sequence_index, targets in enumerate(targets_by_sequence):
            for column in range(COLUMNS):
                other_column = (column + column_shift) % COLUMNS
                left_patterns = pattern_cache[targets[column]]
                right_patterns = pattern_cache[targets[other_column]]
                pair_index = model.NewIntVar(
                    0,
                    len(left_patterns) * len(right_patterns) - 1,
                    f"pair_{shift}_{sequence_index}_{column}",
                )
                model.Add(
                    pair_index
                    == len(right_patterns)
                    * variables[sequence_index][column]
                    + variables[sequence_index][other_column]
                )
                table = [
                    shifted_inner_product(left, right, row_shift)
                    for left in left_patterns
                    for right in right_patterns
                ]
                contribution = model.NewIntVar(
                    -ROWS,
                    ROWS,
                    f"cc_{shift}_{sequence_index}_{column}",
                )
                model.AddElement(pair_index, table, contribution)
                contributions.append(contribution)
                contribution_variables.append(contribution)
                table_entries += len(table)
        model.Add(sum(contributions) == -2)

    proto = model.Proto()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed
    started = time.perf_counter()
    status = solver.Solve(model)
    elapsed = time.perf_counter() - started
    result: dict[str, object] = {
        "model": "crt-column-types",
        "status": solver.StatusName(status),
        "primary_type_variables": 2 * COLUMNS,
        "contribution_variables": len(contribution_variables),
        "element_table_entries": table_entries,
        "pattern_domain_sizes": {
            str(target): len(patterns)
            for target, patterns in sorted(pattern_cache.items())
        },
        "proto_variables": len(proto.variables),
        "proto_constraints": len(proto.constraints),
        "wall_seconds": elapsed,
        "branches": solver.NumBranches(),
        "conflicts": solver.NumConflicts(),
    }
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sequences = []
        for sequence_index, targets in enumerate(targets_by_sequence):
            grid = [[0] * COLUMNS for _ in range(ROWS)]
            for column, target in enumerate(targets):
                pattern = pattern_cache[target][
                    solver.Value(variables[sequence_index][column])
                ]
                for row in range(ROWS):
                    grid[row][column] = pattern[row]
            sequence = [
                grid[index % ROWS][index % COLUMNS]
                for index in range(LENGTH)
            ]
            sequences.append(sequence)
        a, b = sequences
        result.update(
            {
                "sat": True,
                "verified_legendre_pair": verify_pair(a, b),
                "a_sequence": a,
                "b_sequence": b,
            }
        )
    elif status == cp_model.INFEASIBLE:
        result["sat"] = False
    else:
        result["sat"] = None
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("published_fixture", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    fixture = json.loads(args.published_fixture.read_text(encoding="utf-8"))
    if not verify_pair(fixture["a_sequence"], fixture["b_sequence"]):
        raise ValueError("published LP63 fixture failed the benchmark verifier")

    baseline = solve_baseline(args.max_seconds, args.workers, args.seed)
    block = solve_block(args.max_seconds, args.workers, args.seed)
    if baseline.get("sat") is True and not baseline["verified_legendre_pair"]:
        raise ValueError("baseline model emitted an invalid pair")
    if block.get("sat") is True and not block["verified_legendre_pair"]:
        raise ValueError("block model emitted an invalid pair")

    speedup = None
    branch_reduction = None
    if baseline.get("sat") is True and block.get("sat") is True:
        speedup = baseline["wall_seconds"] / block["wall_seconds"]
        if block["branches"]:
            branch_reduction = baseline["branches"] / block["branches"]
    result = {
        "schema": "frontiermath-hadamard-lp63-model-benchmark-v1",
        "status": "measured",
        "fixture_sha256": sha256_file(args.published_fixture),
        "configuration": {
            "max_seconds_per_model": args.max_seconds,
            "workers": args.workers,
            "seed": args.seed,
        },
        "baseline": baseline,
        "block": block,
        "comparison": {
            "wall_speedup_baseline_over_block": speedup,
            "branch_reduction_baseline_over_block": branch_reduction,
            "significance_floor": 3.0,
            "gate_pass": bool(
                (speedup is not None and speedup >= 3.0)
                or (
                    branch_reduction is not None
                    and branch_reduction >= 3.0
                )
            ),
        },
        "claim_limit": (
            "LP63 formulation calibration only; transfer to id3 requires a "
            "separate measured implementation"
        ),
        "solver": {
            "name": "OR-Tools CP-SAT",
            "version": ortools.__version__,
        },
        "environment": {
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "benchmark_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
