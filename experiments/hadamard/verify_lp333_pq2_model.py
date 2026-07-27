#!/usr/bin/env python3
"""Directly verify a SAT model for the prescribed pq2 LP333 slice."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import verify_lp333_family_model as base


EXPECTED_COMPRESSIONS = ([1, 11, -11], [1, -11, 11])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compression(sequence: list[int]) -> list[int]:
    return [
        sum(sequence[index] for index in range(residue, base.LENGTH, 3))
        for residue in range(3)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("--cnf", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    metadata = json.loads(args.encoding_metadata.read_text())
    if (
        metadata.get("schema")
        != "frontiermath-hadamard-lp333-pq2-cnf-v1"
        or metadata.get("family_id") != 0
    ):
        raise ValueError("metadata is not the unrestricted pq2 formula")
    if metadata["cnf"]["sha256"] != sha256(args.cnf):
        raise ValueError("CNF hash does not match pq2 metadata")
    assignments = base.parse_model(
        args.model, metadata["cnf"]["variables"]
    )
    cnf_check = base.stream_check_cnf(args.cnf, assignments)
    first_values = [
        -1 if assignments[variable] else 1
        for variable in metadata["primary_variables"]["za"]
    ]
    second_values = [
        -1 if assignments[variable] else 1
        for variable in metadata["primary_variables"]["zb"]
    ]
    first = base.sequence_from_orbits(
        metadata["subgroup"]["orbits"], first_values
    )
    second = base.sequence_from_orbits(
        metadata["subgroup"]["orbits"], second_values
    )
    direct = base.direct_checks(
        first, second, metadata["subgroup"]["elements"]
    )
    compressions = (compression(first), compression(second))
    negative_counts = [
        [
            sum(
                first[index] == -1
                for index in range(residue, base.LENGTH, 3)
            )
            for residue in range(3)
        ],
        [
            sum(
                second[index] == -1
                for index in range(residue, base.LENGTH, 3)
            )
            for residue in range(3)
        ],
    ]

    mutated = list(first)
    row_sum = sum(mutated)
    target_value = -row_sum
    position = next(
        index
        for index, value in enumerate(mutated)
        if value == target_value
    )
    original_compression = compression(mutated)
    mutated[position] *= -1
    mutated_direct = base.direct_checks(
        mutated, second, metadata["subgroup"]["elements"]
    )
    mutation_rejected = not mutated_direct["verified_legendre_pair"]
    checks = {
        "complete_model": True,
        "cnf_model_satisfied": cnf_check["satisfied"],
        "direct_full_lp333": direct["verified_legendre_pair"],
        "prescribed_compressions": (
            compressions == EXPECTED_COMPRESSIONS
        ),
        "prescribed_negative_counts": (
            negative_counts == [[55, 50, 61], [55, 61, 50]]
        ),
        "single_coordinate_mutation_changes_compression": (
            compression(mutated) != original_compression
        ),
        "single_coordinate_mutation_rejected": mutation_rejected,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-hadamard-lp333-pq2-model-audit-v1",
        "status": status,
        "family_id": 0,
        "scope": "unrestricted prescribed pq2-compression slice",
        "checks": checks,
        "cnf_check": cnf_check,
        "direct": direct,
        "compressions": compressions,
        "negative_counts": negative_counts,
        "mutation_control": {
            "mutation": (
                f"flipped A coordinate {position} chosen to force row sum "
                "outside +/-1"
            ),
            "compression_changed": (
                compression(mutated) != original_compression
            ),
            "rejected": mutation_rejected,
            "mutated_direct_checks": mutated_direct["checks"],
        },
        "candidate": {
            "a_sequence": first,
            "b_sequence": second,
            "a_primary_values": first_values,
            "b_primary_values": second_values,
        }
        if status == "pass"
        else None,
        "bindings": {
            "metadata_sha256": sha256(args.encoding_metadata),
            "model_sha256": sha256(args.model),
            "cnf_sha256": sha256(args.cnf),
            "verifier_sha256": sha256(Path(__file__).resolve()),
            "base_verifier_sha256": sha256(Path(base.__file__).resolve()),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
