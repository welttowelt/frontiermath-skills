#!/usr/bin/env python3
"""Decide the pure margin compatibility of two id3 compression axes.

For an id3-invariant sequence, arrange the signs as a 9 by 13 table: one
mod-37 zero column and twelve size-three K37-orbit columns.  A length-9
compression fixes the weighted row sums; a length-37 compression fixes the
ordinary column sums.  After the singleton signs are determined modulo three,
compatibility is exactly a bipartite degree-sequence problem.

This checker is dependency-free and does not impose the full PAF equations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


P = 37
Q = 3
K37 = (1, 10, 26)
EXPECTED_FAMILY_ID = 3


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


def prescribed_pair() -> tuple[list[int], list[int]]:
    a = [1] + [Q * legendre_symbol(index) for index in range(1, P)]
    b = [1] + [-value for value in a[1:]]
    return a, b


def origin_orientation(values: list[int]) -> int:
    """Global sign making the singleton at (mod9,mod37)=(0,0) equal +1."""

    if values[0] % 3 == 1:
        return 1
    if (-values[0]) % 3 == 1:
        return -1
    raise ValueError("origin row sum has no valid singleton sign modulo three")


def gale_ryser(row_degrees: list[int], column_degrees: list[int]) -> dict:
    rows = sorted(row_degrees, reverse=True)
    columns = sorted(column_degrees, reverse=True)
    checks = []
    for count in range(1, len(rows) + 1):
        left = sum(rows[:count])
        right = sum(min(count, degree) for degree in columns)
        checks.append({"k": count, "left": left, "right": right, "pass": left <= right})
    graphical = (
        sum(rows) == sum(columns)
        and all(record["pass"] for record in checks)
    )
    return {
        "row_sum": sum(rows),
        "column_sum": sum(columns),
        "inequalities": checks,
        "graphical": graphical,
    }


def construct_bipartite(
    row_degrees: list[int], column_degrees: list[int]
) -> list[list[int]]:
    """Bipartite Havel-Hakimi construction with exact post-verification."""

    matrix = [[0] * len(column_degrees) for _ in row_degrees]
    remaining_rows = [(degree, index) for index, degree in enumerate(row_degrees)]
    remaining_columns = list(column_degrees)
    while remaining_rows:
        remaining_rows.sort(reverse=True)
        degree, row_index = remaining_rows.pop(0)
        choices = sorted(
            range(len(remaining_columns)),
            key=lambda index: (remaining_columns[index], -index),
            reverse=True,
        )
        chosen = [index for index in choices if remaining_columns[index] > 0][
            :degree
        ]
        if len(chosen) != degree:
            raise ValueError("degree sequence construction became impossible")
        for column_index in chosen:
            matrix[row_index][column_index] = 1
            remaining_columns[column_index] -= 1
            if remaining_columns[column_index] < 0:
                raise ValueError("negative residual column degree")
    if any(remaining_columns):
        raise ValueError(f"unfilled column degrees: {remaining_columns}")
    if [sum(row) for row in matrix] != row_degrees:
        raise ValueError("constructed row degrees do not match")
    if [
        sum(matrix[row][column] for row in range(len(row_degrees)))
        for column in range(len(column_degrees))
    ] != column_degrees:
        raise ValueError("constructed column degrees do not match")
    return matrix


def analyze_sequence(
    name: str,
    length9_values: list[int],
    prescribed_values: list[int],
) -> dict:
    factor = origin_orientation(length9_values)
    row_sums = [factor * value for value in length9_values]
    column_targets = [factor * value for value in prescribed_values]

    singleton_signs = [
        1 if row_sum % 3 == 1 else -1 for row_sum in row_sums
    ]
    triple_signed_sums = [
        (row_sum - singleton) // 3
        for row_sum, singleton in zip(row_sums, singleton_signs)
    ]
    row_degrees = [
        (12 + signed_sum) // 2 for signed_sum in triple_signed_sums
    ]

    orbits = k37_orbits()
    if orbits[0] != [0] or len(orbits) != 13:
        raise ValueError("unexpected K37 orbit decomposition")
    orbit_targets = []
    for orbit in orbits:
        values = {column_targets[index] for index in orbit}
        if len(values) != 1:
            raise ValueError(
                f"prescribed compression is not K37-invariant on {orbit}"
            )
        orbit_targets.append(values.pop())

    singleton_column_target = orbit_targets[0]
    column_degrees = [
        (9 + target) // 2 for target in orbit_targets[1:]
    ]
    singleton_compatible = sum(singleton_signs) == singleton_column_target
    gale_ryser_result = gale_ryser(row_degrees, column_degrees)
    compatible = singleton_compatible and gale_ryser_result["graphical"]

    sign_matrix = None
    recomputed = None
    if compatible:
        incidence = construct_bipartite(row_degrees, column_degrees)
        sign_matrix = [
            [singleton_signs[row]]
            + [1 if entry else -1 for entry in incidence[row]]
            for row in range(9)
        ]
        recomputed_rows = [
            row[0] + 3 * sum(row[1:]) for row in sign_matrix
        ]
        recomputed_columns = [
            sum(sign_matrix[row][column] for row in range(9))
            for column in range(13)
        ]
        if recomputed_rows != row_sums or recomputed_columns != orbit_targets:
            raise ValueError("constructed sign matrix failed its margins")
        recomputed = {
            "weighted_row_sums": recomputed_rows,
            "orbit_column_sums": recomputed_columns,
        }

    return {
        "name": name,
        "global_sign_factor": factor,
        "oriented_length9_row_sums": row_sums,
        "oriented_length37_columns": column_targets,
        "k37_orbits": orbits,
        "orbit_column_targets": orbit_targets,
        "singleton_signs": singleton_signs,
        "singleton_column_target": singleton_column_target,
        "singleton_compatible": singleton_compatible,
        "triple_row_plus_degrees": row_degrees,
        "nonzero_orbit_column_plus_degrees": column_degrees,
        "gale_ryser": gale_ryser_result,
        "compatible": compatible,
        "sign_matrix_9_by_13": sign_matrix,
        "recomputed_margins": recomputed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("length9_witness", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    document = json.loads(args.length9_witness.read_text(encoding="utf-8"))
    if document.get("family_id") != EXPECTED_FAMILY_ID:
        raise ValueError("witness is not for id3")
    witness = document.get("witness")
    if not isinstance(witness, dict):
        raise ValueError("missing compressed witness")

    prescribed_a, prescribed_b = prescribed_pair()
    a_result = analyze_sequence(
        "a", list(witness["a_tilde"]), prescribed_a
    )
    b_result = analyze_sequence(
        "b", list(witness["b_tilde"]), prescribed_b
    )
    compatible = a_result["compatible"] and b_result["compatible"]
    result = {
        "schema": "frontiermath-hadamard-id3-double-margin-v1",
        "status": "compatible" if compatible else "incompatible",
        "family_id": EXPECTED_FAMILY_ID,
        "length9_witness_sha256": sha256_file(args.length9_witness),
        "scope": (
            "binary margin compatibility under id3 invariance; full PAF "
            "equations are unchecked"
        ),
        "a": a_result,
        "b": b_result,
        "checker_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if compatible else 1


if __name__ == "__main__":
    raise SystemExit(main())
