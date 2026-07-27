#!/usr/bin/env python3
"""Dependency-free checker for an id3 value-set 9-compression witness."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path


EXPECTED_SCHEMA = "frontiermath-hadamard-id3-compression-v1"
EXPECTED_FAMILY_ID = 3
EXPECTED_LENGTH = 9
EXPECTED_PAF = -74
EXPECTED_NORM = 594
ORBIT_SIZES_MOD_37 = (1,) + (3,) * 12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value_set() -> set[int]:
    reachable = {0}
    for size in ORBIT_SIZES_MOD_37:
        reachable = (
            {value + size for value in reachable}
            | {value - size for value in reachable}
        )
    return reachable


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[(index + shift) % len(sequence)]
        for index in range(len(sequence))
    )


def violations(a: object, b: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(a, list) or not isinstance(b, list):
        return ["witness sequences must be JSON lists"]
    if len(a) != EXPECTED_LENGTH or len(b) != EXPECTED_LENGTH:
        return ["witness sequences must each have length 9"]
    if any(type(value) is not int for value in a + b):
        return ["every compressed value must be a JSON integer"]
    allowed = value_set()
    bad = [value for value in a + b if value not in allowed]
    if bad:
        problems.append(f"values outside exact id3 value set: {bad}")
    if sum(a) != 1 or sum(b) != 1:
        problems.append(f"row sums are {(sum(a), sum(b))}, expected (1, 1)")
    norm = sum(value * value for value in a + b)
    if norm != EXPECTED_NORM:
        problems.append(f"combined squared norm is {norm}, expected 594")
    pafs = [
        periodic_autocorrelation(a, shift)
        + periodic_autocorrelation(b, shift)
        for shift in range(1, EXPECTED_LENGTH)
    ]
    if pafs != [EXPECTED_PAF] * (EXPECTED_LENGTH - 1):
        problems.append(f"combined nonzero PAF profile is {pafs}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    started = time.perf_counter()
    try:
        document = json.loads(args.candidate.read_text(encoding="utf-8"))
        if document.get("schema") != EXPECTED_SCHEMA:
            raise ValueError("unexpected candidate schema")
        if document.get("family_id") != EXPECTED_FAMILY_ID:
            raise ValueError("unexpected multiplier family id")
        witness = document.get("witness")
        if not isinstance(witness, dict):
            raise ValueError("missing witness object")
        a = witness.get("a_tilde")
        b = witness.get("b_tilde")
        candidate_violations = violations(a, b)

        # Adversarial control: flipping one entry must not pass the same checker.
        mutated_a = list(a) if isinstance(a, list) else []
        if mutated_a:
            mutated_a[0] = -mutated_a[0]
        adversarial_rejected = bool(violations(mutated_a, b))
        passed = not candidate_violations and adversarial_rejected
        result = {
            "status": "pass" if passed else "fail",
            "claim_status": "compressed-necessary-condition-feasible",
            "family_id": EXPECTED_FAMILY_ID,
            "candidate_sha256": sha256_file(args.candidate),
            "checker_sha256": sha256_file(Path(__file__).resolve()),
            "checked_predicates": [
                "exact-id3-column-sum-value-set",
                "two-length-9-sequences",
                "normalized-row-sums",
                "combined-squared-norm",
                "all-eight-nonzero-periodic-autocorrelations",
            ],
            "candidate_violations": candidate_violations,
            "adversarial_single-entry-mutation_rejected": adversarial_rejected,
            "unchecked_predicates": [
                "decompression-to-orbit-signs",
                "all-332-Legendre-pair-autocorrelations",
                "construction-of-Hadamard-order-668",
            ],
            "runtime_seconds": time.perf_counter() - started,
            "environment": {
                "python": platform.python_version(),
                "machine": platform.machine(),
            },
        }
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        result = {
            "status": "error",
            "error": str(error),
            "runtime_seconds": time.perf_counter() - started,
        }

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
