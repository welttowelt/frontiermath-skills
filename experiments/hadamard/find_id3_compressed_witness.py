#!/usr/bin/env python3
"""Find an exact feasible 9-compression for multiplier family id3.

This decides only the compressed necessary conditions.  A satisfying pair is
not a Legendre pair and not a Hadamard matrix; it is a search slice for the
117-orbit exact model.
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


FAMILY_ID = 3
LENGTH = 333
COMPRESSION_LENGTH = 9
TARGET_PAF = -74
TARGET_NORM = 594
ORBIT_SIZES_MOD_37 = (1,) + (3,) * 12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_set(orbit_sizes: tuple[int, ...]) -> list[int]:
    reachable = {0}
    for size in orbit_sizes:
        reachable = (
            {value + size for value in reachable}
            | {value - size for value in reachable}
        )
    return sorted(reachable)


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[(index + shift) % len(sequence)]
        for index in range(len(sequence))
    )


def solve(max_seconds: float, workers: int, seed: int) -> dict[str, object]:
    values = value_set(ORBIT_SIZES_MOD_37)
    model = cp_model.CpModel()
    domain = cp_model.Domain.FromValues(values)
    a = [
        model.NewIntVarFromDomain(domain, f"a_{index}")
        for index in range(COMPRESSION_LENGTH)
    ]
    b = [
        model.NewIntVarFromDomain(domain, f"b_{index}")
        for index in range(COMPRESSION_LENGTH)
    ]

    # Independent global sign changes preserve every PAF, so both row sums may
    # be normalized to +1 without losing feasibility.
    model.Add(sum(a) == 1)
    model.Add(sum(b) == 1)

    norm_terms = []
    for name, sequence in (("a", a), ("b", b)):
        for index, variable in enumerate(sequence):
            square = model.NewIntVar(0, 37 * 37, f"{name}_sq_{index}")
            model.AddMultiplicationEquality(square, [variable, variable])
            norm_terms.append(square)
    model.Add(sum(norm_terms) == TARGET_NORM)

    # For odd length 9, PAF(s) = PAF(9-s), so shifts 1..4 are the complete
    # independent set.  Each unordered position pair occurs in exactly one.
    for shift in range(1, 5):
        products = []
        for name, sequence in (("a", a), ("b", b)):
            for index in range(COMPRESSION_LENGTH):
                product = model.NewIntVar(
                    -(37 * 37),
                    37 * 37,
                    f"{name}_paf_{shift}_{index}",
                )
                model.AddMultiplicationEquality(
                    product,
                    [
                        sequence[index],
                        sequence[(index + shift) % COMPRESSION_LENGTH],
                    ],
                )
                products.append(product)
        model.Add(sum(products) == TARGET_PAF)

    # Sequence exchange is a symmetry.  Ordering their squared norms removes
    # roughly half of that duplication without constraining either sequence's
    # cyclic arrangement.
    a_norm = model.NewIntVar(0, TARGET_NORM, "a_norm")
    b_norm = model.NewIntVar(0, TARGET_NORM, "b_norm")
    model.Add(a_norm == sum(norm_terms[:COMPRESSION_LENGTH]))
    model.Add(b_norm == sum(norm_terms[COMPRESSION_LENGTH:]))
    model.Add(a_norm <= b_norm)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = seed

    started = time.perf_counter()
    status = solver.Solve(model)
    elapsed = time.perf_counter() - started
    status_name = solver.StatusName(status)

    result: dict[str, object] = {
        "schema": "frontiermath-hadamard-id3-compression-v1",
        "status": status_name,
        "family_id": FAMILY_ID,
        "length": LENGTH,
        "compression_length": COMPRESSION_LENGTH,
        "value_set": values,
        "value_set_size": len(values),
        "orbit_sizes_mod_37": list(ORBIT_SIZES_MOD_37),
        "constraints": {
            "row_sums": [1, 1],
            "combined_periodic_paf_nonzero_shifts": TARGET_PAF,
            "combined_squared_norm": TARGET_NORM,
        },
        "scope": (
            "feasibility of the exact value-set-restricted 9-compression only"
        ),
        "claim_limit": (
            "a feasible compressed pair is not an LP(333) and not H(668)"
        ),
        "solver": {
            "name": "OR-Tools CP-SAT",
            "version": ortools.__version__,
            "max_seconds": max_seconds,
            "workers": workers,
            "random_seed": seed,
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
        av = [solver.Value(variable) for variable in a]
        bv = [solver.Value(variable) for variable in b]
        checks = {
            "a_row_sum": sum(av),
            "b_row_sum": sum(bv),
            "combined_squared_norm": sum(
                value * value for value in av + bv
            ),
            "combined_periodic_paf": [
                periodic_autocorrelation(av, shift)
                + periodic_autocorrelation(bv, shift)
                for shift in range(1, COMPRESSION_LENGTH)
            ],
        }
        result["witness"] = {"a_tilde": av, "b_tilde": bv}
        result["author_checks"] = checks
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=120.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260726)
    args = parser.parse_args()

    result = solve(args.max_seconds, args.workers, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"OPTIMAL", "FEASIBLE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
