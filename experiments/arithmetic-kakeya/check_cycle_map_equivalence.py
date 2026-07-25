#!/usr/bin/env python3
"""Cross-check dense forcing closure with the augmented-cycle-map formula."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from fractions import Fraction
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = (
    ROOT
    / "skills"
    / "verify-frontiermath-candidate"
    / "scripts"
    / "verify_arithmetic_kakeya.py"
)
SEARCH_PATH = ROOT / "experiments" / "arithmetic-kakeya" / "search_small.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VERIFIER = load("cycle_map_verifier", VERIFIER_PATH)
SEARCH = load("cycle_map_search", SEARCH_PATH)
Vertex = tuple[int, ...]


def rref(
    rows: Sequence[Sequence[Fraction]],
) -> tuple[list[list[Fraction]], list[int]]:
    matrix = [
        [Fraction(value) for value in row]
        for row in rows
        if any(value != 0 for value in row)
    ]
    if not matrix:
        return [], []
    width = len(matrix[0])
    active = 0
    pivots: list[int] = []
    for column in range(width):
        selected = next(
            (
                index
                for index in range(active, len(matrix))
                if matrix[index][column] != 0
            ),
            None,
        )
        if selected is None:
            continue
        matrix[active], matrix[selected] = matrix[selected], matrix[active]
        pivot = matrix[active][column]
        matrix[active] = [value / pivot for value in matrix[active]]
        for index in range(len(matrix)):
            if index == active or matrix[index][column] == 0:
                continue
            factor = matrix[index][column]
            matrix[index] = [
                value - factor * basis
                for value, basis in zip(matrix[index], matrix[active])
            ]
        pivots.append(column)
        active += 1
        if active == len(matrix):
            break
    return matrix[:active], pivots


def nullspace(rows: Sequence[Sequence[Fraction]], width: int) -> list[list[Fraction]]:
    reduced, pivots = rref(rows)
    free = [column for column in range(width) if column not in pivots]
    basis: list[list[Fraction]] = []
    for free_column in free:
        vector = [Fraction(0) for _ in range(width)]
        vector[free_column] = Fraction(1)
        for row, pivot in zip(reduced, pivots):
            vector[pivot] = -row[free_column]
        basis.append(vector)
    return basis


def in_row_span(
    target: Sequence[Fraction],
    rows: Sequence[Sequence[Fraction]],
) -> bool:
    reduced, pivots = rref(rows)
    residual = [Fraction(value) for value in target]
    for row, pivot in zip(reduced, pivots):
        factor = residual[pivot]
        if factor == 0:
            continue
        residual = [
            value - factor * basis
            for value, basis in zip(residual, row)
        ]
    return not any(residual)


def incidence_generators(candidate, vertices: Sequence[Vertex]):
    index = {vertex: position for position, vertex in enumerate(vertices)}
    result: list[tuple[list[int], Fraction]] = []
    for left, right, label in VERIFIER.graph_edges(candidate):
        incidence = [0] * len(vertices)
        incidence[index[left]] = 1
        incidence[index[right]] = -1
        result.append(
            (
                incidence,
                Fraction(label[0] - label[1], label[0] + label[1]),
            )
        )
    for row in candidate.singleton_rows:
        vertex, label = next(iter(row.items()))
        incidence = [0] * len(vertices)
        incidence[index[vertex]] = 1
        result.append(
            (
                incidence,
                Fraction(label[0] - label[1], label[0] + label[1]),
            )
        )
    return result


def cycle_map_closure(candidate) -> tuple[set[Vertex], list[list[Vertex]]]:
    vertices = VERIFIER.candidate_vertices(candidate.dimensions)
    known = set(candidate.initial_known)
    generators = incidence_generators(candidate, vertices)
    rounds: list[list[Vertex]] = []
    while len(known) < len(vertices):
        unknown = [vertex for vertex in vertices if vertex not in known]
        unknown_indices = [vertices.index(vertex) for vertex in unknown]
        incidences = [
            [incidence[index] for index in unknown_indices]
            for incidence, _ in generators
        ]
        generator_count = len(incidences)
        transpose = [
            [incidences[row][column] for row in range(generator_count)]
            for column in range(len(unknown))
        ]
        cycles = nullspace(transpose, generator_count)
        image_rows: list[list[Fraction]] = []
        for cycle in cycles:
            image_rows.append(
                [
                    sum(
                        incidences[row][column]
                        * generators[row][1]
                        * cycle[row]
                        for row in range(generator_count)
                    )
                    for column in range(len(unknown))
                ]
            )
        forceable: list[Vertex] = []
        for index, vertex in enumerate(unknown):
            target = [Fraction(0) for _ in unknown]
            target[index] = Fraction(1)
            if in_row_span(target, image_rows):
                forceable.append(vertex)
        if not forceable:
            break
        known.update(forceable)
        rounds.append(forceable)
    return known, rounds


def dense_closure(candidate) -> tuple[set[Vertex], list[list[Vertex]]]:
    vertices = VERIFIER.candidate_vertices(candidate.dimensions)
    edges = VERIFIER.graph_edges(candidate)
    rows = VERIFIER.generator_rows(candidate, vertices, edges)
    return VERIFIER.forcing_closure(vertices, rows, candidate.initial_known)


def random_candidate(rng: random.Random):
    shape = rng.choice(((2, 2), (2, 3), (3, 2), (2, 2, 2)))
    known_count = rng.randrange(min(3, SEARCH.math.prod(shape)))
    space = SEARCH.SearchSpace(
        shape,
        SEARCH.slope_pool(3),
        Fraction(199, 100),
        1_000_003,
        known_count=known_count,
    )
    return space.exact_candidate(space.random_genome(rng))


def normalized_rounds(rounds: Sequence[Sequence[Vertex]]) -> list[list[list[int]]]:
    return [
        [list(vertex) for vertex in sorted(round_vertices)]
        for round_vertices in rounds
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260725)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")

    warmup = VERIFIER.parse_candidate_bytes(
        (
            ROOT
            / "skills"
            / "verify-frontiermath-candidate"
            / "tests"
            / "fixtures"
            / "arithmetic-kakeya-katz-tao-7-over-4.txt"
        ).read_bytes()
    )
    candidates = [warmup]
    rng = random.Random(args.seed)
    candidates.extend(random_candidate(rng) for _ in range(args.trials))

    failures: list[dict[str, object]] = []
    for index, candidate in enumerate(candidates):
        dense_known, dense_rounds = dense_closure(candidate)
        cycle_known, cycle_rounds = cycle_map_closure(candidate)
        if dense_known != cycle_known or normalized_rounds(
            dense_rounds
        ) != normalized_rounds(cycle_rounds):
            failures.append(
                {
                    "candidate_index": index,
                    "dense_known": [list(vertex) for vertex in sorted(dense_known)],
                    "cycle_known": [list(vertex) for vertex in sorted(cycle_known)],
                    "dense_rounds": normalized_rounds(dense_rounds),
                    "cycle_rounds": normalized_rounds(cycle_rounds),
                }
            )
            break

    packet = {
        "status": "cycle-map-equivalence-pass" if not failures else "mismatch",
        "formula": "image(H^T D_tau restricted to kernel(H^T))",
        "seed": args.seed,
        "random_trials": args.trials,
        "warmup_included": True,
        "failures": failures,
        "claim_boundary": (
            "bounded implementation cross-check; the algebraic equivalence "
            "is justified separately and this does not establish Epoch parity"
        ),
    }
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
