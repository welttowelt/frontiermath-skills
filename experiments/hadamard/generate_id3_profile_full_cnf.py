#!/usr/bin/env python3
"""Generate the proof-producing full-ID3 CNF for one fixed profile.

The base XOR/PB circuit is the independently audited proof encoder from the
pinned LP(333) artifact.  This wrapper supplies:

* independently reconstructed ID3 orbits;
* the exact profile row and prescribed-q2 column margins;
* fixed singleton signs; and
* ordinary CNF lemmas for every independently audited benchmark prune.

The generated formula contains all 116 independent full-length PAF equations.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from id3_full_profile_arithmetic import (
    LENGTH,
    MOD9,
    MULTIPLIER_GENERATOR,
    crt_grid_orbits,
    cyclic_subgroup,
    multiplication_orbits,
    orbit_signature,
)


GRID_COLUMNS = 12
SEQUENCES = 2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_proof_encoder(source_repo: Path):
    proof_dir = source_repo.resolve() / "lp333" / "proof_phase2"
    encoder_path = proof_dir / "lp333_cnf.py"
    if not encoder_path.is_file():
        raise ValueError(f"missing pinned proof encoder: {encoder_path}")
    sys.path.insert(0, str(proof_dir))
    module = importlib.import_module("lp333_cnf")
    return module, encoder_path


def validate_inputs(
    ledger_path: Path,
    benchmark_path: Path,
    audit_path: Path,
    event_log_path: Path,
    profile_id: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ledger_hash = sha256_file(ledger_path)
    benchmark_hash = sha256_file(benchmark_path)
    event_hash = sha256_file(event_log_path)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    if benchmark.get("status") != "benchmark-pass":
        raise ValueError("propagation benchmark did not pass")
    if not all(benchmark.get("promotion_checks", {}).values()):
        raise ValueError("not all propagation promotion checks passed")
    if benchmark.get("profile_id") != profile_id:
        raise ValueError("benchmark is bound to a different profile")
    if benchmark.get("profile_ledger_sha256") != ledger_hash:
        raise ValueError("benchmark is bound to a different ledger")
    if benchmark.get("event_log", {}).get("sha256") != event_hash:
        raise ValueError("benchmark event-log hash mismatch")
    if audit.get("status") != "pass" or not all(
        audit.get("checks", {}).values()
    ):
        raise ValueError("propagation event audit did not pass")
    audit_inputs = audit.get("inputs", {})
    if audit_inputs.get("benchmark_manifest_sha256") != benchmark_hash:
        raise ValueError("event audit is bound to a different benchmark")
    if audit_inputs.get("event_log_sha256") != event_hash:
        raise ValueError("event audit is bound to a different event log")
    if audit_inputs.get("profile_ledger_sha256") != ledger_hash:
        raise ValueError("event audit is bound to a different ledger")

    record = next(
        (
            item
            for item in ledger.get("records", [])
            if item.get("id") == profile_id
        ),
        None,
    )
    if record is None or record.get("feasible") is not True:
        raise ValueError("selected profile has no feasible margin witness")
    return record, benchmark, audit


def add_profile_constraints(
    model,
    record: dict[str, Any],
    orbits: list[list[int]],
) -> dict[str, Any]:
    builder = model.builder
    orbit_lookup = {
        frozenset(orbit): index for index, orbit in enumerate(orbits)
    }
    grid = crt_grid_orbits()
    singleton_orbits = [
        orbit_lookup[frozenset(grid[row * 13])] for row in range(MOD9)
    ]
    cell_orbits = [
        [
            orbit_lookup[frozenset(grid[row * 13 + column + 1])]
            for column in range(GRID_COLUMNS)
        ]
        for row in range(MOD9)
    ]
    primary = (model.za, model.zb)

    fixed_global_variables: set[int] = set()
    singleton_signs: list[list[int]] = []
    row_plus_degrees: list[list[int]] = []
    column_plus_degrees: list[list[int]] = []
    row_negative_targets: list[list[int]] = []
    column_negative_targets: list[list[int]] = []

    for sequence, name in enumerate(("a", "b")):
        compressed = record[f"{name}_tilde"]
        binary = record[f"{name}_margin_9_by_12"]
        signs = [1 if value % 3 == 1 else -1 for value in compressed]
        singleton_signs.append(signs)
        for row, sign in enumerate(signs):
            orbit = singleton_orbits[row]
            global_variable = sequence * len(orbits) + orbit
            fixed_global_variables.add(global_variable)
            z_variable = primary[sequence][orbit]
            builder.add_unit(-z_variable if sign == 1 else z_variable)

        row_degrees = [sum(row) for row in binary]
        column_degrees = [
            sum(binary[row][column] for row in range(MOD9))
            for column in range(GRID_COLUMNS)
        ]
        row_plus_degrees.append(row_degrees)
        column_plus_degrees.append(column_degrees)

        negative_rows = []
        for row, plus_degree in enumerate(row_degrees):
            target = GRID_COLUMNS - plus_degree
            negative_rows.append(target)
            bits, _ = builder.weighted_sum(
                [
                    (1, primary[sequence][cell_orbits[row][column]])
                    for column in range(GRID_COLUMNS)
                ],
                f"profile_{name}_row_{row}",
            )
            builder.force_value(bits, target)
        row_negative_targets.append(negative_rows)

        negative_columns = []
        for column, plus_degree in enumerate(column_degrees):
            target = MOD9 - plus_degree
            negative_columns.append(target)
            bits, _ = builder.weighted_sum(
                [
                    (1, primary[sequence][cell_orbits[row][column]])
                    for row in range(MOD9)
                ],
                f"profile_{name}_column_{column}",
            )
            builder.force_value(bits, target)
        column_negative_targets.append(negative_columns)

    return {
        "fixed_global_variables": fixed_global_variables,
        "singleton_orbits": singleton_orbits,
        "cell_orbits": cell_orbits,
        "singleton_signs": singleton_signs,
        "row_plus_degrees": row_plus_degrees,
        "column_plus_degrees": column_plus_degrees,
        "row_negative_targets": row_negative_targets,
        "column_negative_targets": column_negative_targets,
    }


def add_learned_prune_clauses(
    model,
    event_log_path: Path,
    fixed_global_variables: set[int],
    orbit_count: int,
) -> dict[str, Any]:
    builder = model.builder
    primary = tuple(model.za) + tuple(model.zb)
    if len(primary) != SEQUENCES * orbit_count:
        raise ValueError("primary-variable map has an unexpected size")

    seen: set[tuple[int, ...]] = set()
    clause_lengths: list[int] = []
    event_counts: Counter[str] = Counter()
    prune_events = 0
    duplicate_clauses = 0
    canonical_hasher = hashlib.sha256()

    with event_log_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            event = json.loads(line)
            event_type = event.get("event_type")
            event_counts[event_type] += 1
            if event_type not in {"paf-prune", "margin-prune"}:
                continue
            prune_events += 1
            assigned = int(event["assigned_mask_hex"], 16)
            negative = int(event["negative_mask_hex"], 16)
            if negative & ~assigned:
                raise ValueError(
                    f"negative mask outside assigned mask at line {line_number}"
                )
            if assigned >> len(primary) or negative >> len(primary):
                raise ValueError(
                    f"event mask exceeds primary variables at line {line_number}"
                )

            literals: list[int] = []
            semantic_key: list[int] = []
            for global_variable, cnf_variable in enumerate(primary):
                if global_variable in fixed_global_variables:
                    continue
                if not (assigned & (1 << global_variable)):
                    continue
                is_negative = bool(negative & (1 << global_variable))
                # x = +1 means z = 0, so the blocking literal is z.
                literal = -cnf_variable if is_negative else cnf_variable
                literals.append(literal)
                semantic_key.append(
                    -(global_variable + 1)
                    if is_negative
                    else global_variable + 1
                )
            if not literals:
                raise ValueError(
                    f"prune event {line_number} has no nonfixed assignments"
                )
            key = tuple(semantic_key)
            if key in seen:
                duplicate_clauses += 1
                continue
            seen.add(key)
            builder.add_clause(*literals)
            clause_lengths.append(len(literals))
            canonical_hasher.update(
                (" ".join(map(str, key)) + " 0\n").encode("ascii")
            )

    if prune_events != (
        event_counts["paf-prune"] + event_counts["margin-prune"]
    ):
        raise AssertionError("prune event accounting failed")
    return {
        "event_counts": dict(sorted(event_counts.items())),
        "prune_events": prune_events,
        "unique_learned_clauses": len(clause_lengths),
        "duplicate_learned_clauses": duplicate_clauses,
        "clause_length": {
            "minimum": min(clause_lengths),
            "maximum": max(clause_lengths),
            "mean": statistics.fmean(clause_lengths),
            "median": statistics.median(clause_lengths),
        },
        "canonical_semantic_clause_sha256": canonical_hasher.hexdigest(),
    }


def build_witness_primary_assignment(
    record: dict[str, Any],
    profile: dict[str, Any],
    orbit_count: int,
) -> tuple[list[int], list[int]]:
    assignments = [[None] * orbit_count for _ in range(SEQUENCES)]
    for sequence, name in enumerate(("a", "b")):
        for row, sign in enumerate(profile["singleton_signs"][sequence]):
            assignments[sequence][profile["singleton_orbits"][row]] = (
                0 if sign == 1 else 1
            )
        binary = record[f"{name}_margin_9_by_12"]
        for row in range(MOD9):
            for column in range(GRID_COLUMNS):
                sign = 1 if binary[row][column] else -1
                orbit = profile["cell_orbits"][row][column]
                assignments[sequence][orbit] = 0 if sign == 1 else 1
    if any(value is None for sequence in assignments for value in sequence):
        raise ValueError("profile witness did not assign every orbit")
    return (
        [int(value) for value in assignments[0]],
        [int(value) for value in assignments[1]],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_ledger", type=Path)
    parser.add_argument("--profile-id", type=int, default=73)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--event-log", required=True, type=Path)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--cnf-output", required=True, type=Path)
    parser.add_argument("--metadata-output", required=True, type=Path)
    args = parser.parse_args()

    record, benchmark, audit = validate_inputs(
        args.profile_ledger,
        args.benchmark,
        args.audit,
        args.event_log,
        args.profile_id,
    )
    proof_encoder, proof_encoder_path = load_proof_encoder(args.source_repo)
    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    if subgroup != (1, 10, 100) or orbit_signature(orbits) != {1: 9, 3: 108}:
        raise ValueError("independent ID3 orbit signature changed")

    spec = proof_encoder.spec_from_orbits(LENGTH, orbits)
    model = proof_encoder.build_orbit_model(LENGTH, spec)
    base_dimensions = {
        "variables": model.builder.num_vars,
        "clauses": len(model.builder.clauses),
        "used_pairs_per_sequence": model.pair_count,
    }
    profile = add_profile_constraints(model, record, orbits)
    after_profile_dimensions = {
        "variables": model.builder.num_vars,
        "clauses": len(model.builder.clauses),
    }
    learned = add_learned_prune_clauses(
        model,
        args.event_log,
        profile["fixed_global_variables"],
        len(orbits),
    )

    witness_za, witness_zb = build_witness_primary_assignment(
        record, profile, len(orbits)
    )
    direct_full_predicate = model.semantic_value(witness_za, witness_zb)
    cnf_value, extension = model.canonical_cnf_value(witness_za, witness_zb)
    model.audit_extension(witness_za, witness_zb, extension)
    if direct_full_predicate or cnf_value:
        raise ValueError(
            "stored compression witness unexpectedly satisfies the full CNF"
        )

    args.cnf_output.parent.mkdir(parents=True, exist_ok=True)
    serialization = proof_encoder.write_dimacs(
        model.builder,
        args.cnf_output,
        split_unit_clauses=True,
    )
    metadata = {
        "schema": "frontiermath-hadamard-id3-profile-full-cnf-v1",
        "status": "generated",
        "profile_id": args.profile_id,
        "scope": (
            "exact profile row/column margins, all 116 independent full-ID3 "
            "PAF equations, and audited programmatic-search prune lemmas"
        ),
        "claim_boundary": (
            "the generated formula is a single profile slice; SAT requires "
            "direct LP verification and UNSAT requires replay of its proof"
        ),
        "inputs": {
            "profile_ledger": str(args.profile_ledger),
            "profile_ledger_sha256": sha256_file(args.profile_ledger),
            "benchmark": str(args.benchmark),
            "benchmark_sha256": sha256_file(args.benchmark),
            "benchmark_status": benchmark["status"],
            "event_audit": str(args.audit),
            "event_audit_sha256": sha256_file(args.audit),
            "event_audit_status": audit["status"],
            "event_log": str(args.event_log),
            "event_log_sha256": sha256_file(args.event_log),
            "source_repository": str(args.source_repo.resolve()),
            "proof_encoder": str(proof_encoder_path),
            "proof_encoder_sha256": sha256_file(proof_encoder_path),
        },
        "id3": {
            "subgroup": list(subgroup),
            "orbit_count": len(orbits),
            "orbit_signature": {
                str(size): count
                for size, count in orbit_signature(orbits).items()
            },
            "shift_representatives": len(spec["reps"]),
        },
        "profile": {
            key: value
            for key, value in profile.items()
            if key != "fixed_global_variables"
        },
        "base_full_paf_circuit": base_dimensions,
        "after_profile_circuit": after_profile_dimensions,
        "learned_prune_clauses": learned,
        "stored_margin_witness_control": {
            "direct_full_predicate": direct_full_predicate,
            "canonical_cnf_value": cnf_value,
            "result": "correctly-rejected",
        },
        "serialization": serialization,
        "cnf": {
            "path": str(args.cnf_output),
            "sha256": sha256_file(args.cnf_output),
            "bytes": args.cnf_output.stat().st_size,
            "variables": serialization["num_variables"],
            "clauses": serialization["num_clauses"],
        },
        "primary_variables": {
            "za": model.za,
            "zb": model.zb,
            "meaning": "z=0 is orbit sign +1; z=1 is orbit sign -1",
        },
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
    args.metadata_output.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": metadata["status"],
                "cnf": metadata["cnf"],
                "learned_prune_clauses": learned,
                "stored_margin_witness_control": metadata[
                    "stored_margin_witness_control"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

