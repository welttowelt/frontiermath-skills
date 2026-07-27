#!/usr/bin/env python3
"""Independently reconstruct the unrestricted LP333 pq2 CNF additions."""

from __future__ import annotations

import argparse
import hashlib
from itertools import product
import json
import math
from pathlib import Path
from typing import Sequence


LENGTH = 333
COMPRESSED_LENGTH = 37
COMPRESSION_FACTOR = 9


def legendre_symbol_37(value: int) -> int:
    residue = value % COMPRESSED_LENGTH
    if residue == 0:
        return 0
    symbol = pow(residue, 18, COMPRESSED_LENGTH)
    if symbol == 1:
        return 1
    if symbol == 36:
        return -1
    raise ValueError("invalid Euler-criterion value")


COMPRESSED_ROWS = (
    tuple(
        1 if residue == 0 else 3 * legendre_symbol_37(residue)
        for residue in range(COMPRESSED_LENGTH)
    ),
    tuple(
        1 if residue == 0 else -3 * legendre_symbol_37(residue)
        for residue in range(COMPRESSED_LENGTH)
    ),
)
NEGATIVE_TARGETS = tuple(
    tuple((COMPRESSION_FACTOR - value) // 2 for value in row)
    for row in COMPRESSED_ROWS
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def independent_lex_clauses(
    variables: Sequence[int],
    mapping: Sequence[int],
    next_variable: int,
) -> tuple[list[tuple[int, ...]], int, int]:
    support = [
        index
        for index, (left, right) in enumerate(zip(variables, mapping))
        if left != right
    ]
    clauses: list[tuple[int, ...]] = []
    previous: int | None = None
    for support_index, position in enumerate(support):
        left = variables[position]
        right = mapping[position]
        clauses.append(
            (-left, right)
            if previous is None
            else (-previous, -left, right)
        )
        if support_index + 1 == len(support):
            continue
        prefix = next_variable
        next_variable += 1
        if previous is not None:
            clauses.append((-prefix, previous))
        clauses.extend(
            [
                (-prefix, -left, right),
                (-prefix, left, -right),
            ]
        )
        if previous is None:
            clauses.extend(
                [
                    (left, right, prefix),
                    (-left, -right, prefix),
                ]
            )
        else:
            clauses.extend(
                [
                    (-previous, left, right, prefix),
                    (-previous, -left, -right, prefix),
                ]
            )
        previous = prefix
    return clauses, next_variable, len(support)


def clauses_hold(
    clauses: Sequence[tuple[int, ...]], assignment: Sequence[bool]
) -> bool:
    return all(
        any(
            assignment[abs(literal)] == (literal > 0)
            for literal in clause
        )
        for clause in clauses
    )


def lex_truth_table() -> dict[str, int | str | bool]:
    variables = (1, 2, 3, 4)
    mapping = (2, 3, 4, 1)
    clauses, next_variable, _ = independent_lex_clauses(
        variables, mapping, 5
    )
    assignments = 0
    extensions = 0
    for primary in product((False, True), repeat=4):
        expected = tuple(primary) <= tuple(
            primary[variable - 1] for variable in mapping
        )
        satisfying = 0
        for auxiliary in product(
            (False, True), repeat=next_variable - 5
        ):
            assignment = [False] + list(primary) + list(auxiliary)
            satisfying += int(clauses_hold(clauses, assignment))
            extensions += 1
        if bool(satisfying) != expected or satisfying > 1:
            raise ValueError("independent lex truth table failed")
        assignments += 1
    return {
        "result": "PASS",
        "primary_assignments": assignments,
        "auxiliary_extensions": extensions,
        "functional_extensions": True,
    }


def reconstruct_counter(
    inputs: list[int], target: int, start_variable: int
) -> tuple[list[tuple[int, ...]], int]:
    max_threshold = min(len(inputs), target + 1)
    next_variable = start_variable
    rows = []
    for prefix in range(len(inputs)):
        row = []
        for _ in range(1, min(prefix + 1, max_threshold) + 1):
            row.append(next_variable)
            next_variable += 1
        rows.append(row)
    clauses: list[tuple[int, ...]] = []
    for prefix, literal in enumerate(inputs):
        for threshold_index, output in enumerate(rows[prefix]):
            threshold = threshold_index + 1
            if prefix == 0:
                clauses.extend([(-output, literal), (output, -literal)])
                continue
            previous = rows[prefix - 1]
            same = (
                previous[threshold_index]
                if threshold_index < len(previous)
                else None
            )
            lower = (
                previous[threshold_index - 1]
                if threshold_index > 0
                else None
            )
            if threshold == 1:
                clauses.extend(
                    [
                        (-same, output),
                        (-literal, output),
                        (-output, same, literal),
                    ]
                )
            elif same is None:
                clauses.extend(
                    [
                        (-literal, -lower, output),
                        (-output, literal),
                        (-output, lower),
                    ]
                )
            else:
                clauses.extend(
                    [
                        (-same, output),
                        (-literal, -lower, output),
                        (-output, same, literal),
                        (-output, same, lower),
                    ]
                )
    clauses.append((rows[-1][target - 1],))
    clauses.append((-rows[-1][target],))
    return clauses, next_variable


def parse_clause(line: str) -> tuple[int, ...]:
    values = tuple(int(item) for item in line.split())
    if not values or values[-1] != 0:
        raise ValueError("invalid DIMACS clause")
    return values[:-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite {args.output}")
    metadata = json.loads(args.metadata.read_text())
    if metadata["family_id"] != 0:
        raise ValueError("metadata is not the identity family")
    if metadata["subgroup"]["orbits"] != [
        [index] for index in range(LENGTH)
    ]:
        raise ValueError("identity-family singleton orbits differ")
    formula = Path(metadata["cnf"]["path"])
    if sha256(formula) != metadata["cnf"]["sha256"]:
        raise ValueError("formula hash mismatch")
    za = metadata["primary_variables"]["za"]
    zb = metadata["primary_variables"]["zb"]
    variables = tuple(za + zb)

    expected_lex: list[tuple[int, ...]] = []
    next_variable = (
        metadata["pq2_compression_channels"]["block_start_variable"]
        - metadata["symmetry"]["added_auxiliaries"]
    )
    reconstructed_breakers = []
    for unit in range(1, LENGTH):
        if math.gcd(unit, LENGTH) != 1:
            continue
        permutation = [(unit * index) % LENGTH for index in range(LENGTH)]
        swap = legendre_symbol_37(unit) == -1
        mapping = tuple(
            (
                [zb[permutation[index]] for index in range(LENGTH)]
                + [za[permutation[index]] for index in range(LENGTH)]
            )
            if swap
            else (
                [za[permutation[index]] for index in range(LENGTH)]
                + [zb[permutation[index]] for index in range(LENGTH)]
            )
        )
        if mapping == variables:
            continue
        clauses, next_variable, support = independent_lex_clauses(
            variables, mapping, next_variable
        )
        expected_lex.extend(clauses)
        reconstructed_breakers.append(
            {
                "unit": unit,
                "swap_sequences": swap,
                "support": support,
                "auxiliaries": support - 1,
                "clauses": len(clauses),
            }
        )
    symmetry = metadata["symmetry"]
    if (
        len(reconstructed_breakers) != 215
        or len(expected_lex) != symmetry["added_clauses"]
        or next_variable
        != metadata["pq2_compression_channels"]["block_start_variable"]
        or reconstructed_breakers != symmetry["breakers"]
    ):
        raise ValueError("pq2 symmetry reconstruction differs")

    channels = metadata["pq2_compression_channels"]
    expected_source: list[tuple[int, tuple[int, ...]]] = []
    next_variable = channels["block_start_variable"]
    records = channels["channels"]
    record_index = 0
    for row, primary in enumerate((za, zb)):
        for residue in range(COMPRESSED_LENGTH):
            record = records[record_index]
            record_index += 1
            inputs = list(primary[residue::COMPRESSED_LENGTH])
            target = NEGATIVE_TARGETS[row][residue]
            if (
                record["inputs"] != inputs
                or record["target"] != target
                or record["start_variable"] != next_variable
            ):
                raise ValueError("pq2 counter binding differs")
            clauses, next_variable = reconstruct_counter(
                inputs, target, next_variable
            )
            start = record["source_clause_start"]
            if (
                len(clauses) != record["source_clauses"]
                or start + len(clauses) - 1
                != record["source_clause_end"]
            ):
                raise ValueError("pq2 counter dimensions differ")
            expected_source.extend(
                (start + offset, clause)
                for offset, clause in enumerate(clauses)
            )
    if (
        next_variable
        != channels["block_start_variable"]
        + channels["block_auxiliary_variables"]
        or len(expected_source) != channels["block_source_clauses"]
    ):
        raise ValueError("pq2 channel block dimensions differ")
    split_by_source = {
        item["source_clause_index"]: item
        for item in channels["serialized_unit_gadgets"]
    }
    expected_channels = []
    for source_index, clause in expected_source:
        if source_index in split_by_source:
            gadget = split_by_source[source_index]
            if len(clause) != 1 or gadget["source_literal"] != clause[0]:
                raise ValueError("pq2 unit-split binding differs")
            expected_channels.extend(
                [
                    (clause[0], gadget["mask_variable"]),
                    (clause[0], -gadget["mask_variable"]),
                ]
            )
        else:
            expected_channels.append(clause)
    if len(expected_channels) != channels["serialized_clauses"]:
        raise ValueError("serialized pq2 channel size differs")

    lex_start = channels["serialized_clause_start"] - len(expected_lex)
    lex_end = channels["serialized_clause_start"] - 1
    channel_end = (
        channels["serialized_clause_start"]
        + channels["serialized_clauses"]
        - 1
    )
    actual_lex = []
    actual_channels = []
    with formula.open("r", encoding="ascii") as handle:
        header = handle.readline().split()
        if header != [
            "p",
            "cnf",
            str(metadata["cnf"]["variables"]),
            str(metadata["cnf"]["clauses"]),
        ]:
            raise ValueError("DIMACS header mismatch")
        for clause_number, line in enumerate(handle, start=1):
            if lex_start <= clause_number <= lex_end:
                actual_lex.append(parse_clause(line))
            if (
                channels["serialized_clause_start"]
                <= clause_number
                <= channel_end
            ):
                actual_channels.append(parse_clause(line))
    if actual_lex != expected_lex:
        raise ValueError("serialized pq2 symmetry block differs")
    if actual_channels != expected_channels:
        raise ValueError("serialized pq2 channel block differs")
    digest = hashlib.sha256()
    for clause in actual_channels:
        digest.update(
            (" ".join(map(str, clause)) + " 0\n").encode("ascii")
        )
    if digest.hexdigest() != channels["serialized_block_sha256"]:
        raise ValueError("pq2 channel block hash differs")
    mutated = list(expected_channels)
    mutated[0] = (-mutated[0][0],) + mutated[0][1:]
    if mutated == actual_channels:
        raise ValueError("one-literal channel mutation was not rejected")

    controls = metadata["controls"]
    compressed_combined_paf = [
        sum(
            sum(
                row[index]
                * row[(index + shift) % COMPRESSED_LENGTH]
                for index in range(COMPRESSED_LENGTH)
            )
            for row in COMPRESSED_ROWS
        )
        for shift in range(COMPRESSED_LENGTH)
    ]
    if (
        controls["compressed_seed_identity"]["result"] != "PASS"
        or controls["pq2_symmetry_action"]["result"] != "PASS"
        or controls["sequential_cardinality_truth_table"]["result"]
        != "PASS"
        or controls["random_semantic_cnf_equivalence"]["result"]
        != "PASS"
        or controls["direct_full_length_semantic_equivalence"]["result"]
        != "PASS"
    ):
        raise ValueError("generator semantic controls are incomplete")
    if (
        metadata["pq2_compression_channels"]["compressed_rows"]
        != [list(row) for row in COMPRESSED_ROWS]
        or compressed_combined_paf[0] != 650
        or any(
            value != -18 for value in compressed_combined_paf[1:]
        )
    ):
        raise ValueError("compressed pq2 seed identity differs")
    result = {
        "schema": "frontiermath-hadamard-lp333-pq2-cnf-audit-v1",
        "status": "pass",
        "family_id": 0,
        "formula_sha256": metadata["cnf"]["sha256"],
        "metadata_sha256": sha256(args.metadata),
        "checks": {
            "singleton_orbits": LENGTH,
            "factorization": "333 = 37 * 3^2",
            "pq2_compressed_rows": [
                list(row) for row in COMPRESSED_ROWS
            ],
            "pq2_negative_targets": [
                list(targets) for targets in NEGATIVE_TARGETS
            ],
            "compressed_combined_paf": compressed_combined_paf,
            "symmetry_actions": 216,
            "symmetry_breakers_reconstructed": len(
                reconstructed_breakers
            ),
            "symmetry_clauses_reconstructed": len(actual_lex),
            "channels_reconstructed": len(records),
            "source_channel_clauses": len(expected_source),
            "serialized_channel_clauses": len(actual_channels),
            "serialized_channel_sha256": digest.hexdigest(),
            "one_literal_mutation_rejected": True,
            "lex_truth_table": lex_truth_table(),
        },
        "method": (
            "Reconstruct all 216 compression-preserving unit actions, every "
            "lex-leader clause, and all six sequential exact-cardinality "
            "counters directly from arithmetic, then compare the exact "
            "serialized DIMACS blocks without importing either generator."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
