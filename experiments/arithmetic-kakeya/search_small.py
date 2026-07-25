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
    covered: int
    grounded: int
    cost: int
    denominator: int
    rank: int
    modular_rounds: list[list[int]]
    defect: int = 0
    exact_status: str | None = None
    exact_result: dict[str, object] | None = None

    @property
    def forcing(self) -> bool:
        return self.forced == self.total

    @property
    def score(self) -> Fraction:
        return Fraction(self.cost, self.denominator)

    def fitness(
        self,
        coverage_first: bool = False,
    ) -> tuple[int, int, int, int, int, int]:
        if self.forcing:
            return (
                2,
                -self.score.numerator * 1_000_000 // self.score.denominator,
                -self.cost,
                self.rank,
                0,
                0,
            )
        if coverage_first:
            return (
                1,
                self.covered,
                self.grounded,
                self.forced,
                -self.defect,
                self.rank,
            )
        return (
            1,
            self.forced,
            self.grounded,
            -self.defect,
            self.rank,
            -self.cost,
        )


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


def distinct_tau_pool(count: int, seed: int) -> tuple[Pair, ...]:
    """Return distinct projective labels with seeded integer tau parameters."""
    if count < 1:
        raise ValueError("distinct tau pool must be nonempty")
    rng = random.Random(seed)
    tau_values = rng.sample(range(-10_000_000, 10_000_001), count)
    return tuple((1 + tau, 1 - tau) for tau in tau_values)


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


def pair_target_in_span_mod(
    first: int,
    second: int,
    basis: Sequence[Sequence[int]],
    pivots: Sequence[int],
    width: int,
    prime: int,
) -> bool:
    """Test e_first-e_second against an RREF row space without dense reduction."""
    return (
        pair_target_residual_weight_mod(
            first,
            second,
            basis,
            pivots,
            width,
            prime,
        )
        == 0
    )


def pair_target_residual_weight_mod(
    first: int,
    second: int,
    basis: Sequence[Sequence[int]],
    pivots: Sequence[int],
    width: int,
    prime: int,
) -> int:
    """Count nonzero free-column residues after reducing e_first-e_second."""
    pivot_rows = {pivot: row_index for row_index, pivot in enumerate(pivots)}
    first_pivot = pivot_rows.get(first)
    second_pivot = pivot_rows.get(second)
    weight = 0
    for column in range(width):
        if column in pivot_rows:
            continue
        residual = (
            (1 if column == first else 0)
            - (1 if column == second else 0)
        )
        if first_pivot is not None:
            residual -= basis[first_pivot][column]
        if second_pivot is not None:
            residual += basis[second_pivot][column]
        if residual % prime:
            weight += 1
    return weight


def grounded_vertex_count(
    rows: Sequence[Sequence[int]],
    known: set[int],
    total: int,
) -> int:
    """Count known vertices plus unresolved vertices connected to ground."""
    unknown = [index for index in range(total) if index not in known]
    adjacency = {index: set() for index in unknown}
    grounded: set[int] = set()
    for row in rows:
        support = [
            index
            for index in unknown
            if row[2 * index] != 0 or row[2 * index + 1] != 0
        ]
        if len(support) == 1:
            grounded.add(support[0])
        elif len(support) == 2:
            left, right = support
            adjacency[left].add(right)
            adjacency[right].add(left)
        elif len(support) > 2:
            raise ValueError("generator row has support on more than two vertices")
    frontier = list(grounded)
    while frontier:
        vertex_index = frontier.pop()
        for neighbor in adjacency[vertex_index]:
            if neighbor not in grounded:
                grounded.add(neighbor)
                frontier.append(neighbor)
    return len(known) + len(grounded)


class SearchSpace:
    def __init__(
        self,
        shape: tuple[int, ...],
        slopes: tuple[Pair, ...],
        threshold: Fraction,
        prime: int,
        known_count: int = 0,
        edge_semantics: str = "same-tail",
        distinct_generator_labels: bool = False,
        singleton_slots: int = 4,
        force_all_groups: bool = False,
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
        self.required_groups = (
            frozenset(range(len(self.groups)))
            if force_all_groups
            else frozenset()
        )
        if singleton_slots < 1:
            raise ValueError("singleton_slots must be positive")
        self.distinct_generator_labels = distinct_generator_labels
        self.singleton_slots = singleton_slots
        if distinct_generator_labels:
            required_labels = len(self.groups) + len(self.vertices) * singleton_slots
            if len(slopes) < required_labels:
                raise ValueError(
                    "distinct-generator mode needs one label per group and "
                    "singleton slot"
                )
        denominator = len(self.vertices) - known_count
        self.budget = threshold.numerator * denominator // threshold.denominator
        required_cost = sum(
            self.groups[index].cost for index in self.required_groups
        )
        if required_cost > self.budget:
            raise ValueError(
                "required graph groups exceed the exact score budget"
            )
        self.measurement_count = len(self.vertices) * len(slopes)
        if distinct_generator_labels:
            singleton_offset = len(self.groups)
            self.measurement_universe = tuple(
                vertex_index * len(slopes)
                + singleton_offset
                + vertex_index * singleton_slots
                + slot
                for vertex_index in range(len(self.vertices))
                for slot in range(singleton_slots)
            )
        else:
            self.measurement_universe = tuple(range(self.measurement_count))
        self.cache: dict[Genome, Evaluation] = {}

    def random_group_label(self, group_index: int, rng: random.Random) -> int:
        if self.distinct_generator_labels:
            return group_index
        return rng.randrange(len(self.slopes))

    def random_measurement(
        self,
        rng: random.Random,
        vertex_index: int | None = None,
    ) -> int:
        if vertex_index is None or not self.distinct_generator_labels:
            return rng.choice(self.measurement_universe)
        start = len(self.groups) + vertex_index * self.singleton_slots
        slope_index = start + rng.randrange(self.singleton_slots)
        return vertex_index * len(self.slopes) + slope_index

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
        supported = {
            index
            for index in range(len(self.vertices))
            if any(
                row[2 * index] != 0 or row[2 * index + 1] != 0
                for row in rows
            )
        }
        rounds: list[list[int]] = []
        final_rank = 0
        final_defect = 0
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
            target_defects: list[int] = []
            for local_index, global_index in enumerate(unknown):
                defect = pair_target_residual_weight_mod(
                    2 * local_index,
                    2 * local_index + 1,
                    basis,
                    pivots,
                    2 * len(unknown),
                    self.prime,
                )
                target_defects.append(defect)
                if defect == 0:
                    forceable.append(global_index)
            final_defect = sum(target_defects)
            if not forceable:
                break
            known.update(forceable)
            rounds.append(forceable)
        evaluation = Evaluation(
            forced=len(known),
            total=len(self.vertices),
            covered=len(supported | set(genome.known)),
            grounded=grounded_vertex_count(
                rows,
                known,
                len(self.vertices),
            ),
            cost=self.cost(genome),
            denominator=len(self.vertices) - len(genome.known),
            rank=final_rank,
            modular_rounds=rounds,
            defect=final_defect,
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
        for group_index in self.required_groups:
            labels[group_index] = self.random_group_label(group_index, rng)
            remaining -= self.groups[group_index].cost
        for group_index in group_order:
            if group_index in self.required_groups:
                continue
            group = self.groups[group_index]
            if group.cost <= remaining and rng.random() < 0.65:
                labels[group_index] = self.random_group_label(group_index, rng)
                remaining -= group.cost
        maximum_measurements = min(remaining, len(self.measurement_universe))
        measurement_total = rng.randrange(maximum_measurements + 1)
        measurements = tuple(
            sorted(rng.sample(self.measurement_universe, measurement_total))
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
                    labels[index] = self.random_group_label(index, rng)
                elif (
                    index not in self.required_groups
                    and rng.random() < 0.35
                ):
                    labels[index] = -1
                else:
                    labels[index] = self.random_group_label(index, rng)
            elif operation == "measurement":
                value = self.random_measurement(rng)
                if value in measurements:
                    measurements.remove(value)
                else:
                    measurements.add(value)
            elif operation == "swap" and measurements:
                removed = rng.choice(tuple(measurements))
                measurements.remove(removed)
                measurements.add(self.random_measurement(rng))
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

    def guided_mutate(self, genome: Genome, rng: random.Random) -> Genome:
        evaluation = self.evaluate(genome)
        derived = {
            index
            for round_indices in evaluation.modular_rounds
            for index in round_indices
        }
        unresolved = [
            index
            for index in range(len(self.vertices))
            if index not in set(genome.known) | derived
        ]
        if not unresolved:
            return self.mutate(genome, rng)

        victim_index = rng.choice(unresolved)
        victim = self.vertices[victim_index]
        labels = list(genome.labels)
        measurements = set(genome.measurements)
        protected_group: int | None = None
        protected_measurement: int | None = None
        incident_groups = [
            index
            for index, group in enumerate(self.groups)
            if victim[: group.axis + 1]
            in {
                group.prefix,
                group.prefix[:-1] + (group.prefix[-1] + 1,),
            }
        ]
        if incident_groups and rng.random() < 0.55:
            protected_group = rng.choice(incident_groups)
            labels[protected_group] = self.random_group_label(
                protected_group,
                rng,
            )
        else:
            protected_measurement = self.random_measurement(rng, victim_index)
            measurements.add(protected_measurement)

        def current() -> Genome:
            return Genome(
                tuple(labels),
                tuple(sorted(measurements)),
                genome.known,
            )

        while self.cost(current()) > self.budget:
            removable_measurements = [
                value
                for value in measurements
                if value != protected_measurement
            ]
            removable_groups = [
                index
                for index, label_index in enumerate(labels)
                if (
                    label_index >= 0
                    and index != protected_group
                    and index not in self.required_groups
                )
            ]
            if not removable_measurements and not removable_groups:
                return genome
            if removable_measurements and (
                not removable_groups or rng.random() < 0.6
            ):
                measurements.remove(rng.choice(removable_measurements))
            else:
                labels[rng.choice(removable_groups)] = -1

        result = current()
        return result if result != genome else self.mutate(genome, rng)

    def label_repair(
        self,
        genome: Genome,
        rng: random.Random,
        trials: int,
        coverage_first: bool = False,
    ) -> Genome:
        """Sample cost-preserving label substitutions and keep the best."""
        if trials < 1 or self.distinct_generator_labels:
            return genome
        active_groups = [
            index for index, label_index in enumerate(genome.labels)
            if label_index >= 0
        ]
        if not active_groups and not genome.measurements:
            return genome
        best = genome
        best_fitness = self.evaluate(genome).fitness(coverage_first)
        for _ in range(trials):
            labels = list(genome.labels)
            measurements = set(genome.measurements)
            if active_groups and (
                not measurements or rng.random() < 0.5
            ):
                group_index = rng.choice(active_groups)
                labels[group_index] = rng.randrange(len(self.slopes))
            else:
                measurement = rng.choice(tuple(measurements))
                measurements.remove(measurement)
                vertex_index, _ = divmod(measurement, len(self.slopes))
                replacement = (
                    vertex_index * len(self.slopes)
                    + rng.randrange(len(self.slopes))
                )
                measurements.add(replacement)
            candidate = Genome(
                tuple(labels),
                tuple(sorted(measurements)),
                genome.known,
            )
            if self.cost(candidate) > self.budget:
                continue
            fitness = self.evaluate(candidate).fitness(coverage_first)
            if fitness > best_fitness:
                best = candidate
                best_fitness = fitness
        return best

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
    guided_repair_rate: float = 0.0,
    guided_repair_depth: int = 1,
    coverage_first: bool = False,
    label_repair_rate: float = 0.0,
    label_repair_trials: int = 8,
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
            key=lambda genome: space.evaluate(genome).fitness(coverage_first),
            reverse=True,
        )
        if (
            space.evaluate(ranked[0]).fitness(coverage_first)
            > best_evaluation.fitness(coverage_first)
        ):
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
            if guided_repair_rate and rng.random() < guided_repair_rate:
                for _ in range(guided_repair_depth):
                    child = space.guided_mutate(child, rng)
            else:
                child = space.mutate(child, rng)
            if label_repair_rate and rng.random() < label_repair_rate:
                child = space.label_repair(
                    child,
                    rng,
                    label_repair_trials,
                    coverage_first,
                )
            next_population.append(child)
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
    parser.add_argument(
        "--emit-best-candidate",
        action="store_true",
        help="include the best genome and exact rejection packet even without a survivor",
    )
    parser.add_argument(
        "--guided-repair-rate",
        type=float,
        default=0.0,
        help="probability of mutating an unresolved vertex directly (0 to 1)",
    )
    parser.add_argument(
        "--guided-repair-depth",
        type=int,
        default=1,
        help="number of consecutive guided edits when repair is selected",
    )
    parser.add_argument(
        "--coverage-first",
        action="store_true",
        help="rank full generator support ahead of partial forcing progress",
    )
    parser.add_argument(
        "--distinct-generator-labels",
        action="store_true",
        help=(
            "assign a separate seeded integer-tau label to every active graph "
            "group and singleton slot"
        ),
    )
    parser.add_argument(
        "--singleton-slots",
        type=int,
        default=4,
        help="per-vertex singleton choices in distinct-generator mode",
    )
    parser.add_argument(
        "--label-repair-rate",
        type=float,
        default=0.0,
        help="probability of sampled cost-preserving slope hill climbing",
    )
    parser.add_argument(
        "--label-repair-trials",
        type=int,
        default=8,
        help="slope substitutions sampled in each label-repair step",
    )
    parser.add_argument(
        "--force-all-groups",
        action="store_true",
        help="keep every product-graph group active and evolve only its label",
    )
    args = parser.parse_args()
    if not 0.0 <= args.guided_repair_rate <= 1.0:
        parser.error("--guided-repair-rate must be between 0 and 1")
    if args.guided_repair_depth < 1:
        parser.error("--guided-repair-depth must be positive")
    if args.singleton_slots < 1:
        parser.error("--singleton-slots must be positive")
    if not 0.0 <= args.label_repair_rate <= 1.0:
        parser.error("--label-repair-rate must be between 0 and 1")
    if args.label_repair_trials < 1:
        parser.error("--label-repair-trials must be positive")
    threshold = Fraction(args.target_numerator, args.target_denominator)
    if args.distinct_generator_labels:
        label_count = max(
            len(groups(shape)) + math.prod(shape) * args.singleton_slots
            for shape in args.shapes
        )
        slopes = distinct_tau_pool(label_count, args.seed)
    else:
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
            distinct_generator_labels=args.distinct_generator_labels,
            singleton_slots=args.singleton_slots,
            force_all_groups=args.force_all_groups,
        )
        genome, evaluation, survivors = evolve(
            space,
            population_size=args.population,
            generations=args.generations,
            seed=args.seed + offset,
            guided_repair_rate=args.guided_repair_rate,
            guided_repair_depth=args.guided_repair_depth,
            coverage_first=args.coverage_first,
            label_repair_rate=args.label_repair_rate,
            label_repair_trials=args.label_repair_trials,
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
            "best_defect": evaluation.defect,
            "best_covered": evaluation.covered,
            "best_grounded": evaluation.grounded,
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
        elif args.emit_best_candidate:
            exact = space.exact_check(genome)
            summary["best_candidate"] = space.serialize(genome, exact)
            summary["best_exact"] = exact
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
        "guided_repair_rate": args.guided_repair_rate,
        "guided_repair_depth": args.guided_repair_depth,
        "coverage_first": args.coverage_first,
        "distinct_generator_labels": args.distinct_generator_labels,
        "singleton_slots": args.singleton_slots,
        "label_repair_rate": args.label_repair_rate,
        "label_repair_trials": args.label_repair_trials,
        "force_all_groups": args.force_all_groups,
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
