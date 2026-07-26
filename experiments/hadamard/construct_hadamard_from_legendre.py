#!/usr/bin/env python3
"""Construct H(2L+2) from a serialized binary Legendre pair."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


Matrix = list[list[int]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def circulant(sequence: list[int]) -> Matrix:
    size = len(sequence)
    return [
        [sequence[(column - row) % size] for column in range(size)]
        for row in range(size)
    ]


def transpose(matrix: Matrix) -> Matrix:
    return [list(column) for column in zip(*matrix)]


def negate(matrix: Matrix) -> Matrix:
    return [[-value for value in row] for row in matrix]


def construct(a: list[int], b: list[int]) -> Matrix:
    length = len(a)
    ca = circulant(a)
    cb = circulant(b)
    cat = transpose(ca)
    ncbt = negate(transpose(cb))
    ones = [1] * length

    matrix = [
        [-1, -1] + ones + ones,
        [-1, 1] + ones + [-1] * length,
    ]
    for row in range(length):
        matrix.append([1, 1] + cb[row] + ca[row])
    for row in range(length):
        matrix.append([1, -1] + cat[row] + ncbt[row])
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legendre_pair", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--metadata-output", type=Path)
    args = parser.parse_args()

    document = json.loads(args.legendre_pair.read_text(encoding="utf-8"))
    a = document["a_sequence"]
    b = document["b_sequence"]
    if len(a) != len(b) or any(
        type(value) is not int or value not in {-1, 1} for value in a + b
    ):
        raise ValueError("invalid serialized binary sequences")
    matrix = construct(a, b)
    order = 2 * len(a) + 2
    if len(matrix) != order or any(len(row) != order for row in matrix):
        raise ValueError("construction emitted the wrong shape")
    if any(value not in {-1, 1} for row in matrix for value in row):
        raise ValueError("construction emitted a non-binary entry")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="ascii", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(matrix)
    result = {
        "status": "generated",
        "order": order,
        "candidate": str(args.output),
        "candidate_sha256": sha256_file(args.output),
        "legendre_pair_sha256": sha256_file(args.legendre_pair),
        "generator_sha256": sha256_file(Path(__file__).resolve()),
        "construction": "two-circulant-core Legendre-pair construction",
        "verification_boundary": (
            "shape and entry checks only; exact Gram verification is separate"
        ),
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.metadata_output is not None:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
