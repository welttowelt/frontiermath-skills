#!/usr/bin/env python3
"""Independently reconstruct and audit the LP333 unary cardinality channels."""

from __future__ import annotations

import argparse
from collections import Counter
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
) -> tuple[int, list[list[int]]]:
    count = len(orbit_list)
    directed = [[0] * count for _ in range(count)]
    for position in range(LENGTH):
        directed[index[position]][index[(position + shift) % LENGTH]] += 1
    diagonal = sum(directed[item][item] for item in range(count))
    matrix = [[0] * count for _ in range(count)]
    for left in range(count):
        for right in range(left + 1, count):
            matrix[left][right] = (
                directed[left][right] + directed[right][left]
            )
            matrix[right][left] = matrix[left][right]
    return diagonal, matrix


def reconstruct_channel(
    inputs: list[int], target: int, start_variable: int
) -> tuple[list[tuple[int, ...]], int]:
    size = len(inputs)
    max_threshold = min(size, target + 1)
    next_variable = start_variable
    rows = []
    for prefix in range(size):
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
    if target:
        clauses.append((rows[-1][target - 1],))
    if target < size:
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
    channels = metadata["unary_cardinality_channels"]
    if not channels.get("enabled"):
        raise ValueError("metadata does not enable unary channels")
    if metadata["paf_inverse_deduplication"]["enabled"] if "paf_inverse_deduplication" in metadata else False:
        raise ValueError("unary experiment unexpectedly deduplicates PAF rows")

    orbit_list = orbits(metadata["subgroup"]["elements"])
    if orbit_list != metadata["subgroup"]["orbits"]:
        raise ValueError("independent orbits differ from metadata")
    index = [0] * LENGTH
    for orbit_index, orbit in enumerate(orbit_list):
        for position in orbit:
            index[position] = orbit_index
    triple_indices = [
        orbit_index
        for orbit_index, orbit in enumerate(orbit_list)
        if len(orbit) == 3
    ]
    if len(triple_indices) != 110:
        raise ValueError("expected 110 size-three orbits")

    implication = channels["arithmetic_implication"]
    diagonal, matrix = paf_row(orbit_list, index, 111)
    histogram: Counter[int] = Counter()
    singleton_pairs = []
    triple_pairs = []
    for left in range(len(orbit_list)):
        for right in range(left + 1, len(orbit_list)):
            coefficient = matrix[left][right]
            if coefficient:
                histogram[coefficient] += 1
            if coefficient == 1:
                singleton_pairs.append([left, right])
            elif coefficient == 3:
                triple_pairs.append([left, right])
            elif coefficient:
                raise ValueError("unexpected shift-111 coefficient")
    if (
        diagonal != 6
        or dict(sorted(histogram.items()))
        != {int(key): value for key, value in implication["coefficient_histogram"].items()}
        or singleton_pairs != implication["singleton_pairs"]
        or triple_pairs != implication["triple_edge_pairs"]
    ):
        raise ValueError("raw shift-111 decomposition differs from metadata")
    if (334 - 4) // 3 != 110 or (334 - 4) % 3:
        raise ValueError("shift-111 cardinality implication failed")
    row_cases = [
        (singleton_negatives, triple_negatives, weighted)
        for singleton_negatives in range(3)
        for triple_negatives in range(111)
        for weighted in [singleton_negatives + 3 * triple_negatives]
        if weighted in (166, 167)
    ]
    gauge_cases = [case for case in row_cases if case[0] == 1]
    if gauge_cases != [(1, 55, 166)]:
        raise ValueError("row cardinality implication failed")

    records = channels["channels"]
    za = metadata["primary_variables"]["za"]
    zb = metadata["primary_variables"]["zb"]
    if records[0]["inputs"] != [za[item] for item in triple_indices]:
        raise ValueError("A channel inputs differ from size-three orbit vars")
    if records[1]["inputs"] != [zb[item] for item in triple_indices]:
        raise ValueError("B channel inputs differ from size-three orbit vars")
    if [record["target"] for record in records] != [55, 55, 110]:
        raise ValueError("channel targets differ from preregistration")

    source_clauses: list[tuple[int, tuple[int, ...]]] = []
    next_variable = channels["block_start_variable"]
    for record in records:
        if record["start_variable"] != next_variable:
            raise ValueError("channel auxiliary allocation is not contiguous")
        clauses, next_variable = reconstruct_channel(
            record["inputs"], record["target"], next_variable
        )
        expected_start = (
            channels["block_source_clause_start"]
            if not source_clauses
            else source_clauses[-1][0] + 1
        )
        if expected_start != record["source_clause_start"]:
            raise ValueError("channel source clause start mismatch")
        for offset, clause in enumerate(clauses):
            source_clauses.append((expected_start + offset, clause))
        if source_clauses[-1][0] != record["source_clause_end"]:
            raise ValueError("channel source clause end mismatch")
    if (
        next_variable
        != channels["block_start_variable"]
        + channels["block_auxiliary_variables"]
        or len(source_clauses) != channels["block_source_clauses"]
    ):
        raise ValueError("channel block dimensions differ")

    split_by_source = {
        item["source_clause_index"]: item
        for item in channels["serialized_unit_gadgets"]
    }
    expected_serialized = []
    for source_index, clause in source_clauses:
        if source_index in split_by_source:
            gadget = split_by_source[source_index]
            if len(clause) != 1 or gadget["source_literal"] != clause[0]:
                raise ValueError("unit gadget source mismatch")
            expected_serialized.extend(
                [
                    (clause[0], gadget["mask_variable"]),
                    (clause[0], -gadget["mask_variable"]),
                ]
            )
        else:
            expected_serialized.append(clause)
    if len(expected_serialized) != channels["serialized_clauses"]:
        raise ValueError("serialized block clause count mismatch")

    formula = Path(metadata["cnf"]["path"])
    if sha256(formula) != metadata["cnf"]["sha256"]:
        raise ValueError("formula hash mismatch")
    required_xor_clauses = set()
    edge_inputs = records[2]["inputs"]
    if len(edge_inputs) != 216:
        raise ValueError("edge channel does not have 216 inputs")
    for sequence_index, primary in enumerate((za, zb)):
        offset = sequence_index * len(triple_pairs)
        for pair_index, (left, right) in enumerate(triple_pairs):
            output = edge_inputs[offset + pair_index]
            left_var = primary[left]
            right_var = primary[right]
            required_xor_clauses.update(
                {
                    (-left_var, -right_var, -output),
                    (left_var, right_var, -output),
                    (-left_var, right_var, output),
                    (left_var, -right_var, output),
                }
            )

    actual_block = []
    found_xor_clauses = set()
    serialized_start = channels["serialized_clause_start"]
    serialized_end = serialized_start + channels["serialized_clauses"] - 1
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
            clause = parse_clause(line)
            if clause in required_xor_clauses:
                found_xor_clauses.add(clause)
            if serialized_start <= clause_number <= serialized_end:
                actual_block.append(clause)
    if found_xor_clauses != required_xor_clauses:
        raise ValueError("edge-channel inputs lack exact XOR definitions")
    if actual_block != expected_serialized:
        raise ValueError("serialized channel block differs from reconstruction")
    digest = hashlib.sha256()
    for clause in actual_block:
        digest.update(
            (" ".join(map(str, clause)) + " 0\n").encode("ascii")
        )
    if digest.hexdigest() != channels["serialized_block_sha256"]:
        raise ValueError("serialized channel block hash mismatch")
    mutation = list(expected_serialized)
    mutation[0] = (-mutation[0][0],) + mutation[0][1:]
    if mutation == actual_block:
        raise ValueError("one-literal channel mutation was not rejected")

    parent = metadata["controls"]["parent_formula_binding"]
    parent_path = Path(parent["path"])
    if (
        sha256(parent_path) != parent["metadata_sha256"]
        or json.loads(parent_path.read_text())["cnf"]["sha256"]
        != parent["formula_sha256"]
    ):
        raise ValueError("parent formula binding failed")
    result = {
        "schema": "frontiermath-hadamard-unary-channel-audit-v1",
        "status": "pass",
        "family_id": metadata["family_id"],
        "formula_sha256": metadata["cnf"]["sha256"],
        "metadata_sha256": sha256(args.metadata),
        "checks": {
            "row_cardinality_implications": 2,
            "shift111_cardinality_implication": True,
            "raw_position_pairs_counted": LENGTH,
            "coefficient_histogram": dict(sorted(histogram.items())),
            "channels_reconstructed": 3,
            "source_channel_clauses": len(source_clauses),
            "serialized_channel_clauses": len(actual_block),
            "xor_definition_clauses_checked": len(found_xor_clauses),
            "serialized_block_sha256": digest.hexdigest(),
            "one_literal_mutation_rejected": True,
            "parent_metadata_bound": True,
            "truth_table_control": metadata["controls"][
                "sequential_cardinality_truth_table"
            ]["result"],
        },
        "method": (
            "Recompute raw shift-111 coefficients and row cases, reconstruct "
            "the uniquely extended sequential counters, bind their XOR inputs, "
            "and compare the exact DIMACS block without importing the generator "
            "or proof encoder."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
