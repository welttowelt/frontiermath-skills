#!/usr/bin/env python3
"""Independent audit of the LP333 affine-multiplier normalization census."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections import Counter
from pathlib import Path

from py39_compat import strict_zip

LENGTH = 333


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def crt(left: int, right: int) -> int:
    for value in range(left, LENGTH, 9):
        if value % 37 == right:
            return value
    raise AssertionError("CRT residues have no solution")


def additive_span(
    generators: tuple[tuple[int, int], ...]
) -> frozenset[tuple[int, int]]:
    reached = {(0, 0)}
    frontier = [(0, 0)]
    while frontier:
        left, right = frontier.pop()
        for gen_left, gen_right in generators:
            candidate = ((left + gen_left) % 6, (right + gen_right) % 36)
            if candidate not in reached:
                reached.add(candidate)
                frontier.append(candidate)
    return frozenset(reached)


def additive_subgroups() -> list[frozenset[tuple[int, int]]]:
    elements = tuple(
        (left, right) for left in range(6) for right in range(36)
    )
    subgroups = {additive_span((element,)) for element in elements}
    subgroups.add(frozenset({(0, 0)}))
    changed = True
    while changed:
        changed = False
        current = tuple(subgroups)
        for left_index, left in enumerate(current):
            for right in current[left_index:]:
                joined = additive_span(tuple(left | right))
                if joined not in subgroups:
                    subgroups.add(joined)
                    changed = True
    return sorted(
        subgroups,
        key=lambda group: (
            len(group),
            tuple(sorted(group)),
        ),
    )


def multiplicative_image(
    additive_group: frozenset[tuple[int, int]]
) -> tuple[int, ...]:
    return tuple(
        sorted(
            crt(pow(2, left, 9), pow(2, right, 37))
            for left, right in additive_group
        )
    )


def verify_cocycle(
    elements: tuple[int, ...],
    values: tuple[int, ...],
    modulus: int,
) -> bool:
    if len(elements) != len(values):
        return False
    lookup = dict(strict_zip(elements, values))
    if lookup.get(1) != 0:
        return False
    for left in elements:
        for right in elements:
            product = left * right % LENGTH
            if lookup[product] != (
                lookup[left] + left * lookup[right]
            ) % modulus:
                return False
    return True


def cocycles_from_generators(
    elements: tuple[int, ...],
    generators: tuple[int, ...],
    modulus: int,
) -> list[tuple[int, ...]]:
    if not generators:
        return [(0,)]
    found = set()
    for assigned in itertools.product(range(modulus), repeat=len(generators)):
        lookup = {1: 0}
        changed = True
        contradiction = False
        while changed and not contradiction:
            changed = False
            for left, left_value in tuple(lookup.items()):
                for generator, generator_value in strict_zip(
                    generators, assigned
                ):
                    product = left * generator % LENGTH
                    candidate = (
                        left_value + left * generator_value
                    ) % modulus
                    if product in lookup:
                        if lookup[product] != candidate:
                            contradiction = True
                            break
                    else:
                        lookup[product] = candidate
                        changed = True
                if contradiction:
                    break
        if contradiction or len(lookup) != len(elements):
            continue
        candidate = tuple(lookup[element] for element in elements)
        if verify_cocycle(elements, candidate, modulus):
            found.add(candidate)
    return sorted(found)


def canonical_cohomology_classes(
    elements: tuple[int, ...],
    cocycles: list[tuple[int, ...]],
    modulus: int,
) -> list[tuple[int, ...]]:
    coboundaries = {
        tuple((1 - element) * shift % modulus for element in elements)
        for shift in range(modulus)
    }
    return sorted(
        {
            min(
                tuple(
                    (value + delta) % modulus
                    for value, delta in strict_zip(cocycle, coboundary)
                )
                for coboundary in coboundaries
            )
            for cocycle in cocycles
        }
    )


def graph_orbits(
    elements: tuple[int, ...],
    generators: tuple[int, ...],
    cocycle: tuple[int, ...],
) -> list[list[int]]:
    lookup = dict(strict_zip(elements, cocycle))
    unseen = set(range(LENGTH))
    orbits = []
    while unseen:
        start = min(unseen)
        orbit = {start}
        frontier = [start]
        while frontier:
            value = frontier.pop()
            for generator in generators:
                image = (
                    generator * value + lookup[generator]
                ) % LENGTH
                if image not in orbit:
                    orbit.add(image)
                    frontier.append(image)
        unseen.difference_update(orbit)
        orbits.append(sorted(orbit))
    return sorted(orbits, key=lambda orbit: (len(orbit), orbit[0]))


def signature(orbits: list[list[int]]) -> list[list[int]]:
    counts = Counter(map(len, orbits))
    return [[size, counts[size]] for size in sorted(counts)]


def row_sum_feasible(orbits: list[list[int]]) -> bool:
    reachable = 1
    for orbit in orbits:
        reachable |= reachable << len(orbit)
    return bool((reachable >> 166) & 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("census", type=Path)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    census = json.loads(args.census.read_text(encoding="utf-8"))
    classification_path = (
        args.source_repo / "lp333" / "results"
        / "subgroup_classification.json"
    )
    status_path = (
        args.source_repo / "lp333" / "results" / "master_status.json"
    )
    independent_groups = {
        multiplicative_image(group) for group in additive_subgroups()
    }
    stored_groups = {
        tuple(record["elements"]) for record in census["subgroups"]
    }

    component_errors = []
    class_errors = []
    total_classes = 0
    nontrivial_classes = 0
    nontrivial_feasible = 0
    all_nontrivial_cycle_gcds = []
    first_nontrivial: tuple[tuple[int, ...], tuple[int, ...]] | None = None

    for record in census["subgroups"]:
        elements = tuple(record["elements"])
        generators = tuple(record["generators"])
        component_classes = {}
        for modulus, key in ((9, "mod9"), (37, "mod37")):
            cocycles = cocycles_from_generators(
                elements, generators, modulus
            )
            classes = canonical_cohomology_classes(
                elements, cocycles, modulus
            )
            component_classes[modulus] = classes
            expected = record["components"][key]
            if (
                len(cocycles) != expected["cocycles"]
                or len(classes) != expected["cohomology_classes"]
            ):
                component_errors.append(
                    {
                        "subgroup_id": record["subgroup_id"],
                        "modulus": modulus,
                        "cocycles": len(cocycles),
                        "classes": len(classes),
                        "stored": expected,
                    }
                )

        reconstructed = {
            tuple(
                crt(residue_9, residue_37)
                for residue_9, residue_37 in strict_zip(class_9, class_37)
            )
            for class_9, class_37 in itertools.product(
                component_classes[9], component_classes[37]
            )
        }
        stored_classes = {
            tuple(affine_class["cocycle_mod333"]): affine_class
            for affine_class in record["affine_conjugacy_classes"]
        }
        if set(stored_classes) != reconstructed:
            class_errors.append(
                {
                    "subgroup_id": record["subgroup_id"],
                    "reason": "cohomology representatives differ",
                }
            )
            continue

        for cocycle, affine_class in stored_classes.items():
            if not verify_cocycle(elements, cocycle, LENGTH):
                class_errors.append(
                    {
                        "subgroup_id": record["subgroup_id"],
                        "reason": "stored representative is not a cocycle",
                    }
                )
                continue
            orbits = graph_orbits(elements, generators, cocycle)
            feasible = row_sum_feasible(orbits)
            sizes = [len(orbit) for orbit in orbits]
            cycle_gcd = math.gcd(*sizes)
            if (
                signature(orbits) != affine_class["orbit_signature"]
                or cycle_gcd != affine_class["orbit_size_gcd"]
                or feasible
                != affine_class["row_sum_plus_or_minus_one_feasible"]
            ):
                class_errors.append(
                    {
                        "subgroup_id": record["subgroup_id"],
                        "reason": "orbit or row-sum record differs",
                    }
                )
            total_classes += 1
            if any(cocycle):
                nontrivial_classes += 1
                nontrivial_feasible += int(feasible)
                all_nontrivial_cycle_gcds.append(cycle_gcd)
                if first_nontrivial is None:
                    first_nontrivial = (elements, cocycle)

    mutation_rejected = False
    if first_nontrivial is not None:
        elements, cocycle = first_nontrivial
        for index in range(1, len(cocycle)):
            mutated = list(cocycle)
            mutated[index] = (mutated[index] + 1) % LENGTH
            if not verify_cocycle(elements, tuple(mutated), LENGTH):
                mutation_rejected = True
                break

    checks = {
        "census_status_pass": census.get("status") == "pass",
        "source_classification_hash": (
            file_digest(classification_path)
            == census["inputs"]["source_subgroup_classification_sha256"]
        ),
        "source_status_hash": (
            file_digest(status_path)
            == census["inputs"]["source_master_status_sha256"]
        ),
        "independent_additive_subgroup_count_80": (
            len(independent_groups) == 80
        ),
        "stored_subgroups_complete": stored_groups == independent_groups,
        "component_reconstruction": not component_errors,
        "class_reconstruction": not class_errors,
        "affine_class_count_134": total_classes == 134,
        "nontrivial_class_count_54": nontrivial_classes == 54,
        "nontrivial_row_sum_feasible_count_zero": (
            nontrivial_feasible == 0
        ),
        "all_nontrivial_cycle_gcds_divisible_by_3": all(
            divisor % 3 == 0 for divisor in all_nontrivial_cycle_gcds
        ),
        "mutated_cocycle_rejected": mutation_rejected,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": (
            "frontiermath-hadamard-lp333-affine-multiplier-"
            "normalization-audit-v1"
        ),
        "status": status,
        "checks": checks,
        "counts": {
            "independent_subgroups": len(independent_groups),
            "affine_classes": total_classes,
            "nontrivial_classes": nontrivial_classes,
            "nontrivial_row_sum_feasible": nontrivial_feasible,
        },
        "errors": {
            "component": component_errors,
            "class": class_errors,
        },
        "adversarial_control": {
            "mutation": (
                "increment one nonidentity value in a valid nontrivial "
                "333-cocycle"
            ),
            "rejected": mutation_rejected,
        },
        "inputs": {
            "census_sha256": file_digest(args.census),
            "source_subgroup_classification_sha256": file_digest(
                classification_path
            ),
            "source_master_status_sha256": file_digest(status_path),
        },
        "auditor_sha256": file_digest(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": status,
                "checks": checks,
                "counts": output["counts"],
                "errors": output["errors"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
