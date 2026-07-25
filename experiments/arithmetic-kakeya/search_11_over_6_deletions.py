#!/usr/bin/env python3
"""Retune every viable one-generator deletion of an 11/6 topology.

This is a discovery program. It keeps the product-graph and singleton supports
fixed, evolves only slope labels, filters over one prime, and exact-checks every
modular full-forcing assignment.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
import time
from fractions import Fraction
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
SEARCH_PATH = ROOT / "experiments" / "arithmetic-kakeya" / "search_small.py"


def load_search():
    spec = importlib.util.spec_from_file_location(
        "arithmetic_kakeya_deletion_search",
        SEARCH_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SEARCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SEARCH = load_search()
Assignment = tuple[int, ...]


def topology_cases(space) -> list[dict[str, object]]:
    unit_groups = [
        index for index, group in enumerate(space.groups) if group.cost == 1
    ]
    singleton_vertices = (
        space.vertex_index[(1, 1)],
        space.vertex_index[(1, 2)],
        space.vertex_index[(1, 3)],
        space.vertex_index[(2, 1)],
    )
    cases: list[dict[str, object]] = []
    for deleted_group in unit_groups:
        active_groups = tuple(
            index
            for index in range(len(space.groups))
            if index != deleted_group
        )
        cases.append(
            {
                "name": (
                    "delete-edge-"
                    + "-".join(
                        str(value)
                        for value in space.groups[deleted_group].prefix
                    )
                ),
                "active_groups": active_groups,
                "singleton_vertices": singleton_vertices,
            }
        )
    for deleted_singleton in range(len(singleton_vertices)):
        cases.append(
            {
                "name": f"delete-singleton-{deleted_singleton + 1}",
                "active_groups": tuple(range(len(space.groups))),
                "singleton_vertices": tuple(
                    vertex
                    for index, vertex in enumerate(singleton_vertices)
                    if index != deleted_singleton
                ),
            }
        )
    return [
        case
        for case in cases
        if all(
            sum(
                1
                for group_index in case["active_groups"]
                if vertex_incident(
                    space,
                    int(group_index),
                    vertex_index,
                )
            )
            + sum(
                singleton_vertex == vertex_index
                for singleton_vertex in case["singleton_vertices"]
            )
            >= 2
            for vertex_index in range(len(space.vertices))
        )
    ]


def vertex_incident(space, group_index: int, vertex_index: int) -> bool:
    vertex = space.vertices[vertex_index]
    group = space.groups[group_index]
    return vertex[: group.axis + 1] in {
        group.prefix,
        group.prefix[:-1] + (group.prefix[-1] + 1,),
    }


def decode(space, case: dict[str, object], assignment: Assignment):
    active_groups = tuple(int(value) for value in case["active_groups"])
    singleton_vertices = tuple(
        int(value) for value in case["singleton_vertices"]
    )
    labels = [-1] * len(space.groups)
    cursor = 0
    for group_index in active_groups:
        labels[group_index] = assignment[cursor]
        cursor += 1
    measurements: list[int] = []
    for vertex_index in singleton_vertices:
        measurements.append(
            vertex_index * len(space.slopes) + assignment[cursor]
        )
        cursor += 1
    return SEARCH.Genome(tuple(labels), tuple(sorted(measurements)), ())


def random_assignment(
    rng: random.Random,
    length: int,
    slope_count: int,
) -> Assignment:
    return tuple(rng.randrange(slope_count) for _ in range(length))


def mutate(
    assignment: Assignment,
    rng: random.Random,
    slope_count: int,
) -> Assignment:
    values = list(assignment)
    for _ in range(1 if rng.random() < 0.85 else 2):
        index = rng.randrange(len(values))
        replacement = rng.randrange(slope_count)
        while replacement == values[index] and slope_count > 1:
            replacement = rng.randrange(slope_count)
        values[index] = replacement
    return tuple(values)


def crossover(
    left: Assignment,
    right: Assignment,
    rng: random.Random,
) -> Assignment:
    return tuple(
        left_value if rng.random() < 0.5 else right_value
        for left_value, right_value in zip(left, right)
    )


def evolve_case(
    space,
    case: dict[str, object],
    *,
    population_size: int,
    generations: int,
    seed: int,
) -> dict[str, object]:
    rng = random.Random(seed)
    assignment_length = len(case["active_groups"]) + len(
        case["singleton_vertices"]
    )
    population = [
        random_assignment(rng, assignment_length, len(space.slopes))
        for _ in range(population_size)
    ]
    exact_checked: set[SEARCH.Genome] = set()
    best_assignment = population[0]
    best_genome = decode(space, case, best_assignment)
    best_evaluation = space.evaluate(best_genome)
    for generation in range(generations):
        population = list(dict.fromkeys(population))
        ranked = sorted(
            population,
            key=lambda item: space.evaluate(
                decode(space, case, item)
            ).fitness(),
            reverse=True,
        )
        leader = decode(space, case, ranked[0])
        leader_evaluation = space.evaluate(leader)
        if leader_evaluation.fitness() > best_evaluation.fitness():
            best_assignment = ranked[0]
            best_genome = leader
            best_evaluation = leader_evaluation
        for assignment in ranked:
            genome = decode(space, case, assignment)
            evaluation = space.evaluate(genome)
            if not evaluation.forcing or genome in exact_checked:
                continue
            exact_checked.add(genome)
            exact = space.exact_check(genome)
            if exact["status"] == "shadow-verifier-pass":
                return {
                    "status": "exact-candidate-found",
                    "generation": generation,
                    "evaluated": len(space.cache),
                    "exact_checked": len(exact_checked),
                    "candidate": space.serialize(genome, exact),
                    "exact": exact,
                }
        elite_count = max(4, population_size // 10)
        parents = ranked[: max(elite_count, population_size // 3)]
        next_population = ranked[:elite_count]
        while len(next_population) < population_size:
            if len(parents) >= 2 and rng.random() < 0.3:
                child = crossover(*rng.sample(parents, 2), rng)
            else:
                child = rng.choice(parents)
            next_population.append(mutate(child, rng, len(space.slopes)))
        population = next_population
    exact = space.exact_check(best_genome)
    return {
        "status": "bounded-search-no-exact-candidate",
        "evaluated": len(space.cache),
        "exact_checked": len(exact_checked),
        "best_forced": best_evaluation.forced,
        "best_covered": best_evaluation.covered,
        "best_candidate": space.serialize(best_genome, exact),
        "best_exact": exact,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--height", type=int, default=10)
    parser.add_argument("--population", type=int, default=800)
    parser.add_argument("--generations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=202607262)
    args = parser.parse_args()
    if args.height < 1:
        parser.error("--height must be positive")
    if args.population < 4:
        parser.error("--population must be at least four")
    if args.generations < 1:
        parser.error("--generations must be positive")

    slopes = SEARCH.slope_pool(args.height)
    space = SEARCH.SearchSpace(
        (2, 3),
        slopes,
        Fraction(67, 40),
        1_000_003,
    )
    cases = topology_cases(space)
    started = time.perf_counter()
    results: list[dict[str, object]] = []
    for offset, case in enumerate(cases):
        space.cache.clear()
        result = evolve_case(
            space,
            case,
            population_size=args.population,
            generations=args.generations,
            seed=args.seed + offset,
        )
        packet = {"case": case["name"], **result}
        results.append(packet)
        print(json.dumps(packet, sort_keys=True), flush=True)
        if result["status"] == "exact-candidate-found":
            break
    final = {
        "status": (
            "exact-candidate-found"
            if any(
                result["status"] == "exact-candidate-found"
                for result in results
            )
            else "bounded-search-no-exact-candidate"
        ),
        "target": "67/40",
        "source_topology": "one-unit deletion from calibrated 11/6 shape 2x3",
        "height": args.height,
        "slope_count": len(slopes),
        "population": args.population,
        "generations": args.generations,
        "seed": args.seed,
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "cases": results,
        "completeness": "heuristic label search over seven structurally viable deletions",
    }
    print(json.dumps(final, indent=2, sort_keys=True))
    return 0 if final["status"] == "exact-candidate-found" else 1


if __name__ == "__main__":
    raise SystemExit(main())
