#!/usr/bin/env python3
"""Audit an LP333 direct PAF obstruction through an alternate reconstruction."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any


LENGTH = 333


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def source_subgroup(source_repo: Path, family_id: int) -> tuple[dict[str, Any], Path]:
    path = (
        source_repo / "lp333" / "results" / "subgroup_classification.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    record = next(
        item for item in data["subgroups"] if item["id"] == family_id
    )
    return record, path


def subgroup_checks(elements: list[int]) -> dict[str, bool]:
    values = set(elements)
    return {
        "unique": len(values) == len(elements),
        "identity": 1 in values,
        "all_units": all(
            math.gcd(value, LENGTH) == 1 for value in values
        ),
        "closure": all(
            left * right % LENGTH in values
            for left in values
            for right in values
        ),
    }


def union_find_signature(elements: list[int]) -> tuple[dict[str, int], int]:
    partition = DisjointSet(LENGTH)
    for position in range(LENGTH):
        for multiplier in elements:
            partition.union(position, multiplier * position % LENGTH)
    sizes = Counter(
        Counter(partition.find(position) for position in range(LENGTH)).values()
    )
    return (
        {str(size): count for size, count in sorted(sizes.items())},
        sum(sizes.values()),
    )


def direct_same_orbit_count(elements: list[int], shift: int) -> int:
    return sum(
        any(
            multiplier * position % LENGTH
            == (position + shift) % LENGTH
            for multiplier in elements
        )
        for position in range(LENGTH)
    )


def recompute_obstructions(elements: list[int]) -> list[dict[str, int]]:
    result = []
    for shift in range(1, LENGTH):
        diagonal = direct_same_orbit_count(elements, shift)
        off_diagonal = LENGTH - diagonal
        maximum = 2 * off_diagonal
        record = {
            "shift": shift,
            "diagonal_constant_per_sequence": diagonal,
            "off_diagonal_coefficient_sum_per_sequence": off_diagonal,
            "required_weighted_xor_sum": LENGTH + 1,
            "maximum_weighted_xor_sum": maximum,
            "shortfall": LENGTH + 1 - maximum,
        }
        if record["shortfall"] > 0:
            result.append(record)
    return result


def certificate_matches(
    certificate: dict[str, Any],
    elements: list[int],
    source_path: Path,
    family_id: int,
) -> bool:
    signature, orbit_count = union_find_signature(elements)
    return all(
        (
            certificate["family_id"] == family_id,
            certificate["status"]
            == "exact-arithmetic-certified-infeasible",
            certificate["subgroup"]["elements"] == elements,
            certificate["subgroup"]["order"] == len(elements),
            certificate["subgroup"]["orbit_count"] == orbit_count,
            certificate["subgroup"]["orbit_signature"] == signature,
            certificate["derivation"]["target_combined_paf"] == -2,
            certificate["derivation"]["all_nonzero_shifts_checked"]
            == LENGTH - 1,
            certificate["derivation"]["obstructing_shifts"]
            == recompute_obstructions(elements),
            certificate["inputs"]["subgroup_classification_sha256"]
            == sha256_file(source_path),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("certificate", type=Path)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    certificate = json.loads(
        args.certificate.read_text(encoding="utf-8")
    )
    family_id = certificate["family_id"]
    source, source_path = source_subgroup(args.source_repo, family_id)
    elements = source["elements"]
    group = subgroup_checks(elements)
    exact_match = certificate_matches(
        certificate, elements, source_path, family_id
    )

    mutated = deepcopy(certificate)
    mutated["derivation"]["obstructing_shifts"][0]["shortfall"] += 1
    mutation_rejected = not certificate_matches(
        mutated, elements, source_path, family_id
    )
    checks = {
        "source_subgroup_group_axioms": all(group.values()),
        "alternate_union_find_orbit_signature": exact_match,
        "direct_same_orbit_counts_all_shifts": exact_match,
        "weighted_xor_bound_recomputed": exact_match,
        "one_unit_shortfall_mutation_rejected": mutation_rejected,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-lp333-direct-paf-obstruction-audit-v1",
        "status": status,
        "family_id": family_id,
        "checks": checks,
        "subgroup_checks": group,
        "obstructing_shifts": recompute_obstructions(elements),
        "independent_path": (
            "The audit does not import the proof encoder or certificate "
            "generator. It reconstructs orbits with union-find and counts "
            "same-orbit shifted positions directly from the group action."
        ),
        "mutation_control": {
            "change": "incremented the first recorded shortfall by one",
            "rejected": mutation_rejected,
        },
        "inputs": {
            "certificate_sha256": sha256_file(args.certificate),
            "subgroup_classification_sha256": sha256_file(source_path),
        },
        "auditor_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
