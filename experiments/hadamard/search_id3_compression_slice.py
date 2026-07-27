#!/usr/bin/env python3
"""Search the exact id3 orbit model inside one verified 9-compression slice.

The base Booleanized PAF model is imported from the pinned LP(333) artifact.
This script adds 18 exact column-sum equations from a compressed witness.  A
SAT result is independently checked against all 332 length-333 PAF equations
by the artifact's direct checker.  UNKNOWN or an uncertified INFEASIBLE result
does not close id3.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import sys
import time
from pathlib import Path

import ortools
from ortools.sat.python import cp_model


FAMILY_ID = 3
LENGTH = 333
COMPRESSION_LENGTH = 9


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_artifact_modules(source_repo: Path):
    code_dir = source_repo.resolve() / "lp333" / "code"
    if not code_dir.is_dir():
        raise ValueError(f"missing LP(333) code directory: {code_dir}")
    sys.path.insert(0, str(code_dir))
    core = importlib.import_module("core")
    search_common = importlib.import_module("search_common")
    cpsat_search = importlib.import_module("cpsat_search")
    return core, search_common, cpsat_search


def orient_for_fixed_origin(values: list[int]) -> list[int]:
    """Orient a compressed sequence so the singleton orbit {0} has value +1.

    For id3, every mod-9 column is one singleton plus twelve size-3 orbits.
    Hence the singleton sign is the column sum modulo 3.  The base exact model
    fixes the origin singleton to +1.
    """

    if values[0] % 3 == 1:
        return values
    flipped = [-value for value in values]
    if flipped[0] % 3 != 1:
        raise ValueError("compressed origin column has no valid singleton sign")
    return flipped


def add_compression_constraints(
    model: cp_model.CpModel,
    z_variables: list[cp_model.IntVar],
    spec: dict[str, object],
    target: list[int],
) -> None:
    orbits = spec["orbits"]
    sizes = spec["sizes"]
    for residue in range(COMPRESSION_LENGTH):
        orbit_indices = []
        for orbit_index, orbit in enumerate(orbits):
            residues = {element % COMPRESSION_LENGTH for element in orbit}
            if len(residues) != 1:
                raise ValueError(
                    f"id3 orbit {orbit_index} crosses mod-9 columns: {residues}"
                )
            if residue in residues:
                orbit_indices.append(orbit_index)
        if sum(sizes[index] for index in orbit_indices) != 37:
            raise ValueError(f"column {residue} does not contain 37 positions")
        # x_q = 1 - 2 z_q, so this is exactly the full column sum.
        model.Add(
            sum(
                sizes[index] * (1 - 2 * z_variables[index])
                for index in orbit_indices
            )
            == target[residue]
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("compressed_witness", type=Path)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    compressed_document = json.loads(
        args.compressed_witness.read_text(encoding="utf-8")
    )
    if compressed_document.get("family_id") != FAMILY_ID:
        raise ValueError("compressed witness is not for id3")
    witness = compressed_document.get("witness")
    if not isinstance(witness, dict):
        raise ValueError("compressed witness has no witness object")
    a_tilde = orient_for_fixed_origin(list(witness["a_tilde"]))
    b_tilde = orient_for_fixed_origin(list(witness["b_tilde"]))

    core, search_common, cpsat_search = load_artifact_modules(args.source_repo)
    subgroup, subgroup_record = search_common.subgroup_by_id(FAMILY_ID)
    spec = search_common.build_spec(subgroup)
    if spec["r"] != 117 or len(subgroup) != 3:
        raise ValueError("pinned id3 orbit signature changed")

    model, za, zb = cpsat_search.build_model(spec)
    add_compression_constraints(model, za, spec, a_tilde)
    add_compression_constraints(model, zb, spec, b_tilde)

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
        "schema": "frontiermath-hadamard-id3-exact-slice-v1",
        "family_id": FAMILY_ID,
        "status": status_name,
        "scope": "one exact 9-compression slice of the id3 orbit model",
        "claim_limit": (
            "UNKNOWN is no evidence of infeasibility; INFEASIBLE lacks a "
            "replayable proof artifact and closes only this one slice"
        ),
        "compressed_witness_sha256": sha256_file(args.compressed_witness),
        "oriented_compression": {
            "a_tilde": a_tilde,
            "b_tilde": b_tilde,
            "a_row_sum": sum(a_tilde),
            "b_row_sum": sum(b_tilde),
        },
        "model": {
            "orbit_variables_per_sequence": spec["r"],
            "nonzero_shift_orbits": spec["num_reps"],
            "proto_variables": len(proto.variables),
            "proto_constraints": len(proto.constraints),
            "added_compression_equalities": 18,
            "base_model": "lp333/code/cpsat_search.py",
        },
        "source": {
            "repository": str(args.source_repo.resolve()),
            "subgroup_elements": sorted(subgroup),
            "subgroup_record": subgroup_record,
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
