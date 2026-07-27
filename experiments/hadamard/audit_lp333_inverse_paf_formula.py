#!/usr/bin/env python3
"""Independently audit the LP333 inverse-PAF quotient without encoder imports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


LENGTH = 333


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def orbits(elements: list[int]) -> list[list[int]]:
    unseen = set(range(LENGTH))
    result = []
    while unseen:
        seed = min(unseen)
        orbit = sorted({(unit * seed) % LENGTH for unit in elements})
        unseen.difference_update(orbit)
        result.append(orbit)
    result.sort(key=lambda orbit: (len(orbit), orbit[0]))
    return result


def paf_row(
    orbit_list: list[list[int]], index: list[int], shift: int
) -> tuple[int, tuple[tuple[int, ...], ...]]:
    count = len(orbit_list)
    directed = [[0] * count for _ in range(count)]
    for position in range(LENGTH):
        directed[index[position]][index[(position + shift) % LENGTH]] += 1
    diagonal = sum(directed[item][item] for item in range(count))
    matrix = [[0] * count for _ in range(count)]
    for left in range(count):
        for right in range(left + 1, count):
            value = directed[left][right] + directed[right][left]
            matrix[left][right] = value
            matrix[right][left] = value
    return diagonal, tuple(tuple(row) for row in matrix)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite {args.output}")

    metadata = json.loads(args.metadata.read_text())
    dedup = metadata["paf_inverse_deduplication"]
    if not dedup.get("enabled"):
        raise ValueError("metadata does not enable inverse PAF deduplication")
    orbit_list = orbits(metadata["subgroup"]["elements"])
    if orbit_list != metadata["subgroup"]["orbits"]:
        raise ValueError("independent subgroup orbits differ from metadata")
    index = [0] * LENGTH
    for orbit_index, orbit in enumerate(orbit_list):
        for position in orbit:
            index[position] = orbit_index
    representatives = [orbit[0] for orbit in orbit_list[1:]]
    if len(representatives) != dedup["original_representatives"]:
        raise ValueError("original representative count mismatch")

    rows: dict[int, tuple[int, tuple[tuple[int, ...], ...]]] = {}
    checked_position_pairs = 0
    independently_derived_classes = []
    covered = set()
    for original_index, shift in enumerate(representatives):
        if original_index in covered:
            continue
        inverse_index = index[(-shift) % LENGTH] - 1
        members = sorted({original_index, inverse_index})
        if len(members) != 2:
            raise ValueError("inverse class is not a pair")
        for member in members:
            rows.setdefault(
                member,
                paf_row(orbit_list, index, representatives[member]),
            )
            checked_position_pairs += LENGTH
        if rows[members[0]] != rows[members[1]]:
            raise ValueError("directly recomputed inverse rows differ")
        independently_derived_classes.append(
            {
                "original_indices": members,
                "shifts": [representatives[member] for member in members],
                "retained_original_index": members[0],
                "diagonal_constant": rows[members[0]][0],
            }
        )
        covered.update(members)

    expected_classes = [
        {
            key: item[key]
            for key in (
                "original_indices",
                "shifts",
                "retained_original_index",
                "diagonal_constant",
            )
        }
        for item in dedup["classes"]
    ]
    if independently_derived_classes != expected_classes:
        raise ValueError("independent inverse classes differ from metadata")
    if len(independently_derived_classes) != 56:
        raise ValueError("expected 56 inverse classes")

    formula = Path(metadata["cnf"]["path"])
    if sha256(formula) != metadata["cnf"]["sha256"]:
        raise ValueError("formula hash mismatch")
    with formula.open("r", encoding="ascii") as handle:
        header = handle.readline().split()
    if header != [
        "p",
        "cnf",
        str(metadata["cnf"]["variables"]),
        str(metadata["cnf"]["clauses"]),
    ]:
        raise ValueError("DIMACS header differs from metadata")

    result = {
        "schema": "frontiermath-hadamard-inverse-paf-audit-v1",
        "status": "pass",
        "family_id": metadata["family_id"],
        "formula_sha256": metadata["cnf"]["sha256"],
        "metadata_sha256": sha256(args.metadata),
        "checks": {
            "subgroup_orbits_recomputed": True,
            "all_original_representatives_covered": len(covered) == 112,
            "inverse_classes": len(independently_derived_classes),
            "class_sizes": {"2": len(independently_derived_classes)},
            "direct_position_pairs_counted": checked_position_pairs,
            "diagonal_constants_equal": True,
            "coefficient_matrices_equal": True,
            "metadata_classes_exact": True,
            "formula_header_bound": True,
        },
        "method": (
            "Directly count ordered position pairs for every retained and "
            "removed shift using only subgroup elements from metadata; do not "
            "import the generator or proof encoder."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
