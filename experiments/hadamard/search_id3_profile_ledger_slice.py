#!/usr/bin/env python3
"""Lift one ranked witness from the prescribed-profile ledger into full id3."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import ortools
from ortools.sat.python import cp_model

from search_id3_compression_slice import (
    add_compression_constraints,
    load_artifact_modules,
)
from search_id3_double_compression_slice import add_margin_hint
from search_id3_prescribed_q2_slice import (
    add_mod37_compression_constraints,
    prescribed_pair,
)


FAMILY_ID = 3
LENGTH = 333


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def singleton_sign(value: int) -> int:
    return 1 if value % 3 == 1 else -1


def margin_record(record: dict[str, object], sequence: str) -> dict[str, object]:
    values = list(record[f"{sequence}_tilde"])
    binary_margin = record[f"{sequence}_margin_9_by_12"]
    sign_matrix = [
        [singleton_sign(values[row])]
        + [1 if entry else -1 for entry in binary_margin[row]]
        for row in range(9)
    ]
    # The K37 orbit order is fixed and independently reconstructed here.
    k37 = (1, 10, 26)
    unseen = set(range(37))
    orbits = []
    while unseen:
        seed = min(unseen)
        orbit = sorted({(multiplier * seed) % 37 for multiplier in k37})
        unseen.difference_update(orbit)
        orbits.append(orbit)
    return {
        "sign_matrix_9_by_13": sign_matrix,
        "k37_orbits": orbits,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_ledger", type=Path)
    parser.add_argument("--profile-id", required=True, type=int)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    ledger = json.loads(args.profile_ledger.read_text(encoding="utf-8"))
    record = next(
        item for item in ledger["records"] if item["id"] == args.profile_id
    )
    if record.get("feasible") is not True:
        raise ValueError("selected profile has no verified compressed witness")
    a_tilde = list(record["a_tilde"])
    b_tilde = list(record["b_tilde"])
    if singleton_sign(a_tilde[0]) != 1 or singleton_sign(b_tilde[0]) != 1:
        raise ValueError(
            "selected profile is incompatible with the base origin normalization"
        )
    prescribed_a, prescribed_b = prescribed_pair()

    core, search_common, cpsat_search = load_artifact_modules(args.source_repo)
    subgroup, subgroup_record = search_common.subgroup_by_id(FAMILY_ID)
    spec = search_common.build_spec(subgroup)
    model, za, zb = cpsat_search.build_model(spec)
    add_compression_constraints(model, za, spec, a_tilde)
    add_compression_constraints(model, zb, spec, b_tilde)
    add_mod37_compression_constraints(model, za, spec, prescribed_a)
    add_mod37_compression_constraints(model, zb, spec, prescribed_b)
    add_margin_hint(model, za, spec, margin_record(record, "a"))
    add_margin_hint(model, zb, spec, margin_record(record, "b"))

    proto = model.Proto()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.max_seconds
    solver.parameters.num_search_workers = args.workers
    solver.parameters.random_seed = args.seed + args.profile_id
    started = time.perf_counter()
    status = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status_name = solver.StatusName(status)
    result: dict[str, object] = {
        "schema": "frontiermath-hadamard-id3-profile-ledger-slice-v1",
        "family_id": FAMILY_ID,
        "profile_id": args.profile_id,
        "square_counts": record["square_counts"],
        "status": status_name,
        "scope": (
            "one ranked prescribed-margin compressed profile inside the "
            "complete common-multiplier id3 PAF model"
        ),
        "claim_limit": (
            "UNKNOWN has no negative force; uncertified INFEASIBLE closes "
            "only this exact profile slice"
        ),
        "inputs": {
            "profile_ledger_sha256": sha256_file(args.profile_ledger),
            "a_tilde": a_tilde,
            "b_tilde": b_tilde,
        },
        "model": {
            "orbit_variables_per_sequence": spec["r"],
            "nonzero_shift_orbits": spec["num_reps"],
            "proto_variables": len(proto.variables),
            "proto_constraints": len(proto.constraints),
            "primary_orbit_hints": 234,
            "base_model": "lp333/code/cpsat_search.py",
        },
        "solver": {
            "name": "OR-Tools CP-SAT",
            "version": ortools.__version__,
            "max_seconds": args.max_seconds,
            "workers": args.workers,
            "random_seed": args.seed + args.profile_id,
            "wall_seconds": elapsed,
            "branches": solver.NumBranches(),
            "conflicts": solver.NumConflicts(),
        },
        "source": {
            "repository": str(args.source_repo.resolve()),
            "subgroup_record": subgroup_record,
            "paper_doi": "10.1016/j.jsc.2026.102606",
            "base_model_sha256": sha256_file(
                args.source_repo.resolve() / "lp333" / "code" / "cpsat_search.py"
            ),
        },
        "environment": {
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        xa = [1 - 2 * solver.Value(variable) for variable in za]
        xb = [1 - 2 * solver.Value(variable) for variable in zb]
        index = spec["idx"]
        a = [xa[index[position]] for position in range(LENGTH)]
        b = [xb[index[position]] for position in range(LENGTH)]
        verified, message = core.is_legendre_pair(a, b)
        result.update(
            {
                "sat": True,
                "verified_legendre_pair": verified,
                "verify_message": message,
                "a_orbit_values": xa,
                "b_orbit_values": xb,
            }
        )
        if verified:
            result["a_sequence"] = a
            result["b_sequence"] = b
    elif status == cp_model.INFEASIBLE:
        result.update(
            {
                "sat": False,
                "solver_infeasible": True,
                "replayable_unsat_certificate": False,
            }
        )
    else:
        result["sat"] = None

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
