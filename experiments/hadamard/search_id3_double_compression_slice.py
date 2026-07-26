#!/usr/bin/env python3
"""Search one correctly oriented double-compression slice of id3.

This combines:

* a verified feasible length-9 compression;
* the Kotsireas length-37 q^2-compression prescription; and
* the complete id3-invariant PAF model.

Global sign orientation is shared by both compression axes.  A dependency-free
margin ledger supplies an exact 9x13 sign table, used only as a solver hint.
"""

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
from search_id3_prescribed_q2_slice import (
    add_mod37_compression_constraints,
)


FAMILY_ID = 3
LENGTH = 333


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_margin_hint(
    model: cp_model.CpModel,
    z_variables: list[cp_model.IntVar],
    spec: dict[str, object],
    margin_record: dict[str, object],
) -> None:
    sign_matrix = margin_record["sign_matrix_9_by_13"]
    k37_orbits = [set(orbit) for orbit in margin_record["k37_orbits"]]
    if sign_matrix is None:
        raise ValueError("margin ledger contains no compatible sign matrix")

    for orbit_index, orbit in enumerate(spec["orbits"]):
        mod9 = {element % 9 for element in orbit}
        mod37 = {element % 37 for element in orbit}
        if len(mod9) != 1:
            raise ValueError(f"orbit {orbit_index} crosses mod-9 rows")
        row = next(iter(mod9))
        try:
            column = next(
                index
                for index, residues in enumerate(k37_orbits)
                if residues == mod37
            )
        except StopIteration as error:
            raise ValueError(
                f"orbit {orbit_index} has unexpected mod-37 residues {mod37}"
            ) from error
        sign = sign_matrix[row][column]
        model.AddHint(z_variables[orbit_index], 0 if sign == 1 else 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("length9_witness", type=Path)
    parser.add_argument("margin_ledger", type=Path)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    witness_document = json.loads(
        args.length9_witness.read_text(encoding="utf-8")
    )
    ledger = json.loads(args.margin_ledger.read_text(encoding="utf-8"))
    if witness_document.get("family_id") != FAMILY_ID:
        raise ValueError("length-9 witness is not for id3")
    if ledger.get("family_id") != FAMILY_ID or ledger.get("status") != "compatible":
        raise ValueError("margin ledger is not a compatible id3 ledger")
    if ledger.get("length9_witness_sha256") != sha256_file(
        args.length9_witness
    ):
        raise ValueError("margin ledger is bound to another length-9 witness")

    a_record = ledger["a"]
    b_record = ledger["b"]
    a_tilde = list(a_record["oriented_length9_row_sums"])
    b_tilde = list(b_record["oriented_length9_row_sums"])
    prescribed_a = list(a_record["oriented_length37_columns"])
    prescribed_b = list(b_record["oriented_length37_columns"])

    core, search_common, cpsat_search = load_artifact_modules(args.source_repo)
    subgroup, subgroup_record = search_common.subgroup_by_id(FAMILY_ID)
    spec = search_common.build_spec(subgroup)
    if spec["r"] != 117 or len(subgroup) != 3:
        raise ValueError("pinned id3 orbit signature changed")

    model, za, zb = cpsat_search.build_model(spec)
    add_compression_constraints(model, za, spec, a_tilde)
    add_compression_constraints(model, zb, spec, b_tilde)
    add_mod37_compression_constraints(model, za, spec, prescribed_a)
    add_mod37_compression_constraints(model, zb, spec, prescribed_b)
    add_margin_hint(model, za, spec, a_record)
    add_margin_hint(model, zb, spec, b_record)

    proto = model.Proto()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.max_seconds
    solver.parameters.num_search_workers = args.workers
    solver.parameters.random_seed = args.seed
    started = time.perf_counter()
    status = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status_name = solver.StatusName(status)

    result: dict[str, object] = {
        "schema": "frontiermath-hadamard-id3-double-compression-slice-v1",
        "family_id": FAMILY_ID,
        "status": status_name,
        "scope": (
            "one correctly oriented intersection of a verified length-9 "
            "compression and the prescribed length-37 q^2 compression, "
            "inside common-multiplier id3"
        ),
        "claim_limit": (
            "UNKNOWN has no negative force; INFEASIBLE without a replayable "
            "proof closes only this exact joint slice"
        ),
        "inputs": {
            "length9_witness_sha256": sha256_file(args.length9_witness),
            "margin_ledger_sha256": sha256_file(args.margin_ledger),
            "a_tilde": a_tilde,
            "b_tilde": b_tilde,
            "prescribed_a": prescribed_a,
            "prescribed_b": prescribed_b,
        },
        "model": {
            "orbit_variables_per_sequence": spec["r"],
            "nonzero_shift_orbits": spec["num_reps"],
            "proto_variables": len(proto.variables),
            "proto_constraints": len(proto.constraints),
            "length9_compression_equalities": 18,
            "mod37_compression_equalities": 74,
            "primary_orbit_hints": 234,
            "base_model": "lp333/code/cpsat_search.py",
        },
        "source": {
            "repository": str(args.source_repo.resolve()),
            "subgroup_elements": sorted(subgroup),
            "subgroup_record": subgroup_record,
            "paper_doi": "10.1016/j.jsc.2026.102606",
            "base_model_sha256": sha256_file(
                args.source_repo.resolve() / "lp333" / "code" / "cpsat_search.py"
            ),
            "search_common_sha256": sha256_file(
                args.source_repo.resolve() / "lp333" / "code" / "search_common.py"
            ),
        },
        "solver": {
            "name": "OR-Tools CP-SAT",
            "version": ortools.__version__,
            "max_seconds": args.max_seconds,
            "workers": args.workers,
            "random_seed": args.seed,
            "wall_seconds": elapsed,
            "conflicts": solver.NumConflicts(),
            "branches": solver.NumBranches(),
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
