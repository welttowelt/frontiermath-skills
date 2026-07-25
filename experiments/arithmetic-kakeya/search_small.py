#!/usr/bin/env python3
"""Bounded modular search for small Arithmetic Kakeya product graphs.

This is a discovery program, not an independent verifier. Modular row spans are
used only as a fast search filter. Every survivor is rerun by the exact rational
shadow checker before it is reported as an exact candidate.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import math
import random
import sys
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = (
    ROOT
    / "skills"
    / "verify-frontiermath-candidate"
    / "scripts"
    / "verify_arithmetic_kakeya.py"
)


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_arithmetic_kakeya", VERIFIER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier from {VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = load_verifier()
Pair = tuple[int, int]
Vertex = tuple[int, ...]


@dataclass(frozen=True)
class Group:
    axis: int
    prefix: Vertex
    cost: int


@dataclass(frozen=True)
class Genome:
    labels: tuple[int, ...]  # -1 is the omitted/zero label
    measurements: tuple[int, ...]  # flattened vertex * slope index
    known: tuple[int, ...] = ()


@dataclass
class Evaluation:
    forced: int
    total: int
    cost: int
    denominator: int
    rank: int
    modular_rounds: list[list[int]]
    exact_status: str | None = None
    exact_result: dict[str, object] | None = None

    @property
    def forcing(self) -> bool:
        return self.forced == self.total

    @property
    def score(self) -> Fraction:
        return Fraction(self.cost, self.denominator)

    def fitness(self) -> tuple[int, int, int, int, int]:
        if self.forcing:
            return (
                2,
                -self.score.numerator * 1_000_000 // self.score.denominator,
                -self.cost,
                self.rank,
                0,
            )
        return (1, self.forced, self.rank, -self.cost, -self.denominator)


def normalize_pair(a: int, b: int) -> Pair:
    if a == 0 and b == 0:
        raise ValueError("zero has no projective slope")
    divisor = math.gcd(abs(a), abs(b))
    a //= divisor
    b //= divisor
    if a < 0 or (a == 0 and b < 0):
        a, b = -a, -b
    return a, b


def slope_pool(height: int) -> tuple[Pair, ...]:
    slopes = {
        normalize_pair(a, b)
        for a in range(-height, height + 1)
        for b in range(-height, height + 1)
        if (a, b) != (0, 0) and a + b != 0
    }
    return tuple(sorted(slopes))


def vertices(shape: Sequence[int]) -> tuple[Vertex, ...]:
    return tuple(
        itertools.product(*(range(1, dimension + 1) for dimension in shape))
    )


def groups(shape: Sequence[int]) -> tuple[Group, ...]:
    result: list[Group] = []
    for axis, dimension in enumerate(shape):
        cost = math.prod(shape[axis + 1 :])
        prefix_ranges = [
            range(1, shape[index] + 1)
            for index in range(axis)
        ] + [range(1, dimension)]
        for prefix in itertools.product(*prefix_ranges):
            result.append(Group(axis=axis, prefix=tuple(prefix), cost=cost))
    return tuple(result)


def row_rref_mod(
    rows: Sequence[Sequence[int]],
    prime: int,
) -> tuple[list[list[int]], list[int]]:
    matrix = [
        [value % prime for value in row]
        for row in rows
        if any(value % prime for value in row)
    ]
    if not matrix:
        return [], []
    width = len(matrix[0])
    pivot_row = 0
    pivots: list[int] = []
    for column in range(width):
        selected = next(
            (
                row_index
                for row_index in range(pivot_row, len(matrix))
                if matrix[row_index][column]
            ),
            None,
        )
        if selected is None:
            continue
        matrix[pivot_row], matrix[selected] = matrix[selected], matrix[pivot_row]
        inverse = pow(matrix[pivot_row][column], prime - 2, prime)
        matrix[pivot_row] = [
            value * inverse % prime for value in matrix[pivot_row]
        ]
        for row_index, row in enumerate(matrix):
            if row_index == pivot_row or row[column] == 0:
                continue
            factor = row[column]
            matrix[row_index] = [
                (value - factor * basis_value) % prime
                for value, basis_value in zip(row, matrix[pivot_row])
            ]
        pivots.append(column)
        pivot_row += 1
        if pivot_row == len(matrix):
            break
    return matrix[:pivot_row], pivots


def in_span_mod(
    target: Sequence[int],
    basis: Sequence[Sequence[int]],
    pivots: Sequence[int],
    prime: int,
) -> bool:
    residual = [value % prime for value in target]
    for row, pivot in zip(basis, pivots):
        factor = residual[pivot]
        if factor:
            residual = [
                (value - factor * basis_value) % prime
                for value, basis_value in zip(residual, row)
            ]
    return not any(residual)


class SearchSpace:
    def __init__(
        self,
        shape: tuple[int, ...],
        slopes: tuple[Pair, ...],
        threshold: Fraction,
        prime: int,
        known_count: int = 0,
        edge_semantics: str = "same-tail",
    ) -> None:
        self.shape = shape
        self.slopes = slopes
        self.threshold = threshold
        self.prime = prime
        if edge_semantics not in {"same-tail", "literal-cross-tail"}:
            raise ValueError(
                "edge_semantics must be 'same-tail' or 'literal-cross-tail'"
            )
        self.edge_semantics = edge_semantics
        self.vertices = vertices(shape)
        if not 0 <= known_count < len(self.vertices):
            raise ValueError(
                "known_count must be nonnegative and smaller than the vertex count"
            )
        self.known_count = known_count
        self.vertex_index = {
            item: index for index, item in enumerate(self.vertices)
        }
        self.groups = groups(shape)
        denominator = len(self.vertices) - known_count
        self.budget = threshold.numerator * denominator // threshold.denominator
        self.measurement_count = len(self.vertices) * len(slopes)
        self.cache: dict[Genome, Evaluation] = {}

    def edge_rows(self, genome: Genome) -> tuple[list[int], ...]:
        rows: list[list[int]] = []
        for group, label_index in zip(self.groups, genome.labels):
            if label_index < 0:
                continue
            label = self.slopes[label_index]
            tail_ranges = [
                range(1, dimension + 1)
                for dimension in self.shape[group.axis + 1 :]
            ]
            tails: Iterable[tuple[int, ...]] = (
                itertools.product(*tail_ranges) if tail_ranges else [()]
            )
            cached_tails = tuple(tails)
            if self.edge_semantics == "same-tail":
                tail_pairs = ((tail, tail) for tail in cached_tails)
            else:
                tail_pairs = itertools.product(cached_tails, cached_tails)
            for left_tail, right_tail in tail_pairs:
                left = group.prefix + tuple(left_tail)
                right = (
                    group.prefix[:-1]
                    + (group.prefix[-1] + 1,)
                    + tuple(right_tail)
                )
                row = [0] * (2 * len(self.vertices))
                left_offset = 2 * self.vertex_index[left]
                right_offset = 2 * self.vertex_index[right]
                row[left_offset : left_offset + 2] = label
                row[right_offset] = -label[0]
                row[right_offset + 1] = -label[1]
                rows.append(row)
        return tuple(rows)

    def rows(self, genome: Genome) -> tuple[list[int], ...]:
        rows = list(self.edge_rows(genome))
        for measurement in genome.measurements:
            vertex_index, slope_index = divmod(measurement, len(self.slopes))
            label = self.slopes[slope_index]
            row = [0] * (2 * len(self.vertices))
            row[2 * vertex_index : 2 * vertex_index + 2] = label
            rows.append(row)
        return tuple(rows)

    def cost(self, genome: Genome) -> int:
        edge_cost = sum(
            group.cost
            for group, label_index in zip(self.groups, genome.labels)
            if label_index >= 0
        )
        return edge_cost + len(genome.measurements)

    def evaluate(self, genome: Genome) -> Evaluation:
        cached = self.cache.get(genome)
        if cached is not None:
            return cached
        known = set(genome.known)
        rows = self.rows(genome)
        rounds: list[list[int]] = []
        final_rank = 0
        while len(known) < len(self.vertices):
            unknown = [
                index for index in range(len(self.vertices)) if index not in known
            ]
            columns = [
                coordinate
                for index in unknown
                for coordinate in (2 * index, 2 * index + 1)
            ]
            restricted = [[row[column] for column in columns] for row in rows]
            basis, pivots = row_rref_mod(restricted, self.prime)
            final_rank = len(pivots)
            forceable: list[int] = []
            for local_index, global_index in enumerate(unknown):
                target = [0] * (2 * len(unknown))
                target[2 * local_index] = 1
                target[2 * local_index + 1] = -1
                if in_span_mod(target, basis, pivots, self.prime):
                    forceable.append(global_index)
            if not forceable:
                break
            known.update(forceable)
            rounds.append(forceable)
        evaluation = Evaluation(
            forced=len(known),
            total=len(self.vertices),
            cost=self.cost(genome),
            denominator=len(self.vertices) - len(genome.known),
            rank=final_rank,
            modular_rounds=rounds,
        )
        self.cache[genome] = evaluation
        return evaluation

    def random_genome(self, rng: random.Random) -> Genome:
        labels = [-1] * len(self.groups)
        group_order = list(range(len(self.groups)))
        rng.shuffle(group_order)
        known = (
            tuple(sorted(rng.sample(range(len(self.vertices)), self.known_count)))
            if self.known_count
            else ()
        )
        remaining = self.budget
        for group_index in group_order:
            group = self.groups[group_index]
            if group.cost <= remaining and rng.random() < 0.65:
                labels[group_index] = rng.randrange(len(self.slopes))
                remaining -= group.cost
        maximum_measurements = min(remaining, self.measurement_count)
        measurement_total = rng.randrange(maximum_measurements + 1)
        measurements = tuple(
            sorted(rng.sample(range(self.measurement_count), measurement_total))
        )
        return Genome(tuple(labels), measurements, known)

    def mutate(self, genome: Genome, rng: random.Random) -> Genome:
        labels = list(genome.labels)
        measurements = set(genome.measurements)
        for _ in range(1 if rng.random() < 0.8 else rng.randint(2, 4)):
            operations = ["label", "measurement", "swap"]
            if self.known_count:
                operations.append("known")
            operation = rng.choice(operations)
            if operation == "label" and labels:
                index = rng.randrange(len(labels))
                if labels[index] < 0:
                    labels[index] = rng.randrange(len(self.slopes))
                elif rng.random() < 0.35:
                    labels[index] = -1
                else:
                    labels[index] = rng.randrange(len(self.slopes))
            elif operation == "measurement":
                value = rng.randrange(self.measurement_count)
                if value in measurements:
                    measurements.remove(value)
                else:
                    measurements.add(value)
            elif operation == "swap" and measurements:
                removed = rng.choice(tuple(measurements))
                measurements.remove(removed)
                measurements.add(rng.randrange(self.measurement_count))
            elif operation == "known":
                known = set(genome.known)
                removed = rng.choice(tuple(known))
                known.remove(removed)
                available = [
                    index
                    for index in range(len(self.vertices))
                    if index not in known
                ]
                known.add(rng.choice(available))
                genome = Genome(genome.labels, genome.measurements, tuple(sorted(known)))
        result = Genome(tuple(labels), tuple(sorted(measurements)), genome.known)
        if self.cost(result) <= self.budget:
            return result
        return genome

    def crossover(
        self,
        left: Genome,
        right: Genome,
        rng: random.Random,
    ) -> Genome:
        labels = tuple(
            left_value if rng.random() < 0.5 else right_value
            for left_value, right_value in zip(left.labels, right.labels)
        )
        measurements = tuple(
            sorted(
                value
                for value in set(left.measurements) | set(right.measurements)
                if rng.random() < 0.5
            )
        )
        known = (
            left.known if rng.random() < 0.5 else right.known
        ) if self.known_count else ()
        child = Genome(labels, measurements, known)
        return child if self.cost(child) <= self.budget else left

    def exact_candidate(self, genome: Genome):
        functions: list[dict[Vertex, Pair]] = [
            {} for _ in self.shape
        ]
        used = {(0, 0)}
        for group, label_index in zip(self.groups, genome.labels):
            if label_index < 0:
                continue
            label = self.slopes[label_index]
            functions[group.axis][group.prefix] = label
            used.add(label)
        singleton_rows: list[dict[Vertex, Pair]] = []
        for measurement in genome.measurements:
            vertex_index, slope_index = divmod(measurement, len(self.slopes))
            label = self.slopes[slope_index]
            singleton_rows.append({self.vertices[vertex_index]: label})
            used.add(label)
        return VERIFIER.Candidate(
            claimed_header="generated; recompute all parameters",
            x_set=tuple(sorted(used)),
            dimensions=self.shape,
            graph_functions=tuple(functions),
            initial_known=tuple(self.vertices[index] for index in genome.known),
            singleton_rows=tuple(singleton_rows),
        )

    def exact_check(self, genome: Genome) -> dict[str, object]:
        candidate = self.exact_candidate(genome)
        same_tail_result = VERIFIER.verify(candidate, self.threshold)
        if self.edge_semantics == "same-tail":
            return same_tail_result
        known, rounds = VERIFIER.forcing_closure(
            self.vertices,
            self.rows(genome),
            tuple(self.vertices[index] for index in genome.known),
        )
        score = Fraction(
            self.cost(genome),
            len(self.vertices) - len(genome.known),
        )
        result: dict[str, object] = {
            "status": "shadow-verifier-pass",
            "score": f"{score.numerator}/{score.denominator}",
            "target_score": (
                f"{self.threshold.numerator}/{self.threshold.denominator}"
            ),
            "parameters": {
                "m": self.cost(genome) - len(genome.measurements),
                "r": len(genome.measurements),
                "n": len(self.vertices),
                "t": len(genome.known),
            },
            "forcing_rounds": [
                [list(vertex) for vertex in round_vertices]
                for round_vertices in rounds
            ],
            "edge_semantics": "literal-cross-tail",
            "checked_predicates": [
                "public-operation-1-literal-prefix-conditions",
                "exact-m-and-score",
                "forcing-closure-by-rational-row-span",
                "score-threshold",
            ],
            "same_tail_shadow_status": same_tail_result["status"],
            "same_tail_shadow_failure": same_tail_result.get("failure"),
            "epoch_verifier_equivalence": False,
        }
        if len(known) != len(self.vertices):
            result.update(
                {
                    "status": "shadow-verifier-reject",
                    "failure": "forcing-closure-stuck",
                    "unforced_vertices": [
                        list(vertex)
                        for vertex in self.vertices
                        if vertex not in known
                    ],
                }
            )
        elif score > self.threshold:
            result.update(
                {
                    "status": "shadow-verifier-reject",
                    "failure": "score-above-contract-threshold",
                }
            )
        return result

    def serialize(self, genome: Genome, exact: dict[str, object]) -> str:
        candidate = self.exact_candidate(genome)
        parameters = exact["parameters"]
        assert isinstance(parameters, dict)
        header = (
            f"{exact['score']}; m={parameters['m']}, |R|={parameters['r']}, "
            f"n={parameters['n']}, |T|={parameters['t']}"
        )
        return "\n".join(
            [
                header,
                repr(list(candidate.x_set)),
                repr(list(candidate.dimensions)),
                repr(list(candidate.graph_functions)),
                repr(list(candidate.initial_known)),
                repr(list(candidate.singleton_rows)),
            ]
        )


def evolve(
    space: SearchSpace,
    *,
    population_size: int,
    generations: int,
    seed: int,
) -> tuple[Genome, Evaluation, list[dict[str, object]]]:
    rng = random.Random(seed)
    population = [space.random_genome(rng) for _ in range(population_size)]
    exact_survivors: list[dict[str, object]] = []
    best_genome = population[0]
    best_evaluation = space.evaluate(best_genome)
    for generation in range(generations):
        population = list(dict.fromkeys(population))
        ranked = sorted(
            population,
            key=lambda genome: space.evaluate(genome).fitness(),
            reverse=True,
        )
        if space.evaluate(ranked[0]).fitness() > best_evaluation.fitness():
            best_genome = ranked[0]
            best_evaluation = space.evaluate(best_genome)
        for genome in ranked:
            evaluation = space.evaluate(genome)
            if not evaluation.forcing:
                continue
            exact = space.exact_check(genome)
            evaluation.exact_status = str(exact["status"])
            evaluation.exact_result = exact
            if exact["status"] == "shadow-verifier-pass":
                exact_survivors.append(
                    {
                        "generation": generation,
                        "genome": genome,
                        "exact": exact,
                        "candidate": space.serialize(genome, exact),
                    }
                )
                return genome, evaluation, exact_survivors
        elite_count = max(4, population_size // 10)
        parent_pool = ranked[: max(elite_count, population_size // 3)]
        next_population = ranked[:elite_count]
        while len(next_population) < population_size:
            if rng.random() < 0.25 and len(parent_pool) >= 2:
                left, right = rng.sample(parent_pool, 2)
                child = space.crossover(left, right, rng)
            else:
                child = rng.choice(parent_pool)
            next_population.append(space.mutate(child, rng))
        if generation % 20 == 0:
            next_population.extend(
                space.random_genome(rng)
                for _ in range(max(2, population_size // 20))
            )
        population = next_population
    return best_genome, best_evaluation, exact_survivors


def parse_shape(value: str) -> tuple[int, ...]:
    shape = tuple(int(part) for part in value.split("x"))
    if not shape or any(dimension < 1 for dimension in shape):
        raise argparse.ArgumentTypeError("shape must look like 2x3 with positive dimensions")
    return shape


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shape",
        dest="shapes",
        action="append",
        type=parse_shape,
        required=True,
    )
    parser.add_argument("--height", type=int, default=3)
    parser.add_argument("--population", type=int, default=400)
    parser.add_argument("--generations", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260725)
    parser.add_argument("--prime", type=int, default=1_000_003)
    parser.add_argument("--target-numerator", type=int, default=67)
    parser.add_argument("--target-denominator", type=int, default=40)
    parser.add_argument(
        "--known-count",
        type=int,
        default=0,
        help="fix |T| and evolve which vertices are initially known",
    )
    parser.add_argument(
        "--edge-semantics",
        choices=("same-tail", "literal-cross-tail"),
        default="same-tail",
        help=(
            "use intended equal suffixes or the broader literal wording of "
            "public forcing operation 1"
        ),
    )
    args = parser.parse_args()
    threshold = Fraction(args.target_numerator, args.target_denominator)
    slopes = slope_pool(args.height)
    started = time.perf_counter()
    summaries: list[dict[str, object]] = []
    for offset, shape in enumerate(args.shapes):
        space = SearchSpace(
            shape,
            slopes,
            threshold,
            args.prime,
            known_count=args.known_count,
            edge_semantics=args.edge_semantics,
        )
        genome, evaluation, survivors = evolve(
            space,
            population_size=args.population,
            generations=args.generations,
            seed=args.seed + offset,
        )
        summary: dict[str, object] = {
            "shape": list(shape),
            "vertices": len(space.vertices),
            "groups": len(space.groups),
            "slope_count": len(slopes),
            "budget": space.budget,
            "known_count": space.known_count,
            "edge_semantics": space.edge_semantics,
            "evaluated": len(space.cache),
            "best_forced": evaluation.forced,
            "best_derived": evaluation.forced - space.known_count,
            "best_cost": evaluation.cost,
            "best_score": (
                f"{evaluation.score.numerator}/{evaluation.score.denominator}"
            ),
            "best_initial_known": [
                list(space.vertices[index]) for index in genome.known
            ],
            "best_modular_rounds": evaluation.modular_rounds,
            "exact_survivor_count": len(survivors),
        }
        if survivors:
            survivor = survivors[0]
            summary["candidate"] = survivor["candidate"]
            summary["exact"] = survivor["exact"]
        summaries.append(summary)
        print(json.dumps(summary, sort_keys=True), flush=True)
    final = {
        "status": "exact-candidate-found"
        if any(summary["exact_survivor_count"] for summary in summaries)
        else "bounded-search-no-exact-candidate",
        "method": "one-prime evolutionary filter followed by exact rational verification",
        "prime": args.prime,
        "target": f"{threshold.numerator}/{threshold.denominator}",
        "height": args.height,
        "seed": args.seed,
        "population": args.population,
        "generations": args.generations,
        "known_count": args.known_count,
        "edge_semantics": args.edge_semantics,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "summaries": summaries,
        "completeness": "heuristic; no completeness claim",
    }
    print(json.dumps(final, indent=2, sort_keys=True))
    return 0 if final["status"] == "exact-candidate-found" else 1


if __name__ == "__main__":
    raise SystemExit(main())
