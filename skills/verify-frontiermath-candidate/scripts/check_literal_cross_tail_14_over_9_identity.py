#!/usr/bin/env python3
"""Independently check the public-operation cross-tail diagnostic.

This script deliberately does not import the Arithmetic Kakeya row reducer.
It hard-codes integer generator identities for a score-14/9 serialization
under the literal prefix-only conditions in public forcing operation 1.
The same serialization fails the intended equal-suffix graph semantics, so
this is a prompt/verifier-gap diagnostic rather than a claimed new bound.
"""

from __future__ import annotations

import json
from fractions import Fraction
from itertools import product


Pair = tuple[int, int]
Vertex = tuple[int, int]
VERTICES = tuple(product(range(1, 4), repeat=2))
INDEX = {vertex: index for index, vertex in enumerate(VERTICES)}
WIDTH = 2 * len(VERTICES)


def supported(values: dict[Vertex, Pair]) -> tuple[int, ...]:
    row = [0] * WIDTH
    for vertex, pair in values.items():
        offset = 2 * INDEX[vertex]
        row[offset] = pair[0]
        row[offset + 1] = pair[1]
    return tuple(row)


def edge(left: Vertex, right: Vertex, label: Pair) -> tuple[int, ...]:
    return supported(
        {
            left: label,
            right: (-label[0], -label[1]),
        }
    )


GENERATORS: dict[str, tuple[int, ...]] = {}
for left_tail in range(1, 4):
    for right_tail in range(1, 4):
        GENERATORS[f"A{left_tail}{right_tail}"] = edge(
            (1, left_tail),
            (2, right_tail),
            (1, 1),
        )
        GENERATORS[f"B{left_tail}{right_tail}"] = edge(
            (2, left_tail),
            (3, right_tail),
            (0, 1),
        )
GENERATORS.update(
    {
        "C": edge((1, 1), (1, 2), (1, 0)),
        "D": edge((3, 1), (3, 2), (1, 0)),
        "R1": supported({(1, 1): (1, 0)}),
        "R2": supported({(1, 3): (0, 1)}),
        "R3": supported({(1, 3): (1, 1)}),
        "R4": supported({(3, 1): (0, 1)}),
        "R5": supported({(3, 1): (1, 0)}),
        "R6": supported({(3, 3): (1, 0)}),
    }
)


IDENTITIES: dict[Vertex, dict[str, int]] = {
    (1, 1): {"A11": -1, "A31": 1, "R1": 2, "R3": -1},
    (1, 2): {"A21": -1, "A31": 1, "C": -2, "R1": 2, "R3": -1},
    (1, 3): {"R2": -2, "R3": 1},
    (2, 1): {"A31": -1, "B11": -2, "R3": 1, "R4": -2},
    (2, 2): {
        "A11": 1,
        "A12": -1,
        "A31": -1,
        "B21": -2,
        "R3": 1,
        "R4": -2,
    },
    (2, 3): {
        "A11": 1,
        "A13": -1,
        "A31": -1,
        "B31": -2,
        "R3": 1,
        "R4": -2,
    },
    (3, 1): {"R4": -1, "R5": 1},
    (3, 2): {"B11": -1, "B12": 1, "D": -1, "R4": -1, "R5": 1},
    (3, 3): {"B11": -1, "B13": 1, "R4": -1, "R6": 1},
}


def combine(coefficients: dict[str, int]) -> tuple[int, ...]:
    return tuple(
        sum(
            coefficient * GENERATORS[name][coordinate]
            for name, coefficient in coefficients.items()
        )
        for coordinate in range(WIDTH)
    )


def target(vertex: Vertex) -> tuple[int, ...]:
    return supported({vertex: (1, -1)})


def main() -> int:
    identity_checks = {
        str(vertex): combine(coefficients) == target(vertex)
        for vertex, coefficients in IDENTITIES.items()
    }
    parameters = {"m": 8, "r": 6, "n": 9, "t": 0}
    score = Fraction(
        parameters["m"] + parameters["r"],
        parameters["n"] - parameters["t"],
    )
    checks = {
        "all-nine-integer-identities": all(identity_checks.values()),
        "score-is-14-over-9": score == Fraction(14, 9),
        "score-meets-public-full-threshold": score <= Fraction(67, 40),
        "generator-count-is-26": len(GENERATORS) == 26,
    }
    packet = {
        "status": (
            "literal-operation-identity-pass"
            if all(checks.values())
            else "literal-operation-identity-fail"
        ),
        "interpretation": (
            "arbitrary suffix pairs permitted by the literal prefix-only "
            "conditions in public forcing operation 1"
        ),
        "claim_boundary": (
            "diagnostic only; the candidate fails intended equal-suffix "
            "graph semantics"
        ),
        "parameters": parameters,
        "score": f"{score.numerator}/{score.denominator}",
        "checks": checks,
        "identity_checks": identity_checks,
    }
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
