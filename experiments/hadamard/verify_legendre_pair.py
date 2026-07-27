#!/usr/bin/env python3
"""Dependency-free exact checker for a serialized binary Legendre pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[(index + shift) % len(sequence)]
        for index in range(len(sequence))
    )


def legendre_symbol(value: int, prime: int) -> int:
    residue = pow(value % prime, (prime - 1) // 2, prime)
    return 0 if residue == 0 else (1 if residue == 1 else -1)


def violations(
    a: object,
    b: object,
    length: int,
    prescribed_p: int | None,
    prescribed_q: int | None,
) -> list[str]:
    problems = []
    if not isinstance(a, list) or not isinstance(b, list):
        return ["sequences must be JSON lists"]
    if len(a) != length or len(b) != length:
        return [f"both sequences must have length {length}"]
    if any(type(value) is not int or value not in {-1, 1} for value in a + b):
        return ["every entry must be the JSON integer -1 or 1"]
    if sum(a) not in {-1, 1} or sum(b) not in {-1, 1}:
        problems.append(f"row sums are {(sum(a), sum(b))}")
    bad_shifts = [
        {
            "shift": shift,
            "combined_paf": (
                periodic_autocorrelation(a, shift)
                + periodic_autocorrelation(b, shift)
            ),
        }
        for shift in range(1, length)
        if (
            periodic_autocorrelation(a, shift)
            + periodic_autocorrelation(b, shift)
        )
        != -2
    ]
    if bad_shifts:
        problems.append(f"bad PAF shifts: {bad_shifts[:3]}")

    if prescribed_p is not None or prescribed_q is not None:
        if prescribed_p is None or prescribed_q is None:
            problems.append("both prescribed p and q are required")
        elif length != prescribed_p * prescribed_q * prescribed_q:
            problems.append("length is not p*q^2")
        else:
            factor = prescribed_q * prescribed_q
            compressed_a = [
                sum(
                    a[prescribed_p * block + residue]
                    for block in range(factor)
                )
                for residue in range(prescribed_p)
            ]
            compressed_b = [
                sum(
                    b[prescribed_p * block + residue]
                    for block in range(factor)
                )
                for residue in range(prescribed_p)
            ]
            expected_a = [1] + [
                prescribed_q * legendre_symbol(index, prescribed_p)
                for index in range(1, prescribed_p)
            ]
            expected_b = [1] + [-value for value in expected_a[1:]]
            if compressed_a != expected_a or compressed_b != expected_b:
                problems.append(
                    "prescribed compression mismatch: "
                    f"{compressed_a}, {compressed_b}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--length", required=True, type=int)
    parser.add_argument("--prescribed-p", type=int)
    parser.add_argument("--prescribed-q", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    started = time.perf_counter()
    try:
        document = json.loads(args.candidate.read_text(encoding="utf-8"))
        a = document.get("a_sequence")
        b = document.get("b_sequence")
        candidate_violations = violations(
            a, b, args.length, args.prescribed_p, args.prescribed_q
        )
        mutated_a = list(a) if isinstance(a, list) else []
        if mutated_a:
            mutated_a[0] = -mutated_a[0]
        adversarial_rejected = bool(
            violations(
                mutated_a,
                b,
                args.length,
                args.prescribed_p,
                args.prescribed_q,
            )
        )
        passed = not candidate_violations and adversarial_rejected
        result = {
            "status": "pass" if passed else "fail",
            "claim_status": "published-calibration-reproduced",
            "length": args.length,
            "candidate_sha256": sha256_file(args.candidate),
            "checker_sha256": sha256_file(Path(__file__).resolve()),
            "checked_predicates": [
                "length",
                "binary-entry-domain",
                "row-sums",
                "all-nonzero-periodic-autocorrelations",
                "prescribed-pq2-compression",
            ],
            "candidate_violations": candidate_violations,
            "adversarial_single-entry_mutation_rejected": adversarial_rejected,
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
