#!/usr/bin/env python3
"""Independently check the symmetry clauses and decisive ID9/ID10 runs."""

from __future__ import annotations

import argparse
from collections import deque
from itertools import product
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence


LENGTH = 333


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_encoder(source_repo: Path):
    proof_dir = source_repo.resolve() / "lp333" / "proof_phase2"
    sys.path.insert(0, str(proof_dir))
    return importlib.import_module("lp333_cnf")


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


def independent_lex_clauses(
    variables: Sequence[int],
    mapping: Sequence[int],
    next_variable: int,
) -> tuple[list[tuple[int, ...]], int]:
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
    return clauses, next_variable


def exhaustive_lex_truth_table() -> dict[str, Any]:
    variables = (1, 2, 3, 4)
    mapping = (2, 3, 4, 1)
    clauses, next_variable = independent_lex_clauses(
        variables, mapping, 5
    )
    primary_assignments = 0
    full_assignments = 0
    for primary in product((False, True), repeat=4):
        expected = tuple(primary) <= tuple(
            primary[variable - 1] for variable in mapping
        )
        satisfiable_extensions = 0
        for auxiliary in product(
            (False, True), repeat=next_variable - 5
        ):
            assignment = [False] + list(primary) + list(auxiliary)
            satisfiable_extensions += int(
                clauses_hold(clauses, assignment)
            )
            full_assignments += 1
        if bool(satisfiable_extensions) != expected:
            raise ValueError("lex-leader truth table mismatch")
        if satisfiable_extensions > 1:
            raise ValueError("lex prefix auxiliaries are not functional")
        primary_assignments += 1
    return {
        "result": "PASS",
        "primary_assignments": primary_assignments,
        "full_assignments": full_assignments,
        "support": 4,
        "functional_auxiliary_extensions": True,
    }


def reconstruct_actions(
    spec: dict[str, Any], za: Sequence[int], zb: Sequence[int]
) -> list[tuple[int, bool, tuple[int, ...]]]:
    decimations: dict[tuple[int, ...], int] = {}
    for unit in range(1, LENGTH):
        if math.gcd(unit, LENGTH) != 1:
            continue
        permutation = tuple(
            spec["idx"][(unit * orbit[0]) % LENGTH]
            for orbit in spec["orbits"]
        )
        decimations.setdefault(permutation, unit)
    actions = []
    for permutation, unit in sorted(
        decimations.items(), key=lambda item: item[1]
    ):
        actions.append(
            (
                unit,
                False,
                tuple(
                    [za[permutation[index]] for index in range(len(za))]
                    + [zb[permutation[index]] for index in range(len(zb))]
                ),
            )
        )
        actions.append(
            (
                unit,
                True,
                tuple(
                    [zb[permutation[index]] for index in range(len(za))]
                    + [za[permutation[index]] for index in range(len(zb))]
                ),
            )
        )
    return actions


def read_last_clauses(path: Path, count: int) -> list[tuple[int, ...]]:
    result: deque[tuple[int, ...]] = deque(maxlen=count)
    with path.open("r", encoding="ascii") as handle:
        header = handle.readline()
        if not header.startswith("p cnf "):
            raise ValueError("invalid DIMACS header")
        for line in handle:
            values = [int(value) for value in line.split()]
            if not values or values[-1] != 0:
                raise ValueError("malformed DIMACS clause")
            result.append(tuple(values[:-1]))
    if len(result) != count:
        raise ValueError("formula has fewer clauses than expected")
    return list(result)


def verify_family(
    encoder: Any,
    family_id: int,
    metadata_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if metadata["family_id"] != family_id or manifest["family_id"] != family_id:
        raise ValueError("family ID mismatch")
    formula = Path(metadata["cnf"]["path"])
    if sha256_file(formula) != metadata["cnf"]["sha256"]:
        raise ValueError("formula hash mismatch")
    if manifest["inputs"]["encoding_metadata_sha256"] != sha256_file(
        metadata_path
    ):
        raise ValueError("manifest is bound to different metadata")
    if manifest["inputs"]["formula_sha256"] != sha256_file(formula):
        raise ValueError("manifest is bound to a different formula")

    proof_path = Path(manifest["solver"]["command"][-1])
    proof = manifest["solver"]["proof"]
    if (
        not proof_path.is_file()
        or sha256_file(proof_path) != proof["sha256"]
        or proof_path.stat().st_size != proof["bytes"]
    ):
        raise ValueError("proof artifact does not match the manifest")

    version_two_bindings = None
    if manifest.get("schema", "").endswith("-v2"):
        generator = Path(__file__).with_name(
            "generate_lp333_symmetry_cnf.py"
        )
        runner = Path(__file__).with_name(
            "run_lp333_symmetry_solver.py"
        )
        preregistration = Path(
            manifest["inputs"]["preregistration"]
        )
        preregistration_audit = Path(
            manifest["inputs"]["preregistration_audit"]
        )
        version_two_bindings = {
            "generator_sha256": (
                metadata["generator_sha256"] == sha256_file(generator)
            ),
            "runner_sha256": (
                manifest["runner_sha256"] == sha256_file(runner)
            ),
            "preregistration_sha256": (
                manifest["inputs"]["preregistration_sha256"]
                == sha256_file(preregistration)
            ),
            "preregistration_audit_sha256": (
                manifest["inputs"]["preregistration_audit_sha256"]
                == sha256_file(preregistration_audit)
            ),
            "preregistration_audit_pass": (
                json.loads(
                    preregistration_audit.read_text(encoding="utf-8")
                )["status"]
                == "pass"
            ),
        }
        if not all(version_two_bindings.values()):
            raise ValueError(
                f"v2 source or preregistration binding failed: "
                f"{version_two_bindings}"
            )

    model, _ = encoder.build_lp333_model(family_id)
    variables = tuple(model.za + model.zb)
    identity = tuple(variables)
    actions = [
        action
        for action in reconstruct_actions(
            model.spec, model.za, model.zb
        )
        if action[2] != identity
    ]
    if len(actions) != 71:
        raise ValueError("independent action reconstruction is not order 72")

    expected: list[tuple[int, ...]] = []
    next_variable = model.builder.num_vars + 1
    for _, _, mapping in actions:
        clauses, next_variable = independent_lex_clauses(
            variables, mapping, next_variable
        )
        expected.extend(clauses)
    if len(expected) != metadata["symmetry"]["added_clauses"]:
        raise ValueError("independent symmetry clause count mismatch")
    if next_variable - model.builder.num_vars - 1 != metadata[
        "symmetry"
    ]["added_auxiliaries"]:
        raise ValueError("independent symmetry auxiliary count mismatch")
    actual = read_last_clauses(formula, len(expected))
    if actual != expected:
        raise ValueError("serialized symmetry clause block mismatch")

    volume_applicable = manifest["significance"].get(
        "proof_volume_gate_applicable", True
    )
    run_checks = {
        "terminal_status": manifest["status"]
        in ("gate-pass", "proof-certified-unsat"),
        "solver_unsat": (
            manifest["solver"]["returncode"] == 20
            and manifest["solver"]["termination"] == "unsat"
        ),
        "proof_exists": proof["exists"],
        "first_replay": manifest["proof_checks"]["first_replay"][
            "accepted"
        ],
        "fresh_replay": manifest["proof_checks"]["fresh_replay"][
            "accepted"
        ],
        "fresh_bogus_rejected": manifest["proof_checks"]["fresh_bogus"][
            "rejected"
        ],
        "volume_gate": (
            not volume_applicable
            or manifest["significance"]["proof_volume_gate_pass"]
        ),
    }
    if not all(run_checks.values()):
        raise ValueError(f"decisive run checks failed: {run_checks}")
    return {
        "family_id": family_id,
        "result": "PASS",
        "formula_sha256": sha256_file(formula),
        "symmetry_actions": len(actions) + 1,
        "symmetry_clause_block_exact": True,
        "symmetry_clauses_checked": len(expected),
        "symmetry_auxiliaries_checked": (
            next_variable - model.builder.num_vars - 1
        ),
        "finite_orbit_argument": (
            "Every satisfying assignment has a lexicographically least "
            "representative in its finite 72-action orbit; each action "
            "preserves the original formula, so all lex-leaders preserve "
            "satisfiability."
        ),
        "run_checks": run_checks,
        "proof": proof,
        "solver_wall_seconds": manifest["solver"]["wall_seconds"],
        "first_replay_seconds": manifest["proof_checks"]["first_replay"][
            "wall_seconds"
        ],
        "fresh_replay_seconds": manifest["proof_checks"]["fresh_replay"][
            "wall_seconds"
        ],
        "metadata_sha256": sha256_file(metadata_path),
        "manifest_sha256": sha256_file(manifest_path),
        "version_two_bindings": version_two_bindings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--id9-metadata", required=True, type=Path)
    parser.add_argument("--id9-manifest", required=True, type=Path)
    parser.add_argument("--id10-metadata", required=True, type=Path)
    parser.add_argument("--id10-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    encoder = load_encoder(args.source_repo)
    truth_table = exhaustive_lex_truth_table()
    families = [
        verify_family(
            encoder, 9, args.id9_metadata, args.id9_manifest
        ),
        verify_family(
            encoder, 10, args.id10_metadata, args.id10_manifest
        ),
    ]
    output = {
        "schema": "frontiermath-lp333-symmetry-independent-check-v1",
        "status": "pass",
        "lex_leader_truth_table": truth_table,
        "families": families,
        "verifier_sha256": sha256_file(Path(__file__).resolve()),
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
