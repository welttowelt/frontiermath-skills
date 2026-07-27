#!/usr/bin/env python3
"""Add complete static lex-leaders for an exact LP333 symmetry group."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
from itertools import product
import json
import math
from pathlib import Path
import random
import sys
from typing import Any, Sequence


LENGTH = 333
PAPER_URL = "https://arxiv.org/abs/2203.12275"
PAPER_PDF_SHA256 = (
    "026caf5d675eab8d6b8d163d91cfef5c719d0e1ce775f476e6973354ddc06509"
)
CARDINALITY_PAPER_URLS = [
    "https://research.chalmers.se/publication/74331",
    "https://arxiv.org/abs/1012.3853",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_encoder(source_repo: Path):
    proof_dir = source_repo.resolve() / "lp333" / "proof_phase2"
    encoder_path = proof_dir / "lp333_cnf.py"
    sys.path.insert(0, str(proof_dir))
    module = importlib.import_module("lp333_cnf")
    return module, encoder_path


def load_source_family(
    source_repo: Path, family_id: int
) -> tuple[dict[str, Any], Path, Path]:
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
    if status["status"] != "OPEN":
        raise ValueError(f"family {family_id} is not source-OPEN")
    return (
        {"classification": subgroup, "status": status},
        classification_path,
        status_path,
    )


def unit_permutations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    representatives: dict[tuple[int, ...], int] = {}
    for unit in range(1, LENGTH):
        if math.gcd(unit, LENGTH) != 1:
            continue
        permutation = tuple(
            spec["idx"][(unit * orbit[0]) % LENGTH]
            for orbit in spec["orbits"]
        )
        representatives.setdefault(permutation, unit)
    return [
        {"unit": unit, "permutation": permutation}
        for permutation, unit in sorted(
            representatives.items(), key=lambda item: item[1]
        )
    ]


def validate_decimation_group(
    spec: dict[str, Any],
    actions: Sequence[dict[str, Any]],
    subgroup_order: int,
) -> dict[str, Any]:
    permutations = {item["permutation"] for item in actions}
    identity = tuple(range(spec["r"]))
    expected_order = 216 // subgroup_order
    if len(actions) != expected_order or identity not in permutations:
        raise ValueError(
            f"expected the {expected_order}-element unit/H decimation group"
        )
    for left in permutations:
        for right in permutations:
            composition = tuple(right[left[index]] for index in range(spec["r"]))
            if composition not in permutations:
                raise ValueError("decimation permutations are not closed")

    coefficient_checks = 0
    for item in actions:
        unit = item["unit"]
        permutation = item["permutation"]
        for index, size in enumerate(spec["sizes"]):
            if size != spec["sizes"][permutation[index]]:
                raise ValueError("decimation changed an orbit size")
        for matrix_index, shift in enumerate(spec["reps"]):
            target_orbit_index = spec["idx"][(unit * shift) % LENGTH] - 1
            if target_orbit_index < 0:
                raise ValueError("nonzero shift mapped to the zero orbit")
            target_index = spec.get(
                "paf_orbit_to_reduced_index",
                list(range(spec["num_reps"])),
            )[target_orbit_index]
            if spec["const"][matrix_index] != spec["const"][target_index]:
                raise ValueError("decimation changed a PAF diagonal constant")
            source_matrix = spec["W"][matrix_index]
            target_matrix = spec["W"][target_index]
            for left in range(spec["r"]):
                for right in range(left + 1, spec["r"]):
                    mapped_left = permutation[left]
                    mapped_right = permutation[right]
                    expected = target_matrix[mapped_left][mapped_right]
                    if source_matrix[left][right] != expected:
                        raise ValueError("decimation changed a PAF coefficient")
                    coefficient_checks += 1
    return {
        "result": "PASS",
        "unit_group_order": 216,
        "fixed_multiplier_subgroup_order": subgroup_order,
        "quotient_action_order": len(actions),
        "closure_compositions_checked": len(actions) ** 2,
        "orbit_size_checks": len(actions) * spec["r"],
        "paf_coefficient_checks": coefficient_checks,
    }


def quotient_inverse_paf_rows(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove PAF rows that are identical by the identity PAF(s)=PAF(-s)."""
    classes = []
    covered: set[int] = set()
    retained = []
    for index, shift in enumerate(spec["reps"]):
        if index in covered:
            continue
        inverse_index = spec["idx"][(-shift) % LENGTH] - 1
        if inverse_index < 0:
            raise ValueError("nonzero PAF shift inverted to the zero orbit")
        members = sorted({index, inverse_index})
        if len(members) != 2:
            raise ValueError(
                "preregistered ID4/ID5 quotient requires size-two inverse classes"
            )
        left, right = members
        if spec["const"][left] != spec["const"][right]:
            raise ValueError("inverse PAF rows have different diagonal constants")
        if spec["W"][left] != spec["W"][right]:
            raise ValueError("inverse PAF rows have different coefficient matrices")
        covered.update(members)
        retained.append(left)
        classes.append(
            {
                "original_indices": members,
                "shifts": [spec["reps"][member] for member in members],
                "retained_original_index": left,
                "diagonal_constant": spec["const"][left],
            }
        )
    if covered != set(range(spec["num_reps"])):
        raise ValueError("inverse quotient did not cover every PAF representative")

    reduced = dict(spec)
    reduced["reps"] = [spec["reps"][index] for index in retained]
    reduced["const"] = [spec["const"][index] for index in retained]
    reduced["W"] = [spec["W"][index] for index in retained]
    reduced["num_reps"] = len(retained)
    original_to_reduced = [0] * spec["num_reps"]
    for reduced_index, item in enumerate(classes):
        for original_index in item["original_indices"]:
            original_to_reduced[original_index] = reduced_index
    reduced["paf_orbit_to_reduced_index"] = original_to_reduced
    return reduced, {
        "result": "PASS",
        "identity": "PAF_x(s) = PAF_x(-s) by index substitution",
        "original_representatives": spec["num_reps"],
        "retained_representatives": len(retained),
        "class_size_histogram": {"2": len(classes)},
        "all_diagonal_constants_equal": True,
        "all_coefficient_matrices_equal": True,
        "classes": classes,
    }


def direct_random_equivalence(
    model: Any,
    full_spec: dict[str, Any],
    samples: int,
    seed: int,
) -> dict[str, Any]:
    """Compare the reduced predicate with direct length-333 arithmetic."""
    rng = random.Random(seed)
    comparisons = 0
    direct_shift_checks = 0
    for _ in range(samples):
        za = [0] + [rng.randrange(2) for _ in range(model.spec["r"] - 1)]
        zb = [0] + [rng.randrange(2) for _ in range(model.spec["r"] - 1)]
        reduced = model.semantic_value(za, zb)
        a_orbits = [1 - 2 * value for value in za]
        b_orbits = [1 - 2 * value for value in zb]
        a = [a_orbits[full_spec["idx"][position]] for position in range(LENGTH)]
        b = [b_orbits[full_spec["idx"][position]] for position in range(LENGTH)]
        direct = sum(a) in (-1, 1) and sum(b) in (-1, 1)
        if direct:
            for shift in range(1, LENGTH):
                direct_shift_checks += 1
                if (
                    sum(
                        a[position] * a[(position + shift) % LENGTH]
                        for position in range(LENGTH)
                    )
                    + sum(
                        b[position] * b[(position + shift) % LENGTH]
                        for position in range(LENGTH)
                    )
                    != -2
                ):
                    direct = False
                    break
        if reduced != direct:
            raise ValueError("reduced PAF predicate differs from direct arithmetic")
        comparisons += 1
    return {
        "result": "PASS",
        "samples": comparisons,
        "seed": seed,
        "direct_shift_checks": direct_shift_checks,
        "predicate": "row sums plus all 332 direct periodic PAF equations",
    }


def normalized_translation_control(
    model: Any,
    full_spec: dict[str, Any],
    subgroup_elements: Sequence[int],
    samples: int,
    seed: int,
) -> dict[str, Any]:
    translations = [
        translation
        for translation in range(LENGTH)
        if all(
            ((unit - 1) * translation) % LENGTH == 0
            for unit in subgroup_elements
        )
    ]
    if translations != [0, 111, 222]:
        raise ValueError(
            f"expected normalized-translation annihilator [0,111,222], got {translations}"
        )
    singleton_indices = [
        index for index, size in enumerate(full_spec["sizes"]) if size == 1
    ]
    if (
        singleton_indices != [0, 1, 2]
        or full_spec["orbits"][1:] [:2] != [[111], [222]]
    ):
        raise ValueError("unexpected singleton orbit layout")
    triple_indices = [
        index for index, size in enumerate(full_spec["sizes"]) if size == 3
    ]
    allowed_patterns = []
    row_cases = []
    for left in (0, 1):
        for right in (0, 1):
            pattern = (0, left, right)
            for triple_negatives in range(len(triple_indices) + 1):
                weighted = left + right + 3 * triple_negatives
                if weighted in ((LENGTH - 1) // 2, (LENGTH + 1) // 2):
                    allowed_patterns.append(pattern)
                    row_cases.append(
                        {
                            "pattern": list(pattern),
                            "triple_negative_orbits": triple_negatives,
                            "weighted_negative_count": weighted,
                        }
                    )
    allowed_patterns = sorted(set(allowed_patterns))
    if allowed_patterns != [(0, 0, 1), (0, 1, 0), (0, 1, 1)]:
        raise ValueError(f"unexpected row-feasible singleton patterns: {allowed_patterns}")

    def normalized_singleton_translate(
        pattern: tuple[int, int, int], offset: int
    ) -> tuple[int, int, int]:
        return tuple(
            pattern[(index + offset) % 3] ^ pattern[offset]
            for index in range(3)
        )

    pattern_orbits = {}
    for pattern in allowed_patterns:
        orbit = sorted(
            {
                normalized_singleton_translate(pattern, offset)
                for offset in range(3)
            }
        )
        pattern_orbits["".join(map(str, pattern))] = [
            list(item) for item in orbit
        ]
        if orbit != allowed_patterns or min(orbit) != (0, 0, 1):
            raise ValueError("normalized singleton translation has wrong orbit")

    rng = random.Random(seed)
    direct_paf_equalities = 0
    orbit_invariance_checks = 0
    row_magnitude_checks = 0
    for _ in range(samples):
        orbit_values = [1] + [
            rng.choice((-1, 1)) for _ in range(full_spec["r"] - 1)
        ]
        sequence = [
            orbit_values[full_spec["idx"][position]]
            for position in range(LENGTH)
        ]
        base_row_magnitude = abs(sum(sequence))
        base_pafs = [
            sum(
                sequence[position] * sequence[(position + shift) % LENGTH]
                for position in range(LENGTH)
            )
            for shift in range(1, LENGTH)
        ]
        for translation in translations:
            origin = sequence[translation]
            transformed = [
                origin * sequence[(position + translation) % LENGTH]
                for position in range(LENGTH)
            ]
            if transformed[0] != 1:
                raise ValueError("normalized translation changed the fixed origin")
            for orbit in full_spec["orbits"]:
                if len({transformed[position] for position in orbit}) != 1:
                    raise ValueError("normalized translation broke H-invariance")
                orbit_invariance_checks += 1
            if abs(sum(transformed)) != base_row_magnitude:
                raise ValueError("normalized translation changed row-sum magnitude")
            row_magnitude_checks += 1
            for shift, expected in enumerate(base_pafs, start=1):
                actual = sum(
                    transformed[position]
                    * transformed[(position + shift) % LENGTH]
                    for position in range(LENGTH)
                )
                if actual != expected:
                    raise ValueError("normalized translation changed a PAF")
                direct_paf_equalities += 1
    return {
        "result": "PASS",
        "translations": translations,
        "independent_pair_action_order": len(translations) ** 2,
        "singleton_orbits": [
            full_spec["orbits"][index] for index in singleton_indices
        ],
        "row_feasible_singleton_patterns": [
            list(pattern) for pattern in allowed_patterns
        ],
        "row_cases": row_cases,
        "pattern_orbits": pattern_orbits,
        "canonical_pattern": [0, 0, 1],
        "random_orbit_assignments": samples,
        "seed": seed,
        "orbit_invariance_checks": orbit_invariance_checks,
        "row_magnitude_checks": row_magnitude_checks,
        "direct_paf_equalities": direct_paf_equalities,
    }


def apply_translation_gauge(
    model: Any, full_spec: dict[str, Any]
) -> dict[str, Any]:
    index_111 = full_spec["idx"][111]
    index_222 = full_spec["idx"][222]
    if (
        full_spec["orbits"][index_111] != [111]
        or full_spec["orbits"][index_222] != [222]
    ):
        raise ValueError("translation gauge positions are not singleton orbits")
    literals = [
        -model.za[index_111],
        model.za[index_222],
        -model.zb[index_111],
        model.zb[index_222],
    ]
    clause_indices = []
    for literal in literals:
        model.builder.add_unit(literal)
        clause_indices.append(len(model.builder.clauses))
    return {
        "enabled": True,
        "canonical_pattern": [0, 0, 1],
        "per_sequence_translations": [0, 111, 222],
        "independent_pair_action_order": 9,
        "gauge_literals": literals,
        "gauge_source_clause_indices": clause_indices,
    }


def id3_singleton_translation_control(
    full_spec: dict[str, Any],
    subgroup_elements: Sequence[int],
    samples: int,
    seed: int,
) -> dict[str, Any]:
    translations = [
        translation
        for translation in range(LENGTH)
        if all(
            ((unit - 1) * translation) % LENGTH == 0
            for unit in subgroup_elements
        )
    ]
    expected_translations = list(range(0, LENGTH, 37))
    if translations != expected_translations:
        raise ValueError(
            f"expected ID3 translations {expected_translations}, got {translations}"
        )
    singleton_indices = [
        full_spec["idx"][translation] for translation in translations
    ]
    if any(
        full_spec["orbits"][index] != [translation]
        for index, translation in zip(singleton_indices, translations)
    ):
        raise ValueError("ID3 translation positions are not singleton orbits")

    def normalized_pattern_translate(
        pattern: tuple[int, ...], offset: int
    ) -> tuple[int, ...]:
        return tuple(
            pattern[(index + offset) % len(pattern)] ^ pattern[offset]
            for index in range(len(pattern))
        )

    patterns = [
        (0,) + suffix for suffix in product((0, 1), repeat=8)
    ]
    orbit_by_pattern = {}
    unique_orbits = set()
    orbit_size_histogram: Counter[int] = Counter()
    for pattern in patterns:
        orbit = tuple(
            sorted(
                {
                    normalized_pattern_translate(pattern, offset)
                    for offset in range(9)
                }
            )
        )
        orbit_by_pattern[pattern] = orbit
        unique_orbits.add(orbit)
    for orbit in unique_orbits:
        orbit_size_histogram[len(orbit)] += 1
    if len(unique_orbits) != 30 or orbit_size_histogram != Counter(
        {1: 1, 3: 1, 9: 28}
    ):
        raise ValueError("ID3 normalized singleton orbit partition changed")

    row_feasible = []
    row_cases = []
    for pattern in patterns:
        singleton_negatives = sum(pattern)
        cases = []
        for triple_negatives in range(109):
            weighted = singleton_negatives + 3 * triple_negatives
            if weighted in (166, 167):
                cases.append(
                    {
                        "triple_negative_orbits": triple_negatives,
                        "weighted_negative_count": weighted,
                    }
                )
        if cases:
            row_feasible.append(pattern)
            row_cases.append(
                {
                    "pattern": list(pattern),
                    "singleton_negative_count": singleton_negatives,
                    "cases": cases,
                }
            )
    feasible_orbits = {orbit_by_pattern[pattern] for pattern in row_feasible}
    if (
        len(row_feasible) != 171
        or len(feasible_orbits) != 19
        or any(len(orbit) != 9 for orbit in feasible_orbits)
    ):
        raise ValueError("ID3 row-feasible singleton orbit gate failed")
    canonical_patterns = sorted(min(orbit) for orbit in unique_orbits)
    noncanonical_patterns = sorted(
        pattern
        for pattern in patterns
        if pattern != min(orbit_by_pattern[pattern])
    )
    if len(noncanonical_patterns) != 226:
        raise ValueError("ID3 noncanonical singleton count changed")

    rng = random.Random(seed)
    direct_paf_equalities = 0
    orbit_invariance_checks = 0
    row_magnitude_checks = 0
    for _ in range(samples):
        orbit_values = [1] + [
            rng.choice((-1, 1)) for _ in range(full_spec["r"] - 1)
        ]
        sequence = [
            orbit_values[full_spec["idx"][position]]
            for position in range(LENGTH)
        ]
        base_row_magnitude = abs(sum(sequence))
        base_pafs = [
            sum(
                sequence[position] * sequence[(position + shift) % LENGTH]
                for position in range(LENGTH)
            )
            for shift in range(1, LENGTH)
        ]
        for translation in translations:
            origin = sequence[translation]
            transformed = [
                origin * sequence[(position + translation) % LENGTH]
                for position in range(LENGTH)
            ]
            if transformed[0] != 1:
                raise ValueError("ID3 translation changed normalized origin")
            for orbit in full_spec["orbits"]:
                if len({transformed[position] for position in orbit}) != 1:
                    raise ValueError("ID3 translation broke H-invariance")
                orbit_invariance_checks += 1
            if abs(sum(transformed)) != base_row_magnitude:
                raise ValueError("ID3 translation changed row magnitude")
            row_magnitude_checks += 1
            for shift, expected in enumerate(base_pafs, start=1):
                actual = sum(
                    transformed[position]
                    * transformed[(position + shift) % LENGTH]
                    for position in range(LENGTH)
                )
                if actual != expected:
                    raise ValueError("ID3 translation changed a PAF")
                direct_paf_equalities += 1
    return {
        "result": "PASS",
        "translations": translations,
        "singleton_indices": singleton_indices,
        "per_sequence_action_order": 9,
        "independent_pair_action_order": 81,
        "normalized_patterns": len(patterns),
        "all_orbits": len(unique_orbits),
        "all_orbit_size_histogram": dict(
            sorted(orbit_size_histogram.items())
        ),
        "row_feasible_patterns": len(row_feasible),
        "row_feasible_orbits": len(feasible_orbits),
        "row_feasible_orbit_size_histogram": {"9": 19},
        "canonical_patterns": [list(pattern) for pattern in canonical_patterns],
        "noncanonical_patterns": [
            list(pattern) for pattern in noncanonical_patterns
        ],
        "row_cases": row_cases,
        "random_orbit_assignments": samples,
        "seed": seed,
        "orbit_invariance_checks": orbit_invariance_checks,
        "row_magnitude_checks": row_magnitude_checks,
        "direct_paf_equalities": direct_paf_equalities,
    }


def apply_id3_singleton_translation_canonicalization(
    model: Any,
    control: dict[str, Any],
) -> dict[str, Any]:
    singleton_indices = control["singleton_indices"]
    noncanonical_patterns = [
        tuple(pattern) for pattern in control["noncanonical_patterns"]
    ]
    block_start = len(model.builder.clauses) + 1
    sequence_records = []
    for label, primary in (("a", model.za), ("b", model.zb)):
        variables = [primary[index] for index in singleton_indices]
        clauses_before = len(model.builder.clauses)
        for pattern in noncanonical_patterns:
            model.builder.add_clause(
                *[
                    (-variable if value else variable)
                    for variable, value in zip(variables[1:], pattern[1:])
                ]
            )
        sequence_records.append(
            {
                "sequence": label,
                "singleton_variables": variables,
                "blocking_clauses": len(model.builder.clauses)
                - clauses_before,
            }
        )
    return {
        "enabled": True,
        "kind": (
            "blocking clauses for non-lex-minimal normalized singleton "
            "translation patterns"
        ),
        "independent_pair_action_order": 81,
        "block_source_clause_start": block_start,
        "block_source_clause_end": len(model.builder.clauses),
        "block_source_clauses": len(model.builder.clauses) - block_start + 1,
        "sequence_records": sequence_records,
        "canonical_patterns": control["canonical_patterns"],
        "noncanonical_patterns": control["noncanonical_patterns"],
    }


def bind_serialized_plain_clause_block(
    builder: Any,
    serialization: dict[str, Any],
    block: dict[str, Any],
) -> None:
    source_start = block["block_source_clause_start"]
    source_end = block["block_source_clause_end"]
    split_sources = {
        item["source_clause_index"]
        for item in serialization["unit_split_map"]
    }
    if any(source in split_sources for source in range(source_start, source_end + 1)):
        raise ValueError("plain canonicalization block unexpectedly contains units")
    prior_splits = sum(source < source_start for source in split_sources)
    digest = hashlib.sha256()
    for source_index in range(source_start, source_end + 1):
        clause = builder.clauses[source_index - 1]
        digest.update(
            (" ".join(map(str, clause)) + " 0\n").encode("ascii")
        )
    block["serialized_clause_start"] = source_start + prior_splits
    block["serialized_clauses"] = source_end - source_start + 1
    block["serialized_block_sha256"] = digest.hexdigest()


def add_sequential_exact_cardinality(
    builder: Any,
    inputs: Sequence[int],
    target: int,
    name: str,
) -> dict[str, Any]:
    """Add a uniquely extended unary prefix counter and assert count=target."""
    input_literals = list(inputs)
    size = len(input_literals)
    if not 0 <= target <= size:
        builder.add_clause()
        return {
            "name": name,
            "inputs": input_literals,
            "target": target,
            "auxiliary_variables": 0,
            "source_clauses": 1,
        }
    start_variable = builder.num_vars + 1
    rows: list[list[int]] = []
    max_threshold = min(size, target + 1)
    for prefix in range(size):
        rows.append(
            [
                builder.new_var(f"{name}_prefix_{prefix}_ge_{threshold}")
                for threshold in range(
                    1, min(prefix + 1, max_threshold) + 1
                )
            ]
        )
    source_start = len(builder.clauses) + 1
    for prefix, literal in enumerate(input_literals):
        row = rows[prefix]
        for threshold_index, output in enumerate(row):
            threshold = threshold_index + 1
            if prefix == 0:
                builder.add_equivalence(output, literal)
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
                    raise AssertionError("missing previous threshold-one signal")
                # output <-> (same OR literal)
                builder.add_clause(-same, output)
                builder.add_clause(-literal, output)
                builder.add_clause(-output, same, literal)
            elif same is None:
                if lower is None:
                    raise AssertionError("missing lower threshold signal")
                # output <-> (literal AND lower)
                builder.add_clause(-literal, -lower, output)
                builder.add_clause(-output, literal)
                builder.add_clause(-output, lower)
            else:
                if lower is None:
                    raise AssertionError("missing lower threshold signal")
                # output <-> (same OR (literal AND lower))
                builder.add_clause(-same, output)
                builder.add_clause(-literal, -lower, output)
                builder.add_clause(-output, same, literal)
                builder.add_clause(-output, same, lower)
    if target:
        builder.add_unit(rows[-1][target - 1])
    if target < size:
        builder.add_unit(-rows[-1][target])
    source_end = len(builder.clauses)
    return {
        "name": name,
        "inputs": input_literals,
        "input_count": size,
        "target": target,
        "start_variable": start_variable,
        "auxiliary_variables": builder.num_vars - start_variable + 1,
        "source_clause_start": source_start,
        "source_clause_end": source_end,
        "source_clauses": source_end - source_start + 1,
        "max_unary_threshold": max_threshold,
        "asserted_at_least_variable": (
            rows[-1][target - 1] if target else None
        ),
        "asserted_overflow_variable": (
            rows[-1][target] if target < size else None
        ),
    }


def add_sequential_prefix_counter(
    builder: Any,
    inputs: Sequence[int],
    max_threshold: int,
    name: str,
) -> dict[str, Any]:
    """Add a uniquely extended unary counter without asserting a count."""
    input_literals = list(inputs)
    size = len(input_literals)
    if not 1 <= max_threshold <= size:
        raise ValueError("prefix threshold must be between one and input size")
    start_variable = builder.num_vars + 1
    rows: list[list[int]] = []
    for prefix in range(size):
        rows.append(
            [
                builder.new_var(f"{name}_prefix_{prefix}_ge_{threshold}")
                for threshold in range(
                    1, min(prefix + 1, max_threshold) + 1
                )
            ]
        )
    source_start = len(builder.clauses) + 1
    for prefix, literal in enumerate(input_literals):
        row = rows[prefix]
        for threshold_index, output in enumerate(row):
            threshold = threshold_index + 1
            if prefix == 0:
                builder.add_equivalence(output, literal)
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
                    raise AssertionError("missing previous threshold-one signal")
                builder.add_clause(-same, output)
                builder.add_clause(-literal, output)
                builder.add_clause(-output, same, literal)
            elif same is None:
                if lower is None:
                    raise AssertionError("missing lower threshold signal")
                builder.add_clause(-literal, -lower, output)
                builder.add_clause(-output, literal)
                builder.add_clause(-output, lower)
            else:
                if lower is None:
                    raise AssertionError("missing lower threshold signal")
                builder.add_clause(-same, output)
                builder.add_clause(-literal, -lower, output)
                builder.add_clause(-output, same, literal)
                builder.add_clause(-output, same, lower)
    source_end = len(builder.clauses)
    return {
        "name": name,
        "inputs": input_literals,
        "input_count": size,
        "max_unary_threshold": max_threshold,
        "start_variable": start_variable,
        "auxiliary_variables": builder.num_vars - start_variable + 1,
        "source_clause_start": source_start,
        "source_clause_end": source_end,
        "source_clauses": source_end - source_start + 1,
        "terminal_variables": rows[-1],
    }


def sequential_prefix_truth_table() -> dict[str, Any]:
    """Exhaustively test nonasserting counters and their terminal signals."""
    assignments_checked = 0
    extensions_checked = 0
    for size in range(1, 5):
        for max_threshold in range(1, size + 1):
            builder_class = sequential_prefix_truth_table.builder_class
            builder = builder_class()
            inputs = [
                builder.new_var(f"prefix_truth_input_{index}")
                for index in range(size)
            ]
            record = add_sequential_prefix_counter(
                builder,
                inputs,
                max_threshold,
                f"prefix_truth_{size}_{max_threshold}",
            )
            auxiliaries = list(
                range(
                    record["start_variable"],
                    record["start_variable"]
                    + record["auxiliary_variables"],
                )
            )
            for input_values in product((False, True), repeat=size):
                satisfying_extensions = 0
                for auxiliary_values in product(
                    (False, True), repeat=len(auxiliaries)
                ):
                    values: list[bool | None] = [
                        None
                    ] * (builder.num_vars + 1)
                    values[builder.false] = False
                    for variable, value in zip(inputs, input_values):
                        values[variable] = value
                    for variable, value in zip(
                        auxiliaries, auxiliary_values
                    ):
                        values[variable] = value
                    if not builder.clauses_hold(values):
                        extensions_checked += 1
                        continue
                    satisfying_extensions += 1
                    count = sum(input_values)
                    actual = [
                        values[variable]
                        for variable in record["terminal_variables"]
                    ]
                    expected = [
                        count >= threshold
                        for threshold in range(1, max_threshold + 1)
                    ]
                    if actual != expected:
                        raise ValueError(
                            "prefix counter terminal signal is incorrect"
                        )
                    extensions_checked += 1
                if satisfying_extensions != 1:
                    raise ValueError(
                        "prefix counter failed unique-extension truth table"
                    )
                assignments_checked += 1
    return {
        "result": "PASS",
        "input_sizes": [1, 2, 3, 4],
        "thresholds": "all feasible maximum thresholds",
        "assignments_checked": assignments_checked,
        "auxiliary_extensions_checked": extensions_checked,
        "unique_satisfying_extension_for_every_input": True,
        "terminal_signals_equal_at_least_thresholds": True,
    }


def sequential_cardinality_truth_table() -> dict[str, Any]:
    """Exhaustively test small exact counters, including unique extensions."""
    assignments_checked = 0
    extensions_checked = 0
    for size in range(1, 5):
        for target in range(size + 1):
            # Use the encoder module's builder interface through a tiny local
            # import-free implementation supplied by the caller at runtime.
            # The actual builder class is available as the global set in main.
            builder_class = sequential_cardinality_truth_table.builder_class
            builder = builder_class()
            inputs = [
                builder.new_var(f"truth_input_{index}")
                for index in range(size)
            ]
            record = add_sequential_exact_cardinality(
                builder, inputs, target, f"truth_{size}_{target}"
            )
            auxiliaries = list(
                range(
                    record["start_variable"],
                    record["start_variable"]
                    + record["auxiliary_variables"],
                )
            )
            for input_values in product((False, True), repeat=size):
                satisfying_extensions = 0
                for auxiliary_values in product(
                    (False, True), repeat=len(auxiliaries)
                ):
                    values: list[bool | None] = [
                        None
                    ] * (builder.num_vars + 1)
                    values[builder.false] = False
                    for variable, value in zip(inputs, input_values):
                        values[variable] = value
                    for variable, value in zip(
                        auxiliaries, auxiliary_values
                    ):
                        values[variable] = value
                    if builder.clauses_hold(values):
                        satisfying_extensions += 1
                    extensions_checked += 1
                expected = sum(input_values) == target
                if satisfying_extensions != int(expected):
                    raise ValueError(
                        "sequential exact counter failed unique-extension truth table"
                    )
                assignments_checked += 1
    return {
        "result": "PASS",
        "input_sizes": [1, 2, 3, 4],
        "targets": "all feasible targets for every input size",
        "assignments_checked": assignments_checked,
        "auxiliary_extensions_checked": extensions_checked,
        "unique_satisfying_extension_for_valid_inputs": True,
        "zero_satisfying_extensions_for_invalid_inputs": True,
    }


def add_id3_singleton_triple_unary_channel(
    model: Any,
    full_spec: dict[str, Any],
    control: dict[str, Any],
) -> dict[str, Any]:
    singleton_indices = control["singleton_indices"]
    triple_indices = [
        index for index, size in enumerate(full_spec["sizes"]) if size == 3
    ]
    if (
        len(singleton_indices) != 9
        or len(triple_indices) != 108
        or full_spec["num_reps"] != 116
    ):
        raise ValueError("ID3 singleton/triple orbit signature changed")
    canonical_patterns = [
        tuple(pattern) for pattern in control["canonical_patterns"]
    ]
    row_case_by_pattern = {
        tuple(record["pattern"]): record for record in control["row_cases"]
    }
    feasible_patterns = [
        pattern for pattern in canonical_patterns if pattern in row_case_by_pattern
    ]
    infeasible_patterns = [
        pattern for pattern in canonical_patterns if pattern not in row_case_by_pattern
    ]
    if len(feasible_patterns) != 19 or len(infeasible_patterns) != 11:
        raise ValueError("ID3 canonical row-case partition changed")

    pattern_records = []
    for pattern in feasible_patterns:
        record = row_case_by_pattern[pattern]
        cases = record["cases"]
        if len(cases) != 1:
            raise ValueError("ID3 canonical pattern has nonunique row case")
        pattern_records.append(
            {
                "pattern": list(pattern),
                "singleton_negative_count": sum(pattern),
                "triple_negative_orbits": cases[0][
                    "triple_negative_orbits"
                ],
                "weighted_negative_count": cases[0][
                    "weighted_negative_count"
                ],
            }
        )
    allowed_pairs = sorted(
        {
            (
                record["singleton_negative_count"],
                record["triple_negative_orbits"],
            )
            for record in pattern_records
        }
    )
    if allowed_pairs != [(1, 55), (2, 55), (4, 54), (5, 54)]:
        raise ValueError("ID3 singleton/triple row implication changed")

    block_start_variable = model.builder.num_vars + 1
    block_start_clause = len(model.builder.clauses) + 1
    sequence_records = []
    for label, primary in (("a", model.za), ("b", model.zb)):
        singleton_variables = [
            primary[index] for index in singleton_indices
        ]
        counter = add_sequential_prefix_counter(
            model.builder,
            [primary[index] for index in triple_indices],
            56,
            f"id3_row_{label}_triple_prefix",
        )
        infeasible_start = len(model.builder.clauses) + 1
        for pattern in infeasible_patterns:
            mismatch = [
                (-variable if value else variable)
                for variable, value in zip(
                    singleton_variables[1:], pattern[1:]
                )
            ]
            model.builder.add_clause(*mismatch)
        infeasible_end = len(model.builder.clauses)
        conditional_start = infeasible_end + 1
        for record in pattern_records:
            pattern = record["pattern"]
            target = record["triple_negative_orbits"]
            mismatch = [
                (-variable if value else variable)
                for variable, value in zip(
                    singleton_variables[1:], pattern[1:]
                )
            ]
            terminals = counter["terminal_variables"]
            model.builder.add_clause(*mismatch, terminals[target - 1])
            model.builder.add_clause(*mismatch, -terminals[target])
        conditional_end = len(model.builder.clauses)
        sequence_records.append(
            {
                "sequence": label,
                "singleton_variables": singleton_variables,
                "triple_variables": [
                    primary[index] for index in triple_indices
                ],
                "counter": counter,
                "infeasible_clause_start": infeasible_start,
                "infeasible_clause_end": infeasible_end,
                "infeasible_clauses": len(infeasible_patterns),
                "conditional_clause_start": conditional_start,
                "conditional_clause_end": conditional_end,
                "conditional_clauses": 2 * len(pattern_records),
            }
        )
    return {
        "enabled": True,
        "kind": (
            "redundant uniquely-extended unary prefix counters conditionally "
            "bound by canonical singleton row cases"
        ),
        "block_start_variable": block_start_variable,
        "block_auxiliary_variables": model.builder.num_vars
        - block_start_variable
        + 1,
        "block_source_clause_start": block_start_clause,
        "block_source_clause_end": len(model.builder.clauses),
        "block_source_clauses": len(model.builder.clauses)
        - block_start_clause
        + 1,
        "sequence_records": sequence_records,
        "canonical_feasible_patterns": [
            list(pattern) for pattern in feasible_patterns
        ],
        "canonical_infeasible_patterns": [
            list(pattern) for pattern in infeasible_patterns
        ],
        "pattern_cases": pattern_records,
        "allowed_singleton_triple_count_pairs": [
            list(pair) for pair in allowed_pairs
        ],
        "paper_to_levers": {
            "sources": CARDINALITY_PAPER_URLS,
            "adopted": (
                "unary cardinality counters expose partial-assignment "
                "deductions that binary counters can hide from unit propagation"
            ),
            "not_adopted": [
                "literature runtime ratios",
                "replacement of the full weighted PB layer",
                "native PB proof logging",
            ],
        },
    }


def add_unary_cardinality_channels(
    model: Any, full_spec: dict[str, Any]
) -> dict[str, Any]:
    if full_spec["num_reps"] != 112:
        raise ValueError("unary channels require the full 112-row PAF model")
    triple_indices = [
        index for index, size in enumerate(full_spec["sizes"]) if size == 3
    ]
    if len(triple_indices) != 110:
        raise ValueError("expected 110 size-three orbit variables")
    shift_index = full_spec["reps"].index(111)
    matrix = full_spec["W"][shift_index]
    singleton_pairs = []
    triple_edge_pairs = []
    coefficient_histogram: Counter[int] = Counter()
    for left in range(full_spec["r"]):
        for right in range(left + 1, full_spec["r"]):
            coefficient = matrix[left][right]
            if not coefficient:
                continue
            coefficient_histogram[coefficient] += 1
            if coefficient == 1:
                singleton_pairs.append((left, right))
            elif coefficient == 3:
                triple_edge_pairs.append((left, right))
            else:
                raise ValueError(
                    f"unexpected shift-111 coefficient {coefficient}"
                )
    if (
        len(singleton_pairs) != 3
        or len(triple_edge_pairs) != 108
        or full_spec["const"][shift_index] != 6
        or model.paf_targets[shift_index] != 334
    ):
        raise ValueError("shift-111 cardinality decomposition changed")

    block_start_variable = model.builder.num_vars + 1
    block_start_clause = len(model.builder.clauses) + 1
    channels = [
        add_sequential_exact_cardinality(
            model.builder,
            [model.za[index] for index in triple_indices],
            55,
            "channel_row_a_triples",
        ),
        add_sequential_exact_cardinality(
            model.builder,
            [model.zb[index] for index in triple_indices],
            55,
            "channel_row_b_triples",
        ),
        add_sequential_exact_cardinality(
            model.builder,
            [model.wa[pair] for pair in triple_edge_pairs]
            + [model.wb[pair] for pair in triple_edge_pairs],
            110,
            "channel_shift111_triple_edges",
        ),
    ]
    return {
        "enabled": True,
        "kind": "redundant uniquely-extended sequential unary exact counters",
        "block_start_variable": block_start_variable,
        "block_auxiliary_variables": model.builder.num_vars
        - block_start_variable
        + 1,
        "block_source_clause_start": block_start_clause,
        "block_source_clause_end": len(model.builder.clauses),
        "block_source_clauses": len(model.builder.clauses)
        - block_start_clause
        + 1,
        "channels": channels,
        "arithmetic_implication": {
            "orbit_signature": {"1": 3, "3": 110},
            "gauge_singleton_negative_count_per_sequence": 1,
            "row_weighted_negative_domain": [166, 167],
            "forced_triple_negative_orbits_per_sequence": 55,
            "shift": 111,
            "shift_diagonal_constant": full_spec["const"][shift_index],
            "shift_weighted_xor_target": model.paf_targets[shift_index],
            "coefficient_histogram": dict(
                sorted(coefficient_histogram.items())
            ),
            "singleton_pairs": [list(pair) for pair in singleton_pairs],
            "singleton_xor_contribution_across_sequences": 4,
            "triple_edge_pairs": [list(pair) for pair in triple_edge_pairs],
            "forced_active_triple_edges_across_sequences": 110,
        },
        "paper_to_levers": {
            "sources": CARDINALITY_PAPER_URLS,
            "adopted": (
                "unary cardinality counters expose partial-assignment "
                "deductions that binary counters can hide from unit propagation"
            ),
            "not_adopted": [
                "literature runtime ratios",
                "replacement of the full weighted PB layer",
                "native PB proof logging",
            ],
        },
    }


def bind_serialized_channel_block(
    builder: Any,
    serialization: dict[str, Any],
    channels: dict[str, Any],
) -> None:
    split_by_source = {
        item["source_clause_index"]: item
        for item in serialization["unit_split_map"]
    }
    source_start = channels["block_source_clause_start"]
    source_end = channels["block_source_clause_end"]
    prior_splits = sum(
        1 for source in split_by_source if source < source_start
    )
    serialized_clauses = []
    unit_gadgets = []
    for source_index in range(source_start, source_end + 1):
        clause = builder.clauses[source_index - 1]
        if source_index in split_by_source:
            item = split_by_source[source_index]
            if len(clause) != 1 or clause[0] != item["source_literal"]:
                raise ValueError("channel unit-split binding mismatch")
            literal = clause[0]
            mask = item["mask_variable"]
            serialized_clauses.extend(
                [(literal, mask), (literal, -mask)]
            )
            unit_gadgets.append(item)
        else:
            serialized_clauses.append(tuple(clause))
    digest = hashlib.sha256()
    for clause in serialized_clauses:
        digest.update(
            (" ".join(map(str, clause)) + " 0\n").encode("ascii")
        )
    channels["serialized_clause_start"] = source_start + prior_splits
    channels["serialized_clauses"] = len(serialized_clauses)
    channels["serialized_block_sha256"] = digest.hexdigest()
    channels["serialized_unit_gadgets"] = unit_gadgets


def variable_actions(
    za: Sequence[int],
    zb: Sequence[int],
    decimations: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions = []
    for decimation in decimations:
        permutation = decimation["permutation"]
        for swap in (False, True):
            if swap:
                mapping = tuple(
                    [zb[permutation[index]] for index in range(len(za))]
                    + [za[permutation[index]] for index in range(len(zb))]
                )
            else:
                mapping = tuple(
                    [za[permutation[index]] for index in range(len(za))]
                    + [zb[permutation[index]] for index in range(len(zb))]
                )
            actions.append(
                {
                    "unit": decimation["unit"],
                    "swap_sequences": swap,
                    "mapping": mapping,
                }
            )
    return actions


def add_lex_leader(
    builder: Any,
    variables: Sequence[int],
    mapping: Sequence[int],
    label: str,
) -> dict[str, int]:
    support = [
        index
        for index, (left, right) in enumerate(zip(variables, mapping))
        if left != right
    ]
    if not support:
        return {"support": 0, "auxiliaries": 0, "clauses": 0}
    clauses_before = len(builder.clauses)
    auxiliaries = 0
    prefix: int | None = None
    for support_index, position in enumerate(support):
        left = variables[position]
        right = mapping[position]
        if prefix is None:
            builder.add_clause(-left, right)
        else:
            builder.add_clause(-prefix, -left, right)
        if support_index + 1 == len(support):
            continue

        next_prefix = builder.new_var(
            f"{label}_prefix_{support_index + 1}"
        )
        auxiliaries += 1
        if prefix is not None:
            builder.add_clause(-next_prefix, prefix)
        builder.add_clause(-next_prefix, -left, right)
        builder.add_clause(-next_prefix, left, -right)
        if prefix is None:
            builder.add_clause(left, right, next_prefix)
            builder.add_clause(-left, -right, next_prefix)
        else:
            builder.add_clause(-prefix, left, right, next_prefix)
            builder.add_clause(-prefix, -left, -right, next_prefix)
        prefix = next_prefix
    return {
        "support": len(support),
        "auxiliaries": auxiliaries,
        "clauses": len(builder.clauses) - clauses_before,
    }


def normalize(sequence: Sequence[int]) -> list[int]:
    return [sequence[0] * value for value in sequence]


def decimate(sequence: Sequence[int], unit: int) -> list[int]:
    length = len(sequence)
    return [sequence[(unit * index) % length] for index in range(length)]


def lp63_control(
    encoder: Any, fixture_path: Path
) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    original_a = normalize(fixture["a_sequence"])
    original_b = normalize(fixture["b_sequence"])
    units = [
        unit for unit in range(1, 63) if math.gcd(unit, 63) == 1
    ]
    orbit = []
    for unit in units:
        a = decimate(original_a, unit)
        b = decimate(original_b, unit)
        for swap in (False, True):
            left, right = (b, a) if swap else (a, b)
            bits = tuple(
                [(1 - value) // 2 for value in left]
                + [(1 - value) // 2 for value in right]
            )
            orbit.append((bits, left, right))
    canonical_bits, canonical_a, canonical_b = min(
        orbit, key=lambda item: item[0]
    )
    if not encoder.direct_is_legendre_pair(canonical_a, canonical_b):
        raise ValueError("canonicalized LP63 fixture is not a Legendre pair")
    comparisons = 0
    for bits, _, _ in orbit:
        if canonical_bits > bits:
            raise ValueError("LP63 canonical representative is not lex-minimal")
        comparisons += 1
    normalized_translation_checks = 0
    translations = [0, len(canonical_a) // 3, 2 * len(canonical_a) // 3]
    translated_pairs = []
    for left_translation in translations:
        left_origin = canonical_a[left_translation]
        left = [
            left_origin
            * canonical_a[(index + left_translation) % len(canonical_a)]
            for index in range(len(canonical_a))
        ]
        for right_translation in translations:
            right_origin = canonical_b[right_translation]
            right = [
                right_origin
                * canonical_b[(index + right_translation) % len(canonical_b)]
                for index in range(len(canonical_b))
            ]
            if not encoder.direct_is_legendre_pair(left, right):
                raise ValueError(
                    "LP63 positive fixture failed normalized translation"
                )
            translated_pairs.append(
                [left_translation, right_translation]
            )
            normalized_translation_checks += 1
    inverse_checks = 0
    for sequence in (canonical_a, canonical_b):
        for shift in range(1, len(sequence)):
            left = sum(
                sequence[index] * sequence[(index + shift) % len(sequence)]
                for index in range(len(sequence))
            )
            right = sum(
                sequence[index] * sequence[(index - shift) % len(sequence)]
                for index in range(len(sequence))
            )
            if left != right:
                raise ValueError("LP63 positive fixture violates PAF inversion")
            inverse_checks += 1
    return {
        "result": "PASS",
        "fixture_sha256": sha256_file(fixture_path),
        "unit_decimations": len(units),
        "sequence_swap_factor": 2,
        "orbit_assignments": len(orbit),
        "lex_comparisons": comparisons,
        "canonical_pair_directly_verified": True,
        "inverse_paf_equalities_checked": inverse_checks,
        "normalized_independent_translation_pairs": translated_pairs,
        "normalized_translation_legendre_checks": (
            normalized_translation_checks
        ),
        "canonical_prefix_sha256": hashlib.sha256(
            bytes(canonical_bits)
        ).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family-id", required=True, type=int)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--lp63-fixture", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--random-equivalence-samples", type=int, default=1000
    )
    parser.add_argument(
        "--deduplicate-inverse-paf",
        action="store_true",
        help="quotient exact duplicate PAF(s)=PAF(-s) rows before PB encoding",
    )
    parser.add_argument(
        "--canonicalize-independent-translations",
        action="store_true",
        help="fix the normalized singleton translation gauge in each sequence",
    )
    parser.add_argument(
        "--canonicalize-id3-singleton-translations",
        action="store_true",
        help="retain one singleton-pattern representative per ID3 translation orbit",
    )
    parser.add_argument(
        "--add-unary-cardinality-channels",
        action="store_true",
        help="add the three preregistered redundant unary channels",
    )
    parser.add_argument(
        "--add-id3-singleton-triple-unary-channel",
        action="store_true",
        help="add the preregistered conditional ID3 row-count channel",
    )
    parser.add_argument("--parent-metadata", type=Path)
    args = parser.parse_args()
    if args.family_id not in (3, 4, 5, 7, 9, 10):
        raise ValueError(
            "static symmetry generator accepts ID3, ID4, ID5, ID7, ID9, or ID10"
        )
    if args.random_equivalence_samples <= 0:
        raise ValueError("random-equivalence sample count must be positive")
    if args.add_unary_cardinality_channels and (
        not args.canonicalize_independent_translations
        or args.deduplicate_inverse_paf
        or args.parent_metadata is None
    ):
        raise ValueError(
            "unary channels require the full PAF translation gauge and parent metadata"
        )
    if args.canonicalize_id3_singleton_translations and (
        args.family_id != 3
        or args.canonicalize_independent_translations
        or args.deduplicate_inverse_paf
        or args.add_unary_cardinality_channels
        or args.parent_metadata is None
    ):
        raise ValueError(
            "ID3 singleton translation canonicalization requires full PAF ID3 "
            "and parent metadata"
        )
    if args.add_id3_singleton_triple_unary_channel and (
        not args.canonicalize_id3_singleton_translations
        or args.family_id != 3
        or args.canonicalize_independent_translations
        or args.deduplicate_inverse_paf
        or args.add_unary_cardinality_channels
        or args.parent_metadata is None
    ):
        raise ValueError(
            "ID3 singleton/triple channel requires the full-PAF ID3 "
            "singleton quotient and its parent metadata"
        )

    source_family, classification_path, status_path = load_source_family(
        args.source_repo, args.family_id
    )
    encoder, encoder_path = load_encoder(args.source_repo)
    subgroup_elements, subgroup = encoder.subgroup_by_id(args.family_id)
    full_spec = encoder.spec_from_orbits(
        LENGTH, encoder.orbits_on_ZL(subgroup_elements, LENGTH)
    )
    inverse_control = None
    model_spec = full_spec
    if args.deduplicate_inverse_paf:
        model_spec, inverse_control = quotient_inverse_paf_rows(full_spec)
    model = encoder.build_orbit_model(LENGTH, model_spec)
    if (
        subgroup["elements"]
        != source_family["classification"]["elements"]
    ):
        raise ValueError("proof encoder selected a different subgroup")
    if model.direct_pb_obstructions:
        raise ValueError(
            "family has a direct PAF weighted-sum obstruction; certify that "
            "obstruction instead of serializing an empty-clause CNF: "
            f"{model.direct_pb_obstructions}"
        )
    random_equivalence = encoder.random_equivalence_audit(
        model,
        args.random_equivalence_samples,
        20260726 + args.family_id,
    )
    if random_equivalence["result"] != "PASS":
        raise ValueError("base CNF semantic-equivalence control failed")
    direct_equivalence = direct_random_equivalence(
        model,
        full_spec,
        args.random_equivalence_samples,
        20260786 + args.family_id,
    )
    translation_control = None
    translation_gauge = None
    if args.canonicalize_independent_translations:
        translation_control = normalized_translation_control(
            model,
            full_spec,
            subgroup_elements,
            samples=16,
            seed=20260826 + args.family_id,
        )
        translation_gauge = apply_translation_gauge(model, full_spec)
    id3_translation_control = None
    if args.canonicalize_id3_singleton_translations:
        id3_translation_control = id3_singleton_translation_control(
            full_spec,
            subgroup_elements,
            samples=8,
            seed=20260903,
        )
    actions = unit_permutations(model.spec)
    group_control = validate_decimation_group(
        model.spec, actions, len(subgroup["elements"])
    )
    variable_group = variable_actions(model.za, model.zb, actions)
    variables = tuple(model.za + model.zb)
    identity = tuple(variables)
    nonidentity = [
        item for item in variable_group if item["mapping"] != identity
    ]
    expected_full_group_order = 2 * len(actions)
    if (
        len(variable_group) != expected_full_group_order
        or len(nonidentity) != expected_full_group_order - 1
    ):
        raise ValueError(
            f"expected {expected_full_group_order} full symmetry actions "
            "and one identity"
        )

    breaker_records = []
    for action_index, action in enumerate(nonidentity):
        breaker = add_lex_leader(
            model.builder,
            variables,
            action["mapping"],
            f"sym_{action_index:02d}",
        )
        breaker_records.append(
            {
                "unit": action["unit"],
                "swap_sequences": action["swap_sequences"],
                **breaker,
            }
        )
    parent_binding = None
    unary_channels = None
    truth_table = None
    if args.add_unary_cardinality_channels:
        parent_metadata = json.loads(
            args.parent_metadata.read_text(encoding="utf-8")
        )
        expected_source_variables = (
            parent_metadata["cnf"]["variables"]
            - parent_metadata["cnf"]["unit_split_count"]
        )
        expected_source_clauses = (
            parent_metadata["cnf"]["clauses"]
            - parent_metadata["cnf"]["unit_split_count"]
        )
        parent_binding = {
            "result": "PASS",
            "path": str(args.parent_metadata),
            "metadata_sha256": sha256_file(args.parent_metadata),
            "formula_sha256": parent_metadata["cnf"]["sha256"],
            "family_id_equal": (
                parent_metadata["family_id"] == args.family_id
            ),
            "source_variables_equal_before_channels": (
                model.builder.num_vars == expected_source_variables
            ),
            "source_clauses_equal_before_channels": (
                len(model.builder.clauses) == expected_source_clauses
            ),
            "primary_variables_equal": (
                parent_metadata["primary_variables"]["za"] == model.za
                and parent_metadata["primary_variables"]["zb"] == model.zb
            ),
            "symmetry_equal": (
                parent_metadata["symmetry"]["breakers"]
                == breaker_records
            ),
            "translation_gauge_equal": (
                parent_metadata["independent_translation_gauge"][
                    "gauge_literals"
                ]
                == translation_gauge["gauge_literals"]
            ),
            "full_paf_representatives": full_spec["num_reps"],
        }
        if not all(
            value is True
            for key, value in parent_binding.items()
            if key.endswith("_equal")
        ) or parent_binding["full_paf_representatives"] != 112:
            raise ValueError(f"parent formula binding failed: {parent_binding}")
        sequential_cardinality_truth_table.builder_class = (
            encoder.CNFBuilder
        )
        truth_table = sequential_cardinality_truth_table()
        unary_channels = add_unary_cardinality_channels(
            model, full_spec
        )
    id3_parent_binding = None
    id3_singleton_canonicalization = None
    id3_channel_parent_binding = None
    id3_singleton_triple_channel = None
    id3_prefix_truth_table = None
    if args.canonicalize_id3_singleton_translations:
        parent_metadata = json.loads(
            args.parent_metadata.read_text(encoding="utf-8")
        )
        expected_source_variables = (
            parent_metadata["cnf"]["variables"]
            - parent_metadata["cnf"]["unit_split_count"]
        )
        expected_source_clauses = (
            parent_metadata["cnf"]["clauses"]
            - parent_metadata["cnf"]["unit_split_count"]
        )
        if not args.add_id3_singleton_triple_unary_channel:
            id3_parent_binding = {
                "result": "PASS",
                "path": str(args.parent_metadata),
                "metadata_sha256": sha256_file(args.parent_metadata),
                "formula_sha256": parent_metadata["cnf"]["sha256"],
                "family_id_equal": parent_metadata["family_id"] == 3,
                "source_variables_equal_before_canonicalization": (
                    model.builder.num_vars == expected_source_variables
                ),
                "source_clauses_equal_before_canonicalization": (
                    len(model.builder.clauses) == expected_source_clauses
                ),
                "primary_variables_equal": (
                    parent_metadata["primary_variables"]["za"] == model.za
                    and parent_metadata["primary_variables"]["zb"] == model.zb
                ),
                "symmetry_equal": (
                    parent_metadata["symmetry"]["breakers"] == breaker_records
                ),
                "full_paf_representatives": full_spec["num_reps"],
                "no_profile_constraints": (
                    "profile" not in json.dumps(parent_metadata).lower()
                ),
            }
            required = [
                value
                for key, value in id3_parent_binding.items()
                if key.endswith("_equal") or key == "no_profile_constraints"
            ]
            if (
                not all(required)
                or id3_parent_binding["full_paf_representatives"] != 116
            ):
                raise ValueError(
                    f"ID3 parent formula binding failed: {id3_parent_binding}"
                )
        id3_singleton_canonicalization = (
            apply_id3_singleton_translation_canonicalization(
                model, id3_translation_control
            )
        )
        if args.add_id3_singleton_triple_unary_channel:
            expected_formula_sha256 = (
                "0ea4f87736db6d1076214d8378e4f66e1fe499291d5f4d0d406209a7779172b8"
            )
            parent_block = parent_metadata[
                "id3_singleton_translation_canonicalization"
            ]
            comparable_keys = [
                "enabled",
                "kind",
                "independent_pair_action_order",
                "block_source_clause_start",
                "block_source_clause_end",
                "block_source_clauses",
                "sequence_records",
                "canonical_patterns",
                "noncanonical_patterns",
            ]
            id3_channel_parent_binding = {
                "result": "PASS",
                "path": str(args.parent_metadata),
                "metadata_sha256": sha256_file(args.parent_metadata),
                "formula_sha256": parent_metadata["cnf"]["sha256"],
                "expected_formula_sha256": expected_formula_sha256,
                "formula_sha256_equal": (
                    parent_metadata["cnf"]["sha256"]
                    == expected_formula_sha256
                ),
                "family_id_equal": parent_metadata["family_id"] == 3,
                "source_variables_equal_before_channel": (
                    model.builder.num_vars == expected_source_variables
                ),
                "source_clauses_equal_before_channel": (
                    len(model.builder.clauses) == expected_source_clauses
                ),
                "primary_variables_equal": (
                    parent_metadata["primary_variables"]["za"] == model.za
                    and parent_metadata["primary_variables"]["zb"] == model.zb
                ),
                "symmetry_equal": (
                    parent_metadata["symmetry"]["breakers"] == breaker_records
                ),
                "singleton_canonicalization_equal": all(
                    parent_block[key]
                    == id3_singleton_canonicalization[key]
                    for key in comparable_keys
                ),
                "parent_no_profile_control": (
                    parent_metadata["controls"][
                        "id3_static_parent_binding"
                    ]["no_profile_constraints"]
                    is True
                ),
                "full_paf_representatives": full_spec["num_reps"],
            }
            required = [
                value
                for key, value in id3_channel_parent_binding.items()
                if key.endswith("_equal")
                or key == "parent_no_profile_control"
            ]
            if (
                not all(required)
                or id3_channel_parent_binding[
                    "full_paf_representatives"
                ]
                != 116
            ):
                raise ValueError(
                    "ID3 singleton channel parent formula binding failed: "
                    f"{id3_channel_parent_binding}"
                )
            sequential_prefix_truth_table.builder_class = encoder.CNFBuilder
            id3_prefix_truth_table = sequential_prefix_truth_table()
            id3_singleton_triple_channel = (
                add_id3_singleton_triple_unary_channel(
                    model,
                    full_spec,
                    id3_translation_control,
                )
            )

    args.output_dir.mkdir(parents=True, exist_ok=False)
    cnf_path = args.output_dir / f"id{args.family_id}-symmetry.cnf"
    metadata_path = args.output_dir / "encoding.json"
    serialization = encoder.write_dimacs(
        model.builder, cnf_path, split_unit_clauses=True
    )
    if translation_gauge is not None:
        split_by_source = {
            item["source_clause_index"]: item
            for item in serialization["unit_split_map"]
        }
        translation_gauge["serialized_unit_gadgets"] = [
            split_by_source[index]
            for index in translation_gauge["gauge_source_clause_indices"]
        ]
    if unary_channels is not None:
        bind_serialized_channel_block(
            model.builder, serialization, unary_channels
        )
    if id3_singleton_canonicalization is not None:
        bind_serialized_plain_clause_block(
            model.builder,
            serialization,
            id3_singleton_canonicalization,
        )
    if id3_singleton_triple_channel is not None:
        bind_serialized_plain_clause_block(
            model.builder,
            serialization,
            id3_singleton_triple_channel,
        )
    in_memory_hash = encoder.dimacs_sha256(
        model.builder, split_unit_clauses=True
    )
    cnf_hash = sha256_file(cnf_path)
    if cnf_hash != in_memory_hash:
        raise ValueError("written symmetry CNF hash mismatch")
    positive_control = lp63_control(encoder, args.lp63_fixture)

    added_auxiliaries = sum(
        record["auxiliaries"] for record in breaker_records
    )
    added_clauses = sum(record["clauses"] for record in breaker_records)
    metadata = {
        "schema": "frontiermath-hadamard-lp333-symmetry-cnf-v1",
        "status": "generated",
        "family_id": args.family_id,
        "claim_boundary": (
            "Every enabled quotient is an independently controlled formula "
            "automorphism or identity. The lex-leaders preserve satisfiability "
            "by selecting the least assignment in every verified finite "
            "symmetry orbit. UNSAT still requires an accepted complete proof."
        ),
        "subgroup": {
            "elements": subgroup["elements"],
            "order": len(subgroup["elements"]),
            "orbit_count": model.spec["r"],
            "orbits": model.spec["orbits"],
            "orbit_signature": dict(
                sorted(Counter(model.spec["sizes"]).items())
            ),
        },
        "symmetry": {
            "decimation_quotient_order": len(actions),
            "sequence_swap_factor": 2,
            "full_group_order": len(variable_group),
            "nonidentity_lex_leaders": len(nonidentity),
            "variable_order": (
                f"za[0..{len(model.za) - 1}], then "
                f"zb[0..{len(model.zb) - 1}]"
            ),
            "encoding": (
                "complete lex-leaders with fresh prefix-equality auxiliaries"
            ),
            "added_auxiliaries": added_auxiliaries,
            "added_clauses": added_clauses,
            "support_min": min(item["support"] for item in breaker_records),
            "support_max": max(item["support"] for item in breaker_records),
            "breakers": breaker_records,
        },
        "cnf": {
            "path": str(cnf_path),
            "variables": serialization["num_variables"],
            "clauses": serialization["num_clauses"],
            "bytes": cnf_path.stat().st_size,
            "sha256": cnf_hash,
            "unit_split_count": serialization["unit_split_count"],
        },
        "controls": {
            "random_semantic_cnf_equivalence": random_equivalence,
            "direct_full_length_semantic_equivalence": direct_equivalence,
            "exact_decimation_group": group_control,
            "lp63_positive_canonicalization": positive_control,
        },
        "primary_variables": {
            "meaning": "z=0 is orbit sign +1; z=1 is orbit sign -1",
            "za": model.za,
            "zb": model.zb,
        },
        "paper_to_levers": {
            "paper": (
                "Bogaerts, Gocht, McCreesh, Nordstrom, Certified Dominance "
                "and Symmetry Breaking for Combinatorial Optimisation"
            ),
            "url": PAPER_URL,
            "pdf_sha256": PAPER_PDF_SHA256,
            "adopted_shadow": (
                "static lex-leaders with prefix auxiliaries for an explicit "
                "small symmetry group"
            ),
            "not_adopted": [
                "general dominance proof logging",
                "dynamic symmetry learning",
                "giant-weight lexicographic orders",
            ],
            "axis_warning": (
                "The paper's benchmark timing ratios do not transfer to "
                "LP333; only terminal local evidence controls promotion."
            ),
        },
        "inputs": {
            "proof_encoder": str(encoder_path),
            "proof_encoder_sha256": sha256_file(encoder_path),
            "lp63_fixture": str(args.lp63_fixture),
            "lp63_fixture_sha256": sha256_file(args.lp63_fixture),
            "subgroup_classification": str(classification_path),
            "subgroup_classification_sha256": sha256_file(
                classification_path
            ),
            "master_status": str(status_path),
            "master_status_sha256": sha256_file(status_path),
        },
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    if inverse_control is not None:
        metadata["paf_inverse_deduplication"] = {
            "enabled": True,
            **inverse_control,
        }
    if translation_gauge is not None:
        metadata["controls"]["normalized_translation_automorphism"] = (
            translation_control
        )
        metadata["independent_translation_gauge"] = translation_gauge
    if unary_channels is not None:
        metadata["controls"]["sequential_cardinality_truth_table"] = (
            truth_table
        )
        metadata["controls"]["parent_formula_binding"] = parent_binding
        metadata["unary_cardinality_channels"] = unary_channels
    if id3_singleton_canonicalization is not None:
        metadata["controls"]["id3_normalized_translation_automorphism"] = (
            id3_translation_control
        )
        if id3_parent_binding is not None:
            metadata["controls"]["id3_static_parent_binding"] = (
                id3_parent_binding
            )
        else:
            metadata["controls"]["id3_static_parent_binding"] = (
                parent_metadata["controls"]["id3_static_parent_binding"]
            )
        metadata["id3_singleton_translation_canonicalization"] = (
            id3_singleton_canonicalization
        )
    if id3_singleton_triple_channel is not None:
        metadata["controls"]["id3_sequential_prefix_truth_table"] = (
            id3_prefix_truth_table
        )
        metadata["controls"]["id3_singleton_channel_parent_binding"] = (
            id3_channel_parent_binding
        )
        metadata["id3_singleton_triple_unary_channel"] = (
            id3_singleton_triple_channel
        )
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": metadata["status"],
                "family_id": args.family_id,
                "symmetry": {
                    key: value
                    for key, value in metadata["symmetry"].items()
                    if key != "breakers"
                },
                "cnf": metadata["cnf"],
                "controls": metadata["controls"],
                "metadata_sha256": sha256_file(metadata_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
