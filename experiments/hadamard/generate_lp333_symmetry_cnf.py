#!/usr/bin/env python3
"""Add complete static lex-leaders for an exact LP333 symmetry group."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence


LENGTH = 333
PAPER_URL = "https://arxiv.org/abs/2203.12275"
PAPER_PDF_SHA256 = (
    "026caf5d675eab8d6b8d163d91cfef5c719d0e1ce775f476e6973354ddc06509"
)


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
    spec: dict[str, Any], actions: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    permutations = {item["permutation"] for item in actions}
    identity = tuple(range(spec["r"]))
    if len(actions) != 36 or identity not in permutations:
        raise ValueError("expected the 36-element unit/H decimation group")
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
            target_index = spec["idx"][(unit * shift) % LENGTH] - 1
            if target_index < 0:
                raise ValueError("nonzero shift mapped to the zero orbit")
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
        "fixed_multiplier_subgroup_order": 6,
        "quotient_action_order": len(actions),
        "closure_compositions_checked": len(actions) ** 2,
        "orbit_size_checks": len(actions) * spec["r"],
        "paf_coefficient_checks": coefficient_checks,
    }


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
    return {
        "result": "PASS",
        "fixture_sha256": sha256_file(fixture_path),
        "unit_decimations": len(units),
        "sequence_swap_factor": 2,
        "orbit_assignments": len(orbit),
        "lex_comparisons": comparisons,
        "canonical_pair_directly_verified": True,
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
    args = parser.parse_args()
    if args.family_id not in (7, 9, 10):
        raise ValueError("static symmetry generator accepts ID7, ID9, or ID10")
    if args.random_equivalence_samples <= 0:
        raise ValueError("random-equivalence sample count must be positive")

    source_family, classification_path, status_path = load_source_family(
        args.source_repo, args.family_id
    )
    encoder, encoder_path = load_encoder(args.source_repo)
    model, subgroup = encoder.build_lp333_model(args.family_id)
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
    actions = unit_permutations(model.spec)
    group_control = validate_decimation_group(model.spec, actions)
    variable_group = variable_actions(model.za, model.zb, actions)
    variables = tuple(model.za + model.zb)
    identity = tuple(variables)
    nonidentity = [
        item for item in variable_group if item["mapping"] != identity
    ]
    if len(variable_group) != 72 or len(nonidentity) != 71:
        raise ValueError("expected 72 full symmetry actions and one identity")

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

    args.output_dir.mkdir(parents=True, exist_ok=False)
    cnf_path = args.output_dir / f"id{args.family_id}-symmetry.cnf"
    metadata_path = args.output_dir / "encoding.json"
    serialization = encoder.write_dimacs(
        model.builder, cnf_path, split_unit_clauses=True
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
            "The lex-leaders preserve satisfiability by selecting the least "
            "assignment in every explicitly verified finite symmetry orbit. "
            "UNSAT still requires an accepted complete proof."
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
                "The paper's SAT Competition timing ratios do not transfer "
                "to LP333; this run uses the existing ID10 DRAT baseline."
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
