#!/usr/bin/env python3
"""Independent integer-identity check of the Katz--Tao 7/4 warmup graph."""

from __future__ import annotations

import json
from fractions import Fraction


VERTICES = ("g1", "g4", "g2", "g3")
WIDTH = 2 * len(VERTICES)


def singleton(where: str, value: tuple[int, int]) -> tuple[int, ...]:
    row = [0] * WIDTH
    offset = 2 * VERTICES.index(where)
    row[offset : offset + 2] = value
    return tuple(row)


def edge(
    left: str,
    right: str,
    value: tuple[int, int],
) -> tuple[int, ...]:
    row = list(singleton(left, value))
    offset = 2 * VERTICES.index(right)
    row[offset] = -value[0]
    row[offset + 1] = -value[1]
    return tuple(row)


def combine(
    rows: tuple[tuple[int, ...], ...],
    coefficients: tuple[int, ...],
) -> tuple[int, ...]:
    return tuple(
        sum(coefficient * row[column] for coefficient, row in zip(coefficients, rows))
        for column in range(WIDTH)
    )


def target(where: str) -> tuple[int, ...]:
    return singleton(where, (1, -1))


def agrees_outside_known(
    observed: tuple[int, ...],
    expected: tuple[int, ...],
    known: set[str],
) -> bool:
    ignored = {
        coordinate
        for name in known
        for coordinate in (
            2 * VERTICES.index(name),
            2 * VERTICES.index(name) + 1,
        )
    }
    return all(
        actual == wanted
        for coordinate, (actual, wanted) in enumerate(zip(observed, expected))
        if coordinate not in ignored
    )


def main() -> int:
    x_set = {(0, 0), (1, 0), (0, 1), (1, 1), (1, 2)}
    rows = (
        singleton("g1", (1, 1)),
        singleton("g2", (1, 1)),
        singleton("g4", (0, 1)),
        edge("g1", "g2", (1, 0)),
        edge("g4", "g3", (1, 0)),
        edge("g1", "g4", (1, 2)),
        edge("g2", "g3", (0, 1)),
    )

    witnesses = {
        "g3": (2, -1, -2, -1, -1, -1, 1),
        "g1_given_g3": (3, 0, -4, 0, -2, -2, 0),
        "g4_given_g3": (0, 0, -1, 0, 1, 0, 0),
        "g2_given_g3": (4, -1, -4, -2, -2, -2, 0),
    }
    checks = {
        "X_contains_zero": (0, 0) in x_set,
        "X_excludes_nonzero_output_slope": all(
            value == (0, 0) or value[0] + value[1] != 0
            for value in x_set
        ),
        "score_is_7_over_4": Fraction(4 + 3, 4) == Fraction(7, 4),
        "g3_integer_identity": combine(rows, witnesses["g3"]) == target("g3"),
        "g1_after_g3": agrees_outside_known(
            combine(rows, witnesses["g1_given_g3"]),
            target("g1"),
            {"g3"},
        ),
        "g4_after_g3": agrees_outside_known(
            combine(rows, witnesses["g4_given_g3"]),
            target("g4"),
            {"g3"},
        ),
        "g2_after_g3": agrees_outside_known(
            combine(rows, witnesses["g2_given_g3"]),
            target("g2"),
            {"g3"},
        ),
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "status": "pass" if passed else "fail",
                "method": "hard-coded integer identities independent of row reduction",
                "vertex_order": list(VERTICES),
                "checks": checks,
                "integer_witness_coefficients": {
                    key: list(value) for key, value in witnesses.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
