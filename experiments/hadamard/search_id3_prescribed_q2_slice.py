#!/usr/bin/env python3
"""Test the Kotsireas q^2-compression prescription inside LP(333) id3.

For p=37 and q=3, the prescribed length-37 compressed pair is

    A[0] = B[0] = 1,
    A[i] = 3 * Legendre(i, 37),
    B[i] = -A[i]                       for i != 0.

The cited conjecture says this pair can be decompressed to an LP(333).  This
script tests the more restrictive case where both decompressed sequences are
also fixed by multiplier family id3.  An optional verified length-9 witness can
be imposed simultaneously to test one double-compression slice.
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
    orient_for_fixed_origin,
)


FAMILY_ID = 3
LENGTH = 333
P = 37
Q = 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def legendre_symbol(value: int, prime: int) -> int:
    residue = pow(value % prime, (prime - 1) // 2, prime)
    if residue == 1:
        return 1
    if residue == prime - 1:
        return -1
    if residue == 0:
        return 0
    raise ValueError("Euler criterion returned an unexpected residue")


def prescribed_pair() -> tuple[list[int], list[int]]:
    a = [1] + [Q * legendre_symbol(index, P) for index in range(1, P)]
    b = [1] + [-value for value in a[1:]]
    return a, b


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[(index + shift) % len(sequence)]
        for index in range(len(sequence))
    )


def add_mod37_compression_constraints(
    model: cp_model.CpModel,
    z_variables: list[cp_model.IntVar],
    spec: dict[str, object],
    target: list[int],
) -> None:
    orbits = spec["orbits"]
    for residue in range(P):
        terms = []
        positions = 0
        for orbit_index, orbit in enumerate(orbits):
            multiplicity = sum(
                1 for element in orbit if element % P == residue
            )
            if multiplicity:
                terms.append(
                    multiplicity * (1 - 2 * z_variables[orbit_index])
                )
                positions += multiplicity
        if positions != Q * Q:
            raise ValueError(
                f"mod-37 column {residue} has {positions} positions, expected 9"
            )
        model.Add(sum(terms) == target[residue])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--length9-witness", type=Path)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    prescribed_a, prescribed_b = prescribed_pair()
    prescribed_checks = {
        "a_row_sum": sum(prescribed_a),
        "b_row_sum": sum(prescribed_b),
        "a_squared_norm": sum(value * value for value in prescribed_a),
        "b_squared_norm": sum(value * value for value in prescribed_b),
        "combined_nonzero_paf": [
            periodic_autocorrelation(prescribed_a, shift)
            + periodic_autocorrelation(prescribed_b, shift)
            for shift in range(1, P)
        ],
    }
    expected_paf = -2 * Q * Q
    if (
        prescribed_checks["a_row_sum"] != 1
        or prescribed_checks["b_row_sum"] != 1
        or prescribed_checks["a_squared_norm"] != 325
        or prescribed_checks["b_squared_norm"] != 325
        or prescribed_checks["combined_nonzero_paf"]
        != [expected_paf] * (P - 1)
    ):
        raise ValueError("the prescribed q^2-compression failed exact checks")

    core, search_common, cpsat_search = load_artifact_modules(args.source_repo)
    subgroup, subgroup_record = search_common.subgroup_by_id(FAMILY_ID)
    spec = search_common.build_spec(subgroup)
    if spec["r"] != 117 or len(subgroup) != 3:
        raise ValueError("pinned id3 orbit signature changed")

    model, za, zb = cpsat_search.build_model(spec)
    add_mod37_compression_constraints(model, za, spec, prescribed_a)
    add_mod37_compression_constraints(model, zb, spec, prescribed_b)

    length9_record = None
    if args.length9_witness is not None:
        document = json.loads(
            args.length9_witness.read_text(encoding="utf-8")
        )
        if document.get("family_id") != FAMILY_ID:
            raise ValueError("length-9 witness is not for id3")
        witness = document.get("witness")
        if not isinstance(witness, dict):
            raise ValueError("length-9 witness has no witness object")
        a_tilde = orient_for_fixed_origin(list(witness["a_tilde"]))
        b_tilde = orient_for_fixed_origin(list(witness["b_tilde"]))
        add_compression_constraints(model, za, spec, a_tilde)
        add_compression_constraints(model, zb, spec, b_tilde)
        length9_record = {
            "source_sha256": sha256_file(args.length9_witness),
            "a_tilde": a_tilde,
            "b_tilde": b_tilde,
        }

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
        "schema": "frontiermath-hadamard-id3-prescribed-q2-slice-v1",
        "family_id": FAMILY_ID,
        "status": status_name,
        "scope": (
            "Kotsireas q^2-compression prescription within common-multiplier "
            "family id3"
            + (
                ", intersected with one length-9 compression witness"
                if length9_record is not None
                else ""
            )
        ),
        "claim_limit": (
            "this is stricter than the unrestricted decompression conjecture; "
            "UNKNOWN has no negative force and INFEASIBLE would address only "
            "the stated id3 slice without a replayable proof"
        ),
        "prescribed_q2_compression": {
            "p": P,
            "q": Q,
            "a": prescribed_a,
            "b": prescribed_b,
            "exact_checks": prescribed_checks,
            "source_doi": "10.1016/j.jsc.2026.102606",
            "author_slides": (
                "https://us.ticmeet.com/assets/archivos/"
                "d6f1d9b8-d39f-4888-925a-7eb81c4905cc/Gomez.pdf"
            ),
        },
        "length9_compression": length9_record,
        "model": {
            "orbit_variables_per_sequence": spec["r"],
            "nonzero_shift_orbits": spec["num_reps"],
            "proto_variables": len(proto.variables),
            "proto_constraints": len(proto.constraints),
            "mod37_compression_equalities": 74,
            "length9_compression_equalities": (
                18 if length9_record is not None else 0
            ),
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
