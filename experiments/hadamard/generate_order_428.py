#!/usr/bin/env python3
"""Generate the published order-428 Hadamard warmup deterministically.

Construction path:

    TT(36) -> BS(71, 36) -> T(107) -> Cooper-Wallis with W(1)

The Turyn-type sequence is encoded in SageMath's ``t_sequences.py`` at commit
842f12bada41bbae3498a8ead95006cfc4c04946. Sage attributes the data and
construction to Kharaghani and Tayfeh-Rezaie,
"A Hadamard matrix of order 428", DOI 10.1002/jcd.20043.

This script is a dependency-free port of the mathematical construction. It is
not an independent verifier; verification belongs to the contract-bound
checker and a separately implemented integer Gram checker.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


ORDER = 428
T_LENGTH = 107
TT36_HEX = "060989975b685d8fc80750b21c0212eceb26"
SAGE_COMMIT = "842f12bada41bbae3498a8ead95006cfc4c04946"
PRIMARY_DOI = "10.1002/jcd.20043"


Matrix = list[list[int]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_turyn_type(hex_string: str) -> tuple[list[int], ...]:
    sequences: list[list[int]] = [[], [], [], []]
    for digit in hex_string[:-1]:
        bits = bin(int(digit, 16))[2:].zfill(4)
        for index, bit in enumerate(bits):
            sequences[index].append(1 if bit == "0" else -1)
    final_bits = bin(int(hex_string[-1], 16))[2:].zfill(3)
    for index, bit in enumerate(final_bits):
        sequences[index].append(1 if bit == "0" else -1)
    result = tuple(sequences)
    assert tuple(map(len, result)) == (36, 36, 36, 35)
    return result


def nonperiodic_autocorrelation(sequence: list[int], shift: int) -> int:
    return sum(
        sequence[index] * sequence[index + shift]
        for index in range(len(sequence) - shift)
    )


def periodic_autocorrelation(sequence: list[int], shift: int) -> int:
    size = len(sequence)
    return sum(
        sequence[index] * sequence[(index + shift) % size]
        for index in range(size)
    )


def validate_turyn_type(sequences: tuple[list[int], ...]) -> None:
    # Turyn-type sequences satisfy
    # N_X(s) + N_Y(s) + 2 N_Z(s) + 2 N_W(s) = 0 for every s > 0.
    # The factor of two is also what makes the concatenation below a base
    # sequence: N_A + N_B = 2 N_Z + 2 N_W.
    weights = (1, 1, 2, 2)
    for shift in range(1, 36):
        total = sum(
            weight * nonperiodic_autocorrelation(sequence, shift)
            for weight, sequence in zip(weights, sequences)
        )
        if total != 0:
            raise ValueError(
                f"Turyn-type autocorrelation failed at shift {shift}: {total}"
            )


def base_sequences(
    turyn_type: tuple[list[int], ...],
) -> tuple[list[int], ...]:
    x, y, z, w = turyn_type
    a = z + w
    b = z + [-value for value in w]
    c = x
    d = y
    result = (a, b, c, d)
    assert tuple(map(len, result)) == (71, 71, 36, 36)
    for shift in range(1, 71):
        total = sum(
            nonperiodic_autocorrelation(sequence, shift)
            for sequence in result
        )
        if total != 0:
            raise ValueError(
                f"base-sequence autocorrelation failed at shift {shift}: {total}"
            )
    return result


def t_sequences(base: tuple[list[int], ...]) -> tuple[list[int], ...]:
    a, b, c, d = base
    n = len(c)
    p = len(a) - n

    t1 = [(left + right) // 2 for left, right in zip(a, b)] + [0] * n
    t2 = [(left - right) // 2 for left, right in zip(a, b)] + [0] * n
    t3 = [0] * (n + p) + [
        (left + right) // 2 for left, right in zip(c, d)
    ]
    t4 = [0] * (n + p) + [
        (left - right) // 2 for left, right in zip(c, d)
    ]
    result = (t1, t2, t3, t4)
    assert all(len(sequence) == T_LENGTH for sequence in result)

    for index in range(T_LENGTH):
        support = sum(abs(sequence[index]) for sequence in result)
        if support != 1:
            raise ValueError(
                f"T-sequence support partition failed at index {index}: {support}"
            )
    for shift in range(1, T_LENGTH):
        total = sum(
            periodic_autocorrelation(sequence, shift)
            for sequence in result
        )
        if total != 0:
            raise ValueError(
                f"T-sequence periodic autocorrelation failed at shift "
                f"{shift}: {total}"
            )
    return result


def circulant(first_row: list[int]) -> Matrix:
    size = len(first_row)
    return [
        [first_row[(column - row) % size] for column in range(size)]
        for row in range(size)
    ]


def transpose(matrix: Matrix) -> Matrix:
    return [list(column) for column in zip(*matrix)]


def reverse_columns(matrix: Matrix) -> Matrix:
    return [list(reversed(row)) for row in matrix]


def negate(matrix: Matrix) -> Matrix:
    return [[-value for value in row] for row in matrix]


def goethals_seidel_blocks(
    a: Matrix,
    b: Matrix,
    c: Matrix,
    d: Matrix,
) -> list[list[Matrix]]:
    br = reverse_columns(b)
    cr = reverse_columns(c)
    dr = reverse_columns(d)
    btr = reverse_columns(transpose(b))
    ctr = reverse_columns(transpose(c))
    dtr = reverse_columns(transpose(d))
    return [
        [a, br, cr, dr],
        [negate(br), a, negate(dtr), ctr],
        [negate(cr), dtr, a, negate(btr)],
        [negate(dr), negate(ctr), btr, a],
    ]


def add_blocks(target: Matrix, blocks: list[list[Matrix]]) -> None:
    block_size = len(blocks[0][0])
    for block_row in range(4):
        for block_column in range(4):
            block = blocks[block_row][block_column]
            row_offset = block_row * block_size
            column_offset = block_column * block_size
            for row_index, row in enumerate(block):
                target_row = target[row_offset + row_index]
                for column_index, value in enumerate(row):
                    target_row[column_offset + column_index] += value


def construct() -> Matrix:
    turyn_type = decode_turyn_type(TT36_HEX)
    validate_turyn_type(turyn_type)
    sequences = t_sequences(base_sequences(turyn_type))
    x1, x2, x3, x4 = map(circulant, sequences)

    zero = [[0] * ORDER for _ in range(ORDER)]
    inputs = (
        (x1, x2, x3, x4),
        (x2, negate(x1), x4, negate(x3)),
        (x3, negate(x4), negate(x1), x2),
        (x4, x3, negate(x2), negate(x1)),
    )
    for matrices in inputs:
        add_blocks(zero, goethals_seidel_blocks(*matrices))

    bad_entry = next(
        (
            (row_index, column_index, value)
            for row_index, row in enumerate(zero)
            for column_index, value in enumerate(row)
            if value not in {-1, 1}
        ),
        None,
    )
    if bad_entry is not None:
        raise ValueError(f"construction produced a non-binary entry: {bad_entry}")
    return zero


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    matrix = construct()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="ascii", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(matrix)

    result = {
        "status": "generated",
        "order": ORDER,
        "candidate": str(args.output),
        "candidate_sha256": sha256_file(args.output),
        "generator_sha256": sha256_file(Path(__file__).resolve()),
        "construction": "TT(36)->BS(71,36)->T(107)->Cooper-Wallis/W(1)",
        "source": {
            "primary_doi": PRIMARY_DOI,
            "sage_commit": SAGE_COMMIT,
            "turyn_type_hex": TT36_HEX,
        },
        "internal_checks": [
            "weighted Turyn-type nonperiodic autocorrelation",
            "base-sequence nonperiodic autocorrelation",
            "T-sequence disjoint support",
            "T-sequence periodic autocorrelation",
            "constructed entries are exactly plus or minus one",
        ],
        "verification_boundary": (
            "generation checks are not independent Hadamard verification"
        ),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
