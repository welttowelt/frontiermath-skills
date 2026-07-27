#!/usr/bin/env python3
"""Classify coherent multiplier-with-translation actions at length 333."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections import Counter
from pathlib import Path
from typing import Iterable

from py39_compat import strict_zip

LENGTH = 333
CRT_FACTORS = (9, 37)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def units(modulus: int) -> tuple[int, ...]:
    return tuple(
        value
        for value in range(1, modulus)
        if math.gcd(value, modulus) == 1
    )


def generated_subgroup(
    generators: Iterable[int], modulus: int
) -> frozenset[int]:
    generators = tuple(value % modulus for value in generators)
    subgroup = {1}
    frontier = [1]
    while frontier:
        value = frontier.pop()
        for generator in generators:
            product = value * generator % modulus
            if product not in subgroup:
                subgroup.add(product)
                frontier.append(product)
    return frozenset(subgroup)


def cyclic_subgroup(value: int, modulus: int) -> frozenset[int]:
    return generated_subgroup((value,), modulus)


def all_subgroups(
    group_elements: Iterable[int], modulus: int
) -> list[frozenset[int]]:
    subgroups = {
        cyclic_subgroup(value, modulus) for value in group_elements
    }
    subgroups.add(frozenset({1}))
    changed = True
    while changed:
        changed = False
        current = tuple(subgroups)
        for left_index, left in enumerate(current):
            for right in current[left_index:]:
                joined = generated_subgroup(left | right, modulus)
                if joined not in subgroups:
                    subgroups.add(joined)
                    changed = True
    return sorted(subgroups, key=lambda group: (len(group), tuple(sorted(group))))


def minimal_generators(
    group: frozenset[int], modulus: int
) -> tuple[int, ...]:
    if group == frozenset({1}):
        return ()
    ordered = tuple(sorted(group))
    for value in ordered:
        if generated_subgroup((value,), modulus) == group:
            return (value,)
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            if generated_subgroup((left, right), modulus) == group:
                return (left, right)
    raise ValueError("unit subgroup unexpectedly needs more than two generators")


def enumerate_cocycles(
    group: frozenset[int],
    generators: tuple[int, ...],
    coefficient_modulus: int,
    action_modulus: int,
) -> list[tuple[int, ...]]:
    """Return every z with z(uv)=z(u)+u*z(v), aligned to sorted(group)."""

    ordered = tuple(sorted(group))
    if not generators:
        return [(0,)]
    cocycles: list[tuple[int, ...]] = []
    for generator_values in itertools.product(
        range(coefficient_modulus), repeat=len(generators)
    ):
        values = {1: 0}
        frontier = [1]
        consistent = True
        while frontier and consistent:
            left = frontier.pop()
            for generator, generator_value in strict_zip(
                generators, generator_values
            ):
                product = left * generator % action_modulus
                candidate = (
                    values[left]
                    + (left % coefficient_modulus) * generator_value
                ) % coefficient_modulus
                if product in values:
                    if values[product] != candidate:
                        consistent = False
                        break
                else:
                    values[product] = candidate
                    frontier.append(product)
        if consistent and len(values) == len(group):
            cocycles.append(tuple(values[value] for value in ordered))
    return sorted(set(cocycles))


def quotient_by_coboundaries(
    group: frozenset[int],
    cocycles: Iterable[tuple[int, ...]],
    coefficient_modulus: int,
) -> tuple[list[tuple[int, ...]], set[tuple[int, ...]]]:
    ordered = tuple(sorted(group))
    coboundaries = {
        tuple(
            (1 - value) * shift % coefficient_modulus
            for value in ordered
        )
        for shift in range(coefficient_modulus)
    }
    unseen = set(cocycles)
    representatives: list[tuple[int, ...]] = []
    while unseen:
        representative = min(unseen)
        coset = {
            tuple(
                (left + right) % coefficient_modulus
                for left, right in strict_zip(representative, coboundary)
            )
            for coboundary in coboundaries
        }
        if not coset <= unseen | (set(cocycles) - unseen):
            raise ValueError("coboundary coset left the cocycle group")
        unseen.difference_update(coset)
        representatives.append(min(coset))
    return sorted(representatives), coboundaries


def crt_9_37(residue_9: int, residue_37: int) -> int:
    multiplier = (
        (residue_37 - residue_9) * pow(9, -1, 37)
    ) % 37
    result = (residue_9 + 9 * multiplier) % LENGTH
    if result % 9 != residue_9 or result % 37 != residue_37:
        raise ValueError("CRT reconstruction failed")
    return result


def affine_orbits(
    group: frozenset[int], cocycle: tuple[int, ...]
) -> list[list[int]]:
    ordered = tuple(sorted(group))
    if len(ordered) != len(cocycle):
        raise ValueError("cocycle length does not match group")
    offsets = dict(strict_zip(ordered, cocycle))
    unseen = set(range(LENGTH))
    orbits: list[list[int]] = []
    while unseen:
        start = min(unseen)
        orbit = {
            (value * start + offsets[value]) % LENGTH
            for value in ordered
        }
        if start not in orbit:
            raise ValueError("affine orbit omitted its seed")
        unseen.difference_update(orbit)
        orbits.append(sorted(orbit))
    return sorted(orbits, key=lambda orbit: (len(orbit), orbit[0]))


def orbit_signature(orbits: Iterable[Iterable[int]]) -> list[list[int]]:
    counts = Counter(len(tuple(orbit)) for orbit in orbits)
    return [[size, counts[size]] for size in sorted(counts)]


def row_sum_one_feasible(orbits: Iterable[Iterable[int]]) -> bool:
    """A +/-1 sequence of length 333 has row sum +/-1 iff 166 orbits are -1."""

    attainable = 1
    for orbit in orbits:
        attainable |= attainable << len(tuple(orbit))
    return bool((attainable >> 166) & 1)


def classify_subgroup(
    subgroup_id: int,
    group: frozenset[int],
    source_by_elements: dict[tuple[int, ...], dict[str, object]],
) -> dict[str, object]:
    ordered = tuple(sorted(group))
    generators = minimal_generators(group, LENGTH)
    component: dict[int, dict[str, object]] = {}
    representatives: dict[int, list[tuple[int, ...]]] = {}
    for modulus in CRT_FACTORS:
        cocycles = enumerate_cocycles(
            group, generators, modulus, LENGTH
        )
        quotient, coboundaries = quotient_by_coboundaries(
            group, cocycles, modulus
        )
        representatives[modulus] = quotient
        component[modulus] = {
            "cocycles": len(cocycles),
            "coboundaries": len(coboundaries),
            "cohomology_classes": len(quotient),
        }

    classes = []
    for class_id, (class_9, class_37) in enumerate(
        itertools.product(representatives[9], representatives[37])
    ):
        cocycle = tuple(
            crt_9_37(residue_9, residue_37)
            for residue_9, residue_37 in strict_zip(class_9, class_37)
        )
        orbits = affine_orbits(group, cocycle)
        sizes = [len(orbit) for orbit in orbits]
        nontrivial = any(cocycle)
        classes.append(
            {
                "class_id": class_id,
                "nontrivial_cohomology_class": nontrivial,
                "cocycle_mod333": list(cocycle),
                "orbit_signature": orbit_signature(orbits),
                "orbit_size_gcd": math.gcd(*sizes),
                "row_sum_plus_or_minus_one_feasible": (
                    row_sum_one_feasible(orbits)
                ),
            }
        )

    source = source_by_elements.get(ordered)
    record: dict[str, object] = {
        "subgroup_id": subgroup_id,
        "order": len(group),
        "elements": list(ordered),
        "generators": list(generators),
        "contained_in_kernel_mod3": all(value % 3 == 1 for value in group),
        "fixed_orbit_signature": orbit_signature(
            affine_orbits(group, (0,) * len(group))
        ),
        "components": {
            "mod9": component[9],
            "mod37": component[37],
        },
        "affine_conjugacy_classes": classes,
    }
    if source is not None:
        record["source_fixed_family"] = source
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    classification_path = (
        args.source_repo / "lp333" / "results"
        / "subgroup_classification.json"
    )
    status_path = (
        args.source_repo / "lp333" / "results" / "master_status.json"
    )
    source_classification = json.loads(
        classification_path.read_text(encoding="utf-8")
    )
    source_status = json.loads(status_path.read_text(encoding="utf-8"))
    status_by_id = {
        record["id"]: record for record in source_status["families"]
    }
    source_by_elements = {
        tuple(record["elements"]): {
            "family_id": record["id"],
            "status": status_by_id[record["id"]]["status"],
            "method": status_by_id[record["id"]]["method"],
        }
        for record in source_classification["subgroups"]
    }

    unit_group = units(LENGTH)
    subgroups = all_subgroups(unit_group, LENGTH)
    records = [
        classify_subgroup(index, group, source_by_elements)
        for index, group in enumerate(subgroups)
    ]
    all_classes = [
        affine_class
        for record in records
        for affine_class in record["affine_conjugacy_classes"]
    ]
    nontrivial = [
        affine_class
        for affine_class in all_classes
        if affine_class["nontrivial_cohomology_class"]
    ]
    nontrivial_feasible = [
        affine_class
        for affine_class in nontrivial
        if affine_class["row_sum_plus_or_minus_one_feasible"]
    ]
    source_records = [
        record for record in records if "source_fixed_family" in record
    ]
    source_impossible = [
        record
        for record in source_records
        if record["source_fixed_family"]["status"] == "IMPOSSIBLE"
    ]
    source_open = [
        record
        for record in source_records
        if record["source_fixed_family"]["status"] == "OPEN"
    ]
    checks = {
        "unit_group_order_216": len(unit_group) == 216,
        "all_unit_subgroups_80": len(subgroups) == 80,
        "all_affine_classes_134": len(all_classes) == 134,
        "nontrivial_affine_classes_54": len(nontrivial) == 54,
        "mod37_cohomology_trivial_for_every_subgroup": all(
            record["components"]["mod37"]["cohomology_classes"] == 1
            for record in records
        ),
        "every_nontrivial_class_has_cycle_gcd_divisible_by_3": all(
            affine_class["orbit_size_gcd"] % 3 == 0
            for affine_class in nontrivial
        ),
        "no_nontrivial_class_supports_row_sum_plus_or_minus_one": (
            not nontrivial_feasible
        ),
        "source_kernel_subgroups_30": len(source_records) == 30,
        "source_impossible_21": len(source_impossible) == 21,
        "source_open_9": len(source_open) == 9,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": (
            "frontiermath-hadamard-lp333-affine-multiplier-"
            "normalization-v1"
        ),
        "status": status,
        "theorem": (
            "For every subgroup H of (Z/333Z)^*, every coherent affine "
            "H-action whose invariant +/-1 sequence can have row sum +/-1 "
            "is a coboundary, hence a cyclic shift conjugates it to fixed "
            "multiplication by H."
        ),
        "legendre_pair_consequence": (
            "The two sequences may be shifted independently without changing "
            "their PAFs. Therefore a common coherent multiplier-with-"
            "translation subgroup for an LP(333) normalizes to a fixed common "
            "multiplier subgroup. The 21 source IMPOSSIBLE families extend "
            "to coherent affine translations; the nine source OPEN families "
            "remain open."
        ),
        "claim_boundary": (
            "This classifies coherent affine multiplier symmetry only. It "
            "does not decide any of the nine open fixed families, unrestricted "
            "LP(333), or H(668)."
        ),
        "method": {
            "affine_action": "i -> h*i + z(h) mod 333",
            "cocycle_identity": "z(hk)=z(h)+h*z(k)",
            "translation_coboundary": "z_s(h)=(1-h)*s",
            "crt_split": [9, 37],
            "row_sum_test": (
                "exact subset sum over affine orbit sizes for 166 negative "
                "positions; complement covers row sum -1"
            ),
        },
        "summary": {
            "units": len(unit_group),
            "subgroups": len(subgroups),
            "affine_cohomology_classes": len(all_classes),
            "trivial_classes": len(all_classes) - len(nontrivial),
            "nontrivial_classes": len(nontrivial),
            "nontrivial_row_sum_feasible_classes": len(
                nontrivial_feasible
            ),
            "source_kernel_subgroups": len(source_records),
            "source_impossible_families_extended": sorted(
                record["source_fixed_family"]["family_id"]
                for record in source_impossible
            ),
            "source_open_families_unchanged": sorted(
                record["source_fixed_family"]["family_id"]
                for record in source_open
            ),
        },
        "checks": checks,
        "subgroups": records,
        "inputs": {
            "source_subgroup_classification": str(classification_path),
            "source_subgroup_classification_sha256": sha256_file(
                classification_path
            ),
            "source_master_status": str(status_path),
            "source_master_status_sha256": sha256_file(status_path),
        },
        "source_sha256": sha256_file(Path(__file__).resolve()),
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
                "summary": output["summary"],
                "checks": checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
