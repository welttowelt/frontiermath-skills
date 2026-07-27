#!/usr/bin/env python3
"""Independently audit the ID3 singleton-to-triple unary row channel."""

from __future__ import annotations

import argparse
import hashlib
from itertools import product
import json
from pathlib import Path


LENGTH = 333
EXPECTED_PARENT_FORMULA_SHA256 = (
    "0ea4f87736db6d1076214d8378e4f66e1fe499291d5f4d0d406209a7779172b8"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_translate(
    pattern: tuple[int, ...], offset: int
) -> tuple[int, ...]:
    return tuple(
        pattern[(index + offset) % len(pattern)] ^ pattern[offset]
        for index in range(len(pattern))
    )


def reconstruct_prefix_counter(
    inputs: list[int], max_threshold: int, start_variable: int
) -> tuple[list[tuple[int, ...]], int, list[int]]:
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
                if same is None:
                    raise AssertionError("missing threshold-one predecessor")
                clauses.extend(
                    [
                        (-same, output),
                        (-literal, output),
                        (-output, same, literal),
                    ]
                )
            elif same is None:
                if lower is None:
                    raise AssertionError("missing lower predecessor")
                clauses.extend(
                    [
                        (-literal, -lower, output),
                        (-output, literal),
                        (-output, lower),
                    ]
                )
            else:
                if lower is None:
                    raise AssertionError("missing lower predecessor")
                clauses.extend(
                    [
                        (-same, output),
                        (-literal, -lower, output),
                        (-output, same, literal),
                        (-output, same, lower),
                    ]
                )
    return clauses, next_variable, rows[-1]


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
    block = metadata["id3_singleton_triple_unary_channel"]
    if metadata["family_id"] != 3 or not block["enabled"]:
        raise ValueError("metadata does not enable the ID3 channel")

    orbit_list = metadata["subgroup"]["orbits"]
    singleton_indices = [
        index for index, orbit in enumerate(orbit_list) if len(orbit) == 1
    ]
    triple_indices = [
        index for index, orbit in enumerate(orbit_list) if len(orbit) == 3
    ]
    if len(singleton_indices) != 9 or len(triple_indices) != 108:
        raise ValueError("ID3 orbit signature differs")

    patterns = [(0,) + suffix for suffix in product((0, 1), repeat=8)]
    orbit_by_pattern = {}
    unique_orbits = set()
    for pattern in patterns:
        orbit = tuple(
            sorted(
                {
                    normalized_translate(pattern, offset)
                    for offset in range(9)
                }
            )
        )
        orbit_by_pattern[pattern] = orbit
        unique_orbits.add(orbit)
    canonical = sorted(min(orbit) for orbit in unique_orbits)
    row_case_by_pattern = {}
    for pattern in patterns:
        cases = [
            (triple_count, sum(pattern) + 3 * triple_count)
            for triple_count in range(109)
            if sum(pattern) + 3 * triple_count in (166, 167)
        ]
        if cases:
            row_case_by_pattern[pattern] = cases
    feasible = [
        pattern for pattern in canonical if pattern in row_case_by_pattern
    ]
    infeasible = [
        pattern for pattern in canonical if pattern not in row_case_by_pattern
    ]
    if len(feasible) != 19 or len(infeasible) != 11:
        raise ValueError("canonical row-case partition differs")
    pattern_cases = []
    for pattern in feasible:
        cases = row_case_by_pattern[pattern]
        if len(cases) != 1:
            raise ValueError("canonical row case is not unique")
        triple_count, weighted = cases[0]
        pattern_cases.append(
            {
                "pattern": list(pattern),
                "singleton_negative_count": sum(pattern),
                "triple_negative_orbits": triple_count,
                "weighted_negative_count": weighted,
            }
        )
    allowed_pairs = sorted(
        {
            (
                record["singleton_negative_count"],
                record["triple_negative_orbits"],
            )
            for record in pattern_cases
        }
    )
    if allowed_pairs != [(1, 55), (2, 55), (4, 54), (5, 54)]:
        raise ValueError("independent row arithmetic implication failed")
    if (
        block["canonical_feasible_patterns"]
        != [list(pattern) for pattern in feasible]
        or block["canonical_infeasible_patterns"]
        != [list(pattern) for pattern in infeasible]
        or block["pattern_cases"] != pattern_cases
        or block["allowed_singleton_triple_count_pairs"]
        != [list(pair) for pair in allowed_pairs]
    ):
        raise ValueError("metadata row cases differ from reconstruction")

    za = metadata["primary_variables"]["za"]
    zb = metadata["primary_variables"]["zb"]
    expected_clauses: list[tuple[int, ...]] = []
    next_variable = block["block_start_variable"]
    for record, primary in zip(block["sequence_records"], (za, zb)):
        singleton_variables = [
            primary[index] for index in singleton_indices
        ]
        triple_variables = [primary[index] for index in triple_indices]
        if (
            record["singleton_variables"] != singleton_variables
            or record["triple_variables"] != triple_variables
        ):
            raise ValueError("channel primary-variable binding differs")
        counter = record["counter"]
        if (
            counter["inputs"] != triple_variables
            or counter["start_variable"] != next_variable
            or counter["max_unary_threshold"] != 56
        ):
            raise ValueError("counter input or allocation differs")
        counter_clauses, next_variable, terminals = (
            reconstruct_prefix_counter(
                triple_variables, 56, next_variable
            )
        )
        if (
            counter["terminal_variables"] != terminals
            or len(counter_clauses) != counter["source_clauses"]
        ):
            raise ValueError("counter metadata differs from reconstruction")
        expected_clauses.extend(counter_clauses)
        for pattern in infeasible:
            expected_clauses.append(
                tuple(
                    -variable if value else variable
                    for variable, value in zip(
                        singleton_variables[1:], pattern[1:]
                    )
                )
            )
        for case in pattern_cases:
            mismatch = tuple(
                -variable if value else variable
                for variable, value in zip(
                    singleton_variables[1:], case["pattern"][1:]
                )
            )
            target = case["triple_negative_orbits"]
            expected_clauses.append(mismatch + (terminals[target - 1],))
            expected_clauses.append(mismatch + (-terminals[target],))
    if (
        next_variable
        != block["block_start_variable"]
        + block["block_auxiliary_variables"]
        or len(expected_clauses) != block["block_source_clauses"]
    ):
        raise ValueError("channel block dimensions differ")

    formula = Path(metadata["cnf"]["path"])
    if sha256(formula) != metadata["cnf"]["sha256"]:
        raise ValueError("formula hash mismatch")
    actual_clauses = []
    start = block["serialized_clause_start"]
    end = start + block["serialized_clauses"] - 1
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
            if start <= clause_number <= end:
                actual_clauses.append(parse_clause(line))
    if actual_clauses != expected_clauses:
        raise ValueError("serialized channel block differs from reconstruction")
    digest = hashlib.sha256()
    for clause in actual_clauses:
        digest.update(
            (" ".join(map(str, clause)) + " 0\n").encode("ascii")
        )
    if digest.hexdigest() != block["serialized_block_sha256"]:
        raise ValueError("serialized channel block hash differs")
    mutation = list(expected_clauses)
    mutation[0] = (-mutation[0][0],) + mutation[0][1:]
    if mutation == actual_clauses:
        raise ValueError("one-literal channel mutation was not rejected")

    binding = metadata["controls"][
        "id3_singleton_channel_parent_binding"
    ]
    parent_metadata_path = Path(binding["path"])
    if (
        sha256(parent_metadata_path) != binding["metadata_sha256"]
        or binding["formula_sha256"] != EXPECTED_PARENT_FORMULA_SHA256
    ):
        raise ValueError("parent metadata binding differs")
    parent_metadata = json.loads(parent_metadata_path.read_text())
    parent_formula = Path(parent_metadata["cnf"]["path"])
    if (
        parent_metadata["cnf"]["sha256"]
        != EXPECTED_PARENT_FORMULA_SHA256
        or sha256(parent_formula) != EXPECTED_PARENT_FORMULA_SHA256
    ):
        raise ValueError("parent formula hash differs")
    truth = metadata["controls"]["id3_sequential_prefix_truth_table"]
    if (
        truth["result"] != "PASS"
        or not truth["unique_satisfying_extension_for_every_input"]
        or not truth["terminal_signals_equal_at_least_thresholds"]
    ):
        raise ValueError("generator prefix truth-table control failed")

    result = {
        "schema": "frontiermath-hadamard-id3-singleton-triple-channel-audit-v1",
        "status": "pass",
        "family_id": 3,
        "formula_sha256": metadata["cnf"]["sha256"],
        "metadata_sha256": sha256(args.metadata),
        "checks": {
            "canonical_patterns": len(canonical),
            "canonical_feasible_patterns": len(feasible),
            "canonical_infeasible_patterns": len(infeasible),
            "allowed_singleton_triple_count_pairs": [
                list(pair) for pair in allowed_pairs
            ],
            "counters_reconstructed": 2,
            "source_channel_clauses": len(expected_clauses),
            "serialized_channel_clauses": len(actual_clauses),
            "serialized_block_sha256": digest.hexdigest(),
            "one_literal_mutation_rejected": True,
            "parent_metadata_and_formula_bound": True,
            "truth_table_control": truth["result"],
        },
        "method": (
            "Recompute all normalized singleton translation orbits and exact "
            "row cases, independently reconstruct both unary prefix counters "
            "and every conditional clause, bind the parent formula, and "
            "compare the exact DIMACS block without importing the generator "
            "or proof encoder."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
