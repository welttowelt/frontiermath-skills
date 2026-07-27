#!/usr/bin/env python3
"""Semantic and serialization audit for the full profile-ID3 CNF."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import random
import sys
from pathlib import Path
from typing import Any

from generate_id3_profile_full_cnf import (
    add_learned_prune_clauses,
    add_profile_constraints,
    build_witness_primary_assignment,
)
from id3_full_profile_arithmetic import (
    LENGTH,
    MULTIPLIER_GENERATOR,
    cyclic_subgroup,
    multiplication_orbits,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_encoder(source_repo: Path):
    proof_dir = source_repo.resolve() / "lp333" / "proof_phase2"
    sys.path.insert(0, str(proof_dir))
    module = importlib.import_module("lp333_cnf")
    return module, proof_dir / "lp333_cnf.py"


def inspect_dimacs(path: Path) -> dict[str, int]:
    declared_variables = None
    declared_clauses = None
    clauses = 0
    maximum_variable = 0
    maximum_clause_length = 0
    long_clauses = 0
    empty_clauses = 0
    with path.open("r", encoding="ascii") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("c"):
                continue
            if stripped.startswith("p "):
                fields = stripped.split()
                if len(fields) != 4 or fields[1] != "cnf":
                    raise ValueError("invalid DIMACS header")
                declared_variables = int(fields[2])
                declared_clauses = int(fields[3])
                continue
            tokens = [int(token) for token in stripped.split()]
            if not tokens or tokens[-1] != 0:
                raise ValueError("unterminated DIMACS clause")
            literals = tokens[:-1]
            clauses += 1
            maximum_clause_length = max(maximum_clause_length, len(literals))
            if len(literals) >= 100:
                long_clauses += 1
            if not literals:
                empty_clauses += 1
            for literal in literals:
                maximum_variable = max(maximum_variable, abs(literal))
    if declared_variables is None or declared_clauses is None:
        raise ValueError("missing DIMACS header")
    return {
        "declared_variables": declared_variables,
        "declared_clauses": declared_clauses,
        "parsed_clauses": clauses,
        "maximum_variable": maximum_variable,
        "maximum_clause_length": maximum_clause_length,
        "clauses_of_length_at_least_100": long_clauses,
        "empty_clauses": empty_clauses,
    }


def switched_margin_assignments(
    record: dict[str, Any],
    profile: dict[str, Any],
    orbit_count: int,
    samples: int,
    seed: int,
) -> list[tuple[list[int], list[int]]]:
    rng = random.Random(seed)
    matrices = [
        [list(row) for row in record[f"{name}_margin_9_by_12"]]
        for name in ("a", "b")
    ]
    results: list[tuple[list[int], list[int]]] = []

    def encode() -> tuple[list[int], list[int]]:
        assignments = [[None] * orbit_count for _ in range(2)]
        for sequence in range(2):
            for row, sign in enumerate(
                profile["singleton_signs"][sequence]
            ):
                orbit = profile["singleton_orbits"][row]
                assignments[sequence][orbit] = 0 if sign == 1 else 1
            for row in range(9):
                for column in range(12):
                    orbit = profile["cell_orbits"][row][column]
                    assignments[sequence][orbit] = (
                        0 if matrices[sequence][row][column] else 1
                    )
        if any(
            value is None
            for sequence in assignments
            for value in sequence
        ):
            raise ValueError("margin assignment is incomplete")
        return (
            [int(value) for value in assignments[0]],
            [int(value) for value in assignments[1]],
        )

    results.append(encode())
    attempts = 0
    while len(results) < samples and attempts < 100 * samples:
        attempts += 1
        sequence = rng.randrange(2)
        row_a, row_b = rng.sample(range(9), 2)
        column_a, column_b = rng.sample(range(12), 2)
        matrix = matrices[sequence]
        block = (
            matrix[row_a][column_a],
            matrix[row_a][column_b],
            matrix[row_b][column_a],
            matrix[row_b][column_b],
        )
        if block == (1, 0, 0, 1):
            replacement = (0, 1, 1, 0)
        elif block == (0, 1, 1, 0):
            replacement = (1, 0, 0, 1)
        else:
            continue
        (
            matrix[row_a][column_a],
            matrix[row_a][column_b],
            matrix[row_b][column_a],
            matrix[row_b][column_b],
        ) = replacement
        results.append(encode())
    if len(results) < samples:
        raise ValueError(
            f"only generated {len(results)} margin-preserving assignments"
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("profile_ledger", type=Path)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--event-audit", required=True, type=Path)
    parser.add_argument("--event-log", required=True, type=Path)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--margin-samples", type=int, default=100)
    args = parser.parse_args()

    encoding = json.loads(
        args.encoding_metadata.read_text(encoding="utf-8")
    )
    ledger = json.loads(args.profile_ledger.read_text(encoding="utf-8"))
    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    event_audit = json.loads(
        args.event_audit.read_text(encoding="utf-8")
    )
    cnf_path = Path(encoding["cnf"]["path"])
    input_checks = {
        "cnf_hash": sha256_file(cnf_path) == encoding["cnf"]["sha256"],
        "ledger_hash": (
            sha256_file(args.profile_ledger)
            == encoding["inputs"]["profile_ledger_sha256"]
        ),
        "benchmark_hash": (
            sha256_file(args.benchmark)
            == encoding["inputs"]["benchmark_sha256"]
        ),
        "event_audit_hash": (
            sha256_file(args.event_audit)
            == encoding["inputs"]["event_audit_sha256"]
        ),
        "event_log_hash": (
            sha256_file(args.event_log)
            == encoding["inputs"]["event_log_sha256"]
        ),
        "benchmark_pass": benchmark.get("status") == "benchmark-pass",
        "event_audit_pass": event_audit.get("status") == "pass",
    }
    if not all(input_checks.values()):
        raise ValueError(f"input binding failed: {input_checks}")

    record = next(
        item
        for item in ledger["records"]
        if item["id"] == encoding["profile_id"]
    )
    proof_encoder, encoder_path = load_encoder(args.source_repo)
    if sha256_file(encoder_path) != encoding["inputs"]["proof_encoder_sha256"]:
        raise ValueError("pinned proof encoder hash changed")

    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    spec = proof_encoder.spec_from_orbits(LENGTH, orbits)
    model = proof_encoder.build_orbit_model(LENGTH, spec)
    profile = add_profile_constraints(model, record, orbits)
    learned = add_learned_prune_clauses(
        model,
        args.event_log,
        profile["fixed_global_variables"],
        len(orbits),
    )
    rebuilt_hash = proof_encoder.dimacs_sha256(
        model.builder, split_unit_clauses=True
    )
    serialization_matches = rebuilt_hash == encoding["cnf"]["sha256"]

    transformation_audit = proof_encoder.transformation_truth_table_audit()
    small_model = proof_encoder.build_singleton_model(7)
    small_exhaustive = proof_encoder.exhaustive_small_audit(small_model)
    small_a, small_b = proof_encoder.find_small_legendre_pair(7)
    small_za = [0 if value == 1 else 1 for value in small_a]
    small_zb = [0 if value == 1 else 1 for value in small_b]
    small_cnf_value, small_extension = small_model.canonical_cnf_value(
        small_za, small_zb
    )
    small_model.audit_extension(small_za, small_zb, small_extension)
    positive_fixture = {
        "length": 7,
        "direct_semantic_value": small_model.semantic_value(
            small_za, small_zb
        ),
        "canonical_cnf_value": small_cnf_value,
        "a": small_a,
        "b": small_b,
    }

    margin_assignments = switched_margin_assignments(
        record,
        profile,
        len(orbits),
        args.margin_samples,
        20260726,
    )
    margin_audit_failures = []
    full_semantic_true = 0
    cnf_true = 0
    for sample, (za, zb) in enumerate(margin_assignments):
        semantic = model.semantic_value(za, zb)
        cnf_value, extension = model.canonical_cnf_value(za, zb)
        model.audit_extension(za, zb, extension)
        full_semantic_true += int(semantic)
        cnf_true += int(cnf_value)
        # Learned clauses are proved consequences, so the augmented formula
        # must agree with the full semantic predicate on these profile points.
        if semantic != cnf_value:
            margin_audit_failures.append(
                {
                    "sample": sample,
                    "semantic": semantic,
                    "cnf": cnf_value,
                }
            )
    margin_audit = {
        "samples": len(margin_assignments),
        "seed": 20260726,
        "full_semantic_true": full_semantic_true,
        "canonical_cnf_true": cnf_true,
        "failures": margin_audit_failures,
        "result": "PASS" if not margin_audit_failures else "FAIL",
    }

    witness_za, witness_zb = build_witness_primary_assignment(
        record, profile, len(orbits)
    )
    witness_semantic = model.semantic_value(witness_za, witness_zb)
    witness_cnf, witness_extension = model.canonical_cnf_value(
        witness_za, witness_zb
    )
    model.audit_extension(witness_za, witness_zb, witness_extension)
    witness_control = {
        "direct_semantic_value": witness_semantic,
        "canonical_cnf_value": witness_cnf,
        "correctly_rejected": not witness_semantic and not witness_cnf,
    }

    dimacs = inspect_dimacs(cnf_path)
    dimacs_checks = {
        "parsed_clause_count": (
            dimacs["parsed_clauses"] == dimacs["declared_clauses"]
        ),
        "metadata_variable_count": (
            dimacs["declared_variables"] == encoding["cnf"]["variables"]
        ),
        "metadata_clause_count": (
            dimacs["declared_clauses"] == encoding["cnf"]["clauses"]
        ),
        "variable_range": (
            dimacs["maximum_variable"] <= dimacs["declared_variables"]
        ),
        "learned_long_clause_count": (
            dimacs["clauses_of_length_at_least_100"]
            == learned["unique_learned_clauses"]
        ),
        "no_empty_clause": dimacs["empty_clauses"] == 0,
    }
    checks = {
        **input_checks,
        **dimacs_checks,
        "deterministic_serialization_rebuild": serialization_matches,
        "transformation_truth_tables": (
            transformation_audit["result"] == "PASS"
        ),
        "small_exhaustive_equivalence": (
            small_exhaustive["result"] == "PASS"
        ),
        "positive_fixture": (
            positive_fixture["direct_semantic_value"]
            and positive_fixture["canonical_cnf_value"]
        ),
        "profile_margin_samples": not margin_audit_failures,
        "stored_margin_witness_rejected": witness_control[
            "correctly_rejected"
        ],
        "learned_clause_hash": (
            learned["canonical_semantic_clause_sha256"]
            == encoding["learned_prune_clauses"][
                "canonical_semantic_clause_sha256"
            ]
        ),
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-hadamard-id3-profile-full-cnf-audit-v1",
        "status": status,
        "checks": checks,
        "dimacs": dimacs,
        "deterministic_rebuild_sha256": rebuilt_hash,
        "transformation_audit": transformation_audit,
        "small_exhaustive_audit": small_exhaustive,
        "positive_fixture": positive_fixture,
        "profile_margin_assignment_audit": margin_audit,
        "stored_margin_witness_control": witness_control,
        "learned_prune_clauses": learned,
        "inputs": {
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "cnf_sha256": sha256_file(cnf_path),
            "profile_ledger_sha256": sha256_file(args.profile_ledger),
            "benchmark_sha256": sha256_file(args.benchmark),
            "event_audit_sha256": sha256_file(args.event_audit),
            "event_log_sha256": sha256_file(args.event_log),
            "proof_encoder_sha256": sha256_file(encoder_path),
        },
        "auditor_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "checks": checks,
                "dimacs": dimacs,
                "profile_margin_assignment_audit": margin_audit,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

