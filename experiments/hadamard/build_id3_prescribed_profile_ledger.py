#!/usr/bin/env python3
"""Classify all 95 id3 square multisets under prescribed q^2 margins.

Every feasible id3 length-9 compressed pair has 18 entries from the exact
value set and combined squared norm 594.  There are exactly 95 possible square
multisets.  For each multiset this script asks whether there is:

* a pair of length-9 compressed vectors with row sums 1;
* combined PAF -74 at every nonzero shift; and
* explicit 9x13 id3 sign tables whose column sums equal the prescribed
  length-37 q^2-compression.

The output is a finite screening ledger.  CP-SAT INFEASIBLE records are not
replayable proof certificates; feasible records carry directly checked
witnesses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from collections import Counter
from pathlib import Path

import ortools
from ortools.sat.python import cp_model


P = 37
Q = 3
K37 = (1, 10, 26)
TARGET_NORM = 594
TARGET_PAF = -74
SLOTS = 18
VALUES = (
    -23,
    -19,
    -17,
    -13,
    -11,
    -7,
    -5,
    -1,
    1,
    5,
    7,
    11,
    13,
    17,
    19,
    23,
)
SQUARES = tuple(sorted({value * value for value in VALUES}))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    degrees = []
    for orbit in k37_orbits()[1:]:
        target = sign * Q * legendre_symbol(orbit[0])
        degrees.append((9 + target) // 2)
    return degrees


def square_multisets() -> list[dict[int, int]]:
    results: list[dict[int, int]] = []

    def recurse(
        index: int,
        remaining_slots: int,
        remaining_sum: int,
        counts: list[int],
    ) -> None:
        if index == len(SQUARES):
            if remaining_slots == 0 and remaining_sum == 0:
                results.append(
                    {
                        square: count
                        for square, count in zip(SQUARES, counts)
                        if count
                    }
                )
            return
        square = SQUARES[index]
        for count in range(remaining_slots + 1):
            cost = count * square
            if cost > remaining_sum:
                break
            recurse(
                index + 1,
                remaining_slots - count,
                remaining_sum - cost,
                counts + [count],
            )

    recurse(0, SLOTS, TARGET_NORM, [])
    return results


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[(index + shift) % len(sequence)]
        for index in range(len(sequence))
    )


def value_table() -> list[list[int]]:
    rows = []
    for value in VALUES:
        singleton = 1 if value % 3 == 1 else -1
        degree_numerator = (value - singleton) // 3 + 12
        if degree_numerator % 2:
            raise ValueError("id3 value has a nonintegral row degree")
        degree = degree_numerator // 2
        if not 0 <= degree <= 12:
            raise ValueError("id3 value has an invalid row degree")
        rows.append([value, value * value, singleton, degree])
    return rows


def solve_multiset(
    multiset_id: int,
    square_counts: dict[int, int],
    max_seconds: float,
    workers: int,
    seed: int,
) -> dict[str, object]:
    model = cp_model.CpModel()
    value_domain = cp_model.Domain.FromValues(VALUES)
    table = value_table()

    sequences = []
    squares = []
    singletons = []
    degrees = []
    margins = []
    column_degree_sets = (
        prescribed_nonzero_column_degrees(1),
        prescribed_nonzero_column_degrees(-1),
    )
    for sequence_index, name in enumerate(("a", "b")):
        values = [
            model.NewIntVarFromDomain(value_domain, f"{name}_{index}")
            for index in range(9)
        ]
        sequence_squares = [
            model.NewIntVar(min(SQUARES), max(SQUARES), f"{name}_sq_{index}")
            for index in range(9)
        ]
        sequence_singletons = [
            model.NewIntVar(-1, 1, f"{name}_eps_{index}")
            for index in range(9)
        ]
        sequence_degrees = [
            model.NewIntVar(0, 12, f"{name}_deg_{index}")
            for index in range(9)
        ]
        for index in range(9):
            model.AddAllowedAssignments(
                [
                    values[index],
                    sequence_squares[index],
                    sequence_singletons[index],
                    sequence_degrees[index],
                ],
                table,
            )
        model.Add(sum(values) == 1)
        model.Add(sum(sequence_singletons) == 1)

        matrix = [
            [
                model.NewBoolVar(f"{name}_margin_{row}_{column}")
                for column in range(12)
            ]
            for row in range(9)
        ]
        for row in range(9):
            model.Add(sum(matrix[row]) == sequence_degrees[row])
        for column, target_degree in enumerate(
            column_degree_sets[sequence_index]
        ):
            model.Add(
                sum(matrix[row][column] for row in range(9))
                == target_degree
            )

        sequences.append(values)
        squares.extend(sequence_squares)
        singletons.append(sequence_singletons)
        degrees.append(sequence_degrees)
        margins.append(matrix)

    for square in SQUARES:
        indicators = []
        for position, square_variable in enumerate(squares):
            indicator = model.NewBoolVar(
                f"is_square_{square}_{position}"
            )
            model.Add(square_variable == square).OnlyEnforceIf(indicator)
            model.Add(square_variable != square).OnlyEnforceIf(
                indicator.Not()
            )
            indicators.append(indicator)
        model.Add(sum(indicators) == square_counts.get(square, 0))

    for shift in range(1, 5):
        products = []
        for sequence_index, sequence in enumerate(sequences):
            for index in range(9):
                product = model.NewIntVar(
                    -(23 * 23),
                    23 * 23,
                    f"p_{sequence_index}_{shift}_{index}",
                )
                model.AddMultiplicationEquality(
                    product,
                    [sequence[index], sequence[(index + shift) % 9]],
                )
                products.append(product)
        model.Add(sum(products) == TARGET_PAF)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed + multiset_id
    started = time.perf_counter()
    status = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status_name = solver.StatusName(status)
    result: dict[str, object] = {
        "id": multiset_id,
        "square_counts": {
            str(square): count
            for square, count in sorted(square_counts.items())
        },
        "status": status_name,
        "wall_seconds": elapsed,
        "branches": solver.NumBranches(),
        "conflicts": solver.NumConflicts(),
    }
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        a = [solver.Value(variable) for variable in sequences[0]]
        b = [solver.Value(variable) for variable in sequences[1]]
        actual_counts = Counter(value * value for value in a + b)
        paf_profile = [
            periodic_autocorrelation(a, shift)
            + periodic_autocorrelation(b, shift)
            for shift in range(1, 9)
        ]
        margin_witnesses = [
            [
                [
                    solver.Value(margins[sequence][row][column])
                    for column in range(12)
                ]
                for row in range(9)
            ]
            for sequence in range(2)
        ]
        recomputed_row_degrees = [
            [sum(row) for row in margin] for margin in margin_witnesses
        ]
        recomputed_column_degrees = [
            [
                sum(margin[row][column] for row in range(9))
                for column in range(12)
            ]
            for margin in margin_witnesses
        ]
        valid = (
            sum(a) == 1
            and sum(b) == 1
            and paf_profile == [TARGET_PAF] * 8
            and actual_counts == Counter(square_counts)
            and recomputed_row_degrees
            == [
                [solver.Value(variable) for variable in degrees[0]],
                [solver.Value(variable) for variable in degrees[1]],
            ]
            and recomputed_column_degrees
            == [list(column_degree_sets[0]), list(column_degree_sets[1])]
        )
        if not valid:
            raise ValueError(f"multiset {multiset_id} witness failed checks")
        result.update(
            {
                "feasible": True,
                "a_tilde": a,
                "b_tilde": b,
                "combined_paf": paf_profile,
                "a_margin_9_by_12": margin_witnesses[0],
                "b_margin_9_by_12": margin_witnesses[1],
            }
        )
    elif status == cp_model.INFEASIBLE:
        result.update(
            {
                "feasible": False,
                "replayable_unsat_certificate": False,
            }
        )
    else:
        result["feasible"] = None
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds-per-multiset", type=float, default=2.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    multisets = square_multisets()
    if len(multisets) != 95:
        raise ValueError(f"expected 95 square multisets, found {len(multisets)}")
    started = time.perf_counter()
    records = []
    for multiset_id, counts in enumerate(multisets):
        record = solve_multiset(
            multiset_id,
            counts,
            args.max_seconds_per_multiset,
            args.workers,
            args.seed,
        )
        records.append(record)
        print(
            f"{multiset_id:02d}/94 {record['status']:<10} "
            f"{record['wall_seconds']:.3f}s",
            flush=True,
        )

    status_counts = Counter(record["status"] for record in records)
    result = {
        "schema": "frontiermath-hadamard-id3-prescribed-profile-ledger-v1",
        "status": "complete" if "UNKNOWN" not in status_counts else "bounded",
        "family_id": 3,
        "square_multisets_total": len(multisets),
        "status_counts": dict(sorted(status_counts.items())),
        "feasible_multiset_ids": [
            record["id"] for record in records if record.get("feasible") is True
        ],
        "unknown_multiset_ids": [
            record["id"] for record in records if record.get("feasible") is None
        ],
        "scope": (
            "length-9 PAF feasibility plus explicit prescribed q^2 margins; "
            "full LP(333) PAF equations are unchecked"
        ),
        "claim_limit": (
            "INFEASIBLE entries are CP-SAT decisions without replayable "
            "proofs; feasible entries carry exact checked witnesses"
        ),
        "solver": {
            "name": "OR-Tools CP-SAT",
            "version": ortools.__version__,
            "max_seconds_per_multiset": args.max_seconds_per_multiset,
            "workers": args.workers,
            "seed_base": args.seed,
        },
        "environment": {
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "runtime_seconds": time.perf_counter() - started,
        "generator_sha256": sha256_file(Path(__file__).resolve()),
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: result[key] for key in (
        "status",
        "square_multisets_total",
        "status_counts",
        "feasible_multiset_ids",
        "unknown_multiset_ids",
        "runtime_seconds",
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
