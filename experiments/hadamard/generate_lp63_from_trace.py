#!/usr/bin/env python3
"""Reconstruct the published prescribed-compression LP(63) from traces.

The source gives trace representations over GF(2^6), with primitive element
alpha satisfying x^6 + x^4 + x^3 + x + 1.  This dependency-free script
evaluates those traces, converts bits to signs, and globally normalizes both
sequences to the source's prescribed 9-compression.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


LENGTH = 63
P = 7
Q = 3
FIELD_DEGREE = 6
REDUCTION_LOW = 0b011011  # x^4 + x^3 + x + 1 after removing x^6
SOURCE_DOI = "10.1016/j.jsc.2026.102606"

A_TRACE_6 = (
    (31, 2),
    (23, 32),
    (13, 36),
    (11, 40),
    (7, 53),
    (5, 12),
    (3, 18),
    (1, 42),
)
B_TRACE_6 = (
    (31, 22),
    (23, 27),
    (15, 11),
    (13, 17),
    (11, 53),
    (7, 46),
    (5, 52),
    (1, 2),
)
A_TRACE_3 = (9, 0)
B_TRACE_3 = (27, 0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def field_multiply(left: int, right: int) -> int:
    result = 0
    while right:
        if right & 1:
            result ^= left
        right >>= 1
        left <<= 1
        if left & (1 << FIELD_DEGREE):
            left ^= REDUCTION_LOW
    return result & ((1 << FIELD_DEGREE) - 1)


def alpha_power(exponent: int) -> int:
    exponent %= (1 << FIELD_DEGREE) - 1
    result = 1
    base = 2  # polynomial x
    while exponent:
        if exponent & 1:
            result = field_multiply(result, base)
        base = field_multiply(base, base)
        exponent >>= 1
    return result


def absolute_trace(value: int, degree: int) -> int:
    result = 0
    current = value
    for _ in range(degree):
        result ^= current
        current = field_multiply(current, current)
    if result not in {0, 1}:
        raise ValueError(
            f"degree-{degree} trace escaped GF(2): {result}"
        )
    return result


def trace_sequence(
    degree6_terms: tuple[tuple[int, int], ...],
    degree3_term: tuple[int, int],
) -> list[int]:
    bits = []
    for index in range(LENGTH):
        bit = 0
        for multiplier, offset in degree6_terms:
            bit ^= absolute_trace(
                alpha_power(multiplier * index + offset), 6
            )
        multiplier, offset = degree3_term
        bit ^= absolute_trace(
            alpha_power(multiplier * index + offset), 3
        )
        bits.append(bit)
    # The trace formula produces the global negative of the convention used
    # for A_7,B_7 in the paper.  Negating all signs preserves every PAF.
    return [-1 if bit == 0 else 1 for bit in bits]


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[(index + shift) % len(sequence)]
        for index in range(len(sequence))
    )


def compress_to_p(sequence: list[int]) -> list[int]:
    return [
        sum(sequence[P * block + residue] for block in range(Q * Q))
        for residue in range(P)
    ]


def legendre_symbol(value: int) -> int:
    residue = pow(value % P, (P - 1) // 2, P)
    return 0 if residue == 0 else (1 if residue == 1 else -1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if len({alpha_power(exponent) for exponent in range(LENGTH)}) != LENGTH:
        raise ValueError("the selected alpha is not primitive in GF(2^6)")

    a = trace_sequence(A_TRACE_6, A_TRACE_3)
    b = trace_sequence(B_TRACE_6, B_TRACE_3)
    expected_a = [1] + [
        Q * legendre_symbol(index) for index in range(1, P)
    ]
    expected_b = [1] + [-value for value in expected_a[1:]]
    checks = {
        "a_row_sum": sum(a),
        "b_row_sum": sum(b),
        "a_compression": compress_to_p(a),
        "b_compression": compress_to_p(b),
        "combined_nonzero_paf": [
            periodic_autocorrelation(a, shift)
            + periodic_autocorrelation(b, shift)
            for shift in range(1, LENGTH)
        ],
    }
    if (
        checks["a_row_sum"] != 1
        or checks["b_row_sum"] != 1
        or checks["a_compression"] != expected_a
        or checks["b_compression"] != expected_b
        or checks["combined_nonzero_paf"] != [-2] * (LENGTH - 1)
    ):
        raise ValueError("trace reconstruction failed an exact identity")

    result = {
        "schema": "frontiermath-legendre-pair-calibration-v1",
        "status": "generated",
        "length": LENGTH,
        "p": P,
        "q": Q,
        "a_sequence": a,
        "b_sequence": b,
        "source": {
            "doi": SOURCE_DOI,
            "field": "GF(2^6)",
            "minimal_polynomial": "x^6+x^4+x^3+x+1",
            "a_trace6_terms": [list(term) for term in A_TRACE_6],
            "a_trace3_term": list(A_TRACE_3),
            "b_trace6_terms": [list(term) for term in B_TRACE_6],
            "b_trace3_term": list(B_TRACE_3),
        },
        "author_checks": checks,
        "claim_limit": (
            "published LP(63) calibration; not an LP(333) or H(668) candidate"
        ),
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
