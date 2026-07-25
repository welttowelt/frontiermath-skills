#!/usr/bin/env python3
"""Check the endpoint obstruction in one 5/3 deletion topology.

The topology is the calibrated 2x3 graph with the top-right horizontal edge
deleted. Assume E=(2,2) has just become known. The augmented cycle map on the
remaining vertices A,B,C,D,F has the exact symbolic row pattern checked below.

This proves a conditional pruning lemma: after E is known, forcing C next
requires the two labels incident to F to coincide, which then strands F.
Forcing F next symmetrically strands C. It does not rule out every possible
first forcing step for the topology.
"""

from __future__ import annotations

import json


SymbolicLinear = tuple[int, ...]
ZERO: SymbolicLinear = (0,) * 8
SYMBOLS = ("p", "q", "r", "s", "a", "b", "c", "d")


def add(left: SymbolicLinear, right: SymbolicLinear) -> SymbolicLinear:
    return tuple(a + b for a, b in zip(left, right))


def scale(value: int, form: SymbolicLinear) -> SymbolicLinear:
    return tuple(value * coefficient for coefficient in form)


def symbol(name: str) -> SymbolicLinear:
    return tuple(int(candidate == name) for candidate in SYMBOLS)


def matrix_product_entry(
    incidence_row: tuple[int, ...],
    tau_by_edge: tuple[SymbolicLinear, ...],
    cycle_column: tuple[int, ...],
) -> SymbolicLinear:
    result = ZERO
    for incidence, tau, cycle in zip(
        incidence_row,
        tau_by_edge,
        cycle_column,
    ):
        result = add(result, scale(incidence * cycle, tau))
    return result


def main() -> int:
    # Edge order:
    # AD, BE, CF, AB, DE, EF, OA, OB, OC, OD.
    incidence = (
        (1, 0, 0, 1, 0, 0, -1, 0, 0, 0),   # A
        (0, 1, 0, -1, 0, 0, 0, -1, 0, 0),   # B
        (0, 0, 1, 0, 0, 0, 0, 0, -1, 0),    # C
        (-1, 0, 0, 0, 1, 0, 0, 0, 0, -1),   # D
        (0, 0, -1, 0, 0, -1, 0, 0, 0, 0),   # F
    )
    cycle_basis = (
        (1, -1, 0, -1, 1, 0, 0, 0, 0, 0),
        (0, 1, 0, 1, 0, 0, 1, 0, 0, 0),
        (0, 1, 0, 0, 0, 0, 0, 1, 0, 0),
        (0, 0, 1, 0, 0, -1, 0, 0, 1, 0),
        (-1, 1, 0, 1, 0, 0, 0, 0, 0, 1),
    )
    for vertex_row in incidence:
        for cycle_column in cycle_basis:
            assert sum(
                incidence_value * cycle_value
                for incidence_value, cycle_value in zip(
                    vertex_row,
                    cycle_column,
                )
            ) == 0

    tau_by_edge = tuple(
        symbol(name)
        for name in ("p", "p", "p", "q", "r", "s", "a", "b", "c", "d")
    )
    cycle_map = tuple(
        tuple(
            matrix_product_entry(row, tau_by_edge, column)
            for column in cycle_basis
        )
        for row in incidence
    )
    expected_c = (ZERO, ZERO, ZERO, add(symbol("p"), scale(-1, symbol("c"))), ZERO)
    expected_f = (ZERO, ZERO, ZERO, add(symbol("s"), scale(-1, symbol("p"))), ZERO)
    assert cycle_map[2] == expected_c
    assert cycle_map[4] == expected_f

    print(
        json.dumps(
            {
                "status": "exact-structural-check-pass",
                "state": "E=(2,2) known; A,B,C,D,F unknown",
                "cycle_map_row_C": ["0", "0", "0", "p-c", "0"],
                "cycle_map_row_F": ["0", "0", "0", "s-p", "0"],
                "deduction": (
                    "forcing C requires s=p and strands F; "
                    "forcing F requires c=p and strands C"
                ),
                "scope": "conditional forcing order only",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
