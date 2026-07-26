#!/usr/bin/env python3
"""Independently verify a Hadamard CSV with an exact NumPy integer Gram product."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_exact_csv(path: Path, order: int) -> np.ndarray:
    rows: list[list[int]] = []
    with path.open(newline="", encoding="ascii") as handle:
        for row_number, raw_row in enumerate(csv.reader(handle), start=1):
            if len(raw_row) != order:
                raise ValueError(
                    f"row {row_number} has {len(raw_row)} entries; "
                    f"expected {order}"
                )
            row: list[int] = []
            for column_number, raw_value in enumerate(raw_row, start=1):
                value = raw_value.strip()
                if value not in {"-1", "1"}:
                    raise ValueError(
                        f"entry ({row_number},{column_number}) is "
                        f"{raw_value!r}; expected -1 or 1"
                    )
                row.append(int(value))
            rows.append(row)
    if len(rows) != order:
        raise ValueError(f"found {len(rows)} rows; expected {order}")
    return np.asarray(rows, dtype=np.int64)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix_csv", type=Path)
    parser.add_argument("--order", required=True, type=int)
    args = parser.parse_args()

    started = time.perf_counter()
    try:
        matrix = load_exact_csv(args.matrix_csv, args.order)
        gram = matrix @ matrix.T
        delta = gram - args.order * np.eye(args.order, dtype=np.int64)
        failing = np.argwhere(delta != 0)
        first_failure = None
        if failing.size:
            row, column = map(int, failing[0])
            first_failure = {
                "row_zero_indexed": row,
                "column_zero_indexed": column,
                "gram_value": int(gram[row, column]),
                "expected": args.order if row == column else 0,
            }
        result = {
            "status": "pass" if first_failure is None else "fail",
            "order": args.order,
            "candidate_sha256": sha256_file(args.matrix_csv),
            "checker_sha256": sha256_file(Path(__file__).resolve()),
            "arithmetic": "NumPy int64 matrix multiplication",
            "max_abs_gram_error": int(np.abs(delta).max()),
            "first_failure": first_failure,
            "runtime_seconds": time.perf_counter() - started,
            "environment": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "machine": platform.machine(),
            },
        }
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        result = {
            "status": "error",
            "error": str(error),
            "runtime_seconds": time.perf_counter() - started,
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
