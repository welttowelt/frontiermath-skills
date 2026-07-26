#!/usr/bin/env python3
"""Certify a direct PAF bound obstruction for one LP333 multiplier family."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any


LENGTH = 333
TARGET_COMBINED_PAF = -2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_family(
    source_repo: Path, family_id: int
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    classification_path = (
        source_repo / "lp333" / "results" / "subgroup_classification.json"
    )
    status_path = source_repo / "lp333" / "results" / "master_status.json"
    classification = json.loads(
        classification_path.read_text(encoding="utf-8")
    )
    statuses = json.loads(status_path.read_text(encoding="utf-8"))
    subgroup = next(
        record
        for record in classification["subgroups"]
        if record["id"] == family_id
    )
    status = next(
        record
        for record in statuses["families"]
        if record["id"] == family_id
    )
    return subgroup, status, classification_path, status_path


def validate_subgroup(elements: list[int]) -> None:
    values = set(elements)
    if 1 not in values or len(values) != len(elements):
        raise ValueError("subgroup identity or uniqueness failed")
    if any(math.gcd(value, LENGTH) != 1 for value in values):
        raise ValueError("subgroup contains a nonunit")
    if any(
        left * right % LENGTH not in values
        for left in values
        for right in values
    ):
        raise ValueError("subgroup is not closed")


def multiplication_orbits(elements: list[int]) -> list[list[int]]:
    unseen = set(range(LENGTH))
    orbits: list[list[int]] = []
    while unseen:
        seed = min(unseen)
        orbit = sorted({element * seed % LENGTH for element in elements})
        if not orbit or not set(orbit).issubset(unseen):
            raise ValueError("orbit construction is not a partition")
        orbits.append(orbit)
        unseen.difference_update(orbit)
    return orbits


def obstruction_record(
    orbit_index: list[int], shift: int
) -> dict[str, int]:
    diagonal = sum(
        orbit_index[position]
        == orbit_index[(position + shift) % LENGTH]
        for position in range(LENGTH)
    )
    off_diagonal = LENGTH - diagonal
    required_weighted_xor_sum = LENGTH + 1
    maximum_weighted_xor_sum = 2 * off_diagonal
    return {
        "shift": shift,
        "diagonal_constant_per_sequence": diagonal,
        "off_diagonal_coefficient_sum_per_sequence": off_diagonal,
        "required_weighted_xor_sum": required_weighted_xor_sum,
        "maximum_weighted_xor_sum": maximum_weighted_xor_sum,
        "shortfall": (
            required_weighted_xor_sum - maximum_weighted_xor_sum
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family-id", required=True, type=int)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    subgroup, source_status, classification_path, status_path = load_family(
        args.source_repo, args.family_id
    )
    elements = subgroup["elements"]
    validate_subgroup(elements)
    orbits = multiplication_orbits(elements)
    orbit_index = [-1] * LENGTH
    for index, orbit in enumerate(orbits):
        for position in orbit:
            if orbit_index[position] != -1:
                raise ValueError("orbits overlap")
            orbit_index[position] = index
    if any(index < 0 for index in orbit_index):
        raise ValueError("orbits do not cover Z/333Z")

    records = [
        obstruction_record(orbit_index, shift)
        for shift in range(1, LENGTH)
    ]
    obstructions = [
        record for record in records if record["shortfall"] > 0
    ]
    if not obstructions:
        raise ValueError("family has no direct PAF bound obstruction")

    output = {
        "schema": "frontiermath-lp333-direct-paf-obstruction-v1",
        "status": "exact-arithmetic-certified-infeasible",
        "family_id": args.family_id,
        "source_status_before_certificate": source_status["status"],
        "claim": (
            "No pair of +/-1 sequences invariant under the named multiplier "
            "subgroup can have combined nonzero PAF -2."
        ),
        "claim_boundary": (
            "This closes only the named fixed multiplier family and, through "
            "the separate affine-normalization theorem, its coherent "
            "translated versions. It does not decide unrestricted LP333 or "
            "H668."
        ),
        "subgroup": {
            "elements": elements,
            "order": len(elements),
            "orbit_count": len(orbits),
            "orbit_signature": {
                str(size): count
                for size, count in sorted(
                    Counter(map(len, orbits)).items()
                )
            },
        },
        "derivation": {
            "length": LENGTH,
            "target_combined_paf": TARGET_COMBINED_PAF,
            "identity": (
                "For one shift, PAF_A+PAF_B = "
                "2*diagonal + 2*off_diagonal - "
                "2*weighted_xor_sum. Setting this to -2 requires "
                "weighted_xor_sum = diagonal+off_diagonal+1 = 334."
            ),
            "bound": (
                "Each off-diagonal coefficient contributes at most one XOR "
                "bit per sequence, so weighted_xor_sum is at most "
                "2*off_diagonal."
            ),
            "obstructing_shifts": obstructions,
            "all_nonzero_shifts_checked": LENGTH - 1,
        },
        "inputs": {
            "subgroup_classification": str(classification_path),
            "subgroup_classification_sha256": sha256_file(
                classification_path
            ),
            "master_status": str(status_path),
            "master_status_sha256": sha256_file(status_path),
        },
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
