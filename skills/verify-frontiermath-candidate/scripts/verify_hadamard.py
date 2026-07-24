#!/usr/bin/env python3
"""Exact public-contract shadow verifier for a Hadamard CSV matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import platform
import re
import time
from pathlib import Path


CHECKER_VERSION = "0.4.0"
CONTRACT_SCHEMA = "frontiermath-shadow-contract-v1"
MANIFEST_SCHEMA = "frontiermath-contract-manifest-v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_CONTRACT_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CANDIDATE_BYTES = 8 * 1024 * 1024
MAX_HADAMARD_ORDER = 2048


def popcount(value: int) -> int:
    native = getattr(value, "bit_count", None)
    return native() if native is not None else bin(value).count("1")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_bytes_limited(path: Path, limit: int, label: str) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{label} exceeds {limit} bytes")
    return raw


def load_manifest_entry(
    contract: dict[str, object],
    contract_hash: str,
) -> tuple[str, str]:
    manifest_path = Path(__file__).resolve().parents[1] / "contracts" / "manifest.json"
    raw = read_bytes_limited(manifest_path, MAX_MANIFEST_BYTES, "contract manifest")
    try:
        manifest = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid bundled contract manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"bundled manifest schema must be {MANIFEST_SCHEMA!r}")
    entries = manifest.get("contracts")
    if not isinstance(entries, dict):
        raise ValueError("bundled manifest contracts must be an object")
    entry = entries.get(contract_hash)
    if not isinstance(entry, dict):
        raise ValueError(
            "contract SHA-256 is not registered in the bundled manifest"
        )
    contract_id = entry.get("id")
    if not isinstance(contract_id, str) or not contract_id:
        raise ValueError("bundled manifest entry id must be a nonempty string")
    expected = {
        "checker": contract.get("checker"),
        "problem_id": contract.get("problem_id"),
        "prompt_type": contract.get("prompt_type"),
        "source": contract.get("source"),
        "target": contract.get("target"),
    }
    observed = {key: entry.get(key) for key in expected}
    if observed != expected:
        raise ValueError("bundled manifest entry does not match contract content")
    return contract_id, bytes_sha256(raw)


def load_contract(
    path: Path,
) -> tuple[dict[str, object], str, str, str]:
    raw = read_bytes_limited(path, MAX_CONTRACT_BYTES, "contract")
    contract_hash = bytes_sha256(raw)
    try:
        contract = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid contract JSON: {exc}") from exc
    if not isinstance(contract, dict):
        raise ValueError("contract must be a JSON object")
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise ValueError(f"contract schema must be {CONTRACT_SCHEMA!r}")
    if contract.get("checker") != "hadamard":
        raise ValueError("contract checker must be 'hadamard'")
    if contract.get("problem_id") != "hadamard":
        raise ValueError("contract problem_id must be 'hadamard'")
    if not isinstance(contract.get("prompt_type"), str) or not contract["prompt_type"]:
        raise ValueError("contract prompt_type must be a nonempty string")

    source = contract.get("source")
    if not isinstance(source, dict):
        raise ValueError("contract source must be an object")
    for field in ("url", "retrieved"):
        if not isinstance(source.get(field), str) or not source[field]:
            raise ValueError(f"contract source.{field} must be a nonempty string")
    for field in ("artifact_sha256", "prompt_sha256"):
        value = source.get(field)
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            raise ValueError(f"contract source.{field} must be lowercase SHA-256")

    target = contract.get("target")
    if not isinstance(target, dict):
        raise ValueError("contract target must be an object")
    order = target.get("order")
    if not isinstance(order, int) or isinstance(order, bool) or order < 1:
        raise ValueError("contract target.order must be a positive integer")
    if order > MAX_HADAMARD_ORDER:
        raise ValueError(
            f"contract target.order exceeds supported ceiling {MAX_HADAMARD_ORDER}"
        )
    contract_id, manifest_hash = load_manifest_entry(contract, contract_hash)
    return contract, contract_hash, contract_id, manifest_hash


def parse_matrix_bytes(raw: bytes) -> list[list[int]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError(f"candidate is not UTF-8 CSV: {exc}") from exc
    matrix: list[list[int]] = []
    handle = io.StringIO(text, newline="")
    for row_number, raw_row in enumerate(csv.reader(handle), start=1):
        if not raw_row or all(not cell.strip() for cell in raw_row):
            raise ValueError(f"blank row at line {row_number}")
        row: list[int] = []
        for column_number, cell in enumerate(raw_row, start=1):
            value = cell.strip()
            if value not in {"-1", "1", "+1"}:
                raise ValueError(
                    f"entry ({row_number},{column_number}) is not -1 or +1: {value!r}"
                )
            row.append(int(value))
        matrix.append(row)
    if not matrix:
        raise ValueError("matrix is empty")
    return matrix


def parse_matrix(path: Path) -> list[list[int]]:
    return parse_matrix_bytes(
        read_bytes_limited(path, MAX_CANDIDATE_BYTES, "candidate")
    )


def verify(matrix: list[list[int]], expected_order: int | None = None) -> dict[str, object]:
    order = len(matrix)
    if order < 1:
        raise ValueError("matrix is empty")
    if expected_order is not None and expected_order < 1:
        raise ValueError("expected order must be positive")
    if expected_order is not None and order != expected_order:
        return {
            "status": "shadow-verifier-reject",
            "failure": "wrong-row-count",
            "expected_order": expected_order,
            "actual_rows": order,
            "checked_predicates": ["row-count"],
        }
    bad_width = next(
        ((index, len(row)) for index, row in enumerate(matrix) if len(row) != order),
        None,
    )
    if bad_width is not None:
        row, width = bad_width
        return {
            "status": "shadow-verifier-reject",
            "failure": "non-square",
            "order": order,
            "row": row,
            "row_width": width,
            "checked_predicates": ["row-count", "square-shape"],
        }
    bad_entry = next(
        (
            (row_index, column_index, value)
            for row_index, row in enumerate(matrix)
            for column_index, value in enumerate(row)
            if value not in {-1, 1}
        ),
        None,
    )
    if bad_entry is not None:
        row, column, value = bad_entry
        return {
            "status": "shadow-verifier-reject",
            "failure": "entry-outside-plus-minus-one",
            "order": order,
            "entry_zero_indexed": [row, column],
            "value": value,
            "checked_predicates": [
                "row-count",
                "square-shape",
                "plus-minus-one-entries",
            ],
        }
    if order > 1 and order % 2:
        return {
            "status": "shadow-verifier-reject",
            "failure": "odd-order-cannot-have-orthogonal-distinct-plus-minus-one-rows",
            "order": order,
            "checked_predicates": [
                "row-count",
                "square-shape",
                "plus-minus-one-entries",
                "row-orthogonality",
            ],
        }

    bit_rows = [
        sum((1 << column) for column, value in enumerate(row) if value == 1)
        for row in matrix
    ]
    required_distance = order // 2
    for left in range(order):
        for right in range(left + 1, order):
            distance = popcount(bit_rows[left] ^ bit_rows[right])
            if distance != required_distance:
                dot_product = order - 2 * distance
                return {
                    "status": "shadow-verifier-reject",
                    "failure": "non-orthogonal-row-pair",
                    "order": order,
                    "rows_zero_indexed": [left, right],
                    "hamming_distance": distance,
                    "required_hamming_distance": required_distance,
                    "dot_product": dot_product,
                    "checked_predicates": [
                        "row-count",
                        "square-shape",
                        "plus-minus-one-entries",
                        "row-orthogonality",
                    ],
                }
    return {
        "status": "shadow-verifier-pass",
        "order": order,
        "checked_predicates": [
            "row-count",
            "square-shape",
            "plus-minus-one-entries",
            "row-orthogonality",
        ],
        "unchecked_predicates": [
            "novelty-of-construction",
            "Epoch-private-verifier-predicates",
        ],
        "epoch_verifier_equivalence": False,
    }


def fixture_record(
    name: str,
    passed: bool,
    artifact: bytes,
) -> dict[str, object]:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "artifact_sha256": bytes_sha256(artifact),
    }


def run_fixtures() -> list[dict[str, object]]:
    fixture_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    valid_path = fixture_dir / "hadamard-order-4.csv"
    equivalent_path = fixture_dir / "hadamard-order-4-plus.csv"
    malformed_path = fixture_dir / "hadamard-malformed.csv"
    valid_order_four = [
        [1, 1, 1, 1],
        [1, -1, 1, -1],
        [1, 1, -1, -1],
        [1, -1, -1, 1],
    ]
    local_defect = [row[:] for row in valid_order_four]
    local_defect[-1][-1] = -1
    fixtures = [
        fixture_record(
            "known-valid-order-four",
            verify(valid_order_four, 4)["status"] == "shadow-verifier-pass",
            valid_path.read_bytes(),
        ),
        fixture_record(
            "boundary-order-one",
            verify([[1]], 1)["status"] == "shadow-verifier-pass",
            b"[[1]]",
        ),
        fixture_record(
            "local-mathematical-defect",
            verify(local_defect, 4).get("failure") == "non-orthogonal-row-pair",
            json.dumps(local_defect, separators=(",", ":")).encode(),
        ),
        fixture_record(
            "non-square-shape",
            verify([[1, 1], [1]], 2).get("failure") == "non-square",
            b"[[1,1],[1]]",
        ),
        fixture_record(
            "entry-domain",
            verify([[1, 0], [1, -1]], 2).get("failure")
            == "entry-outside-plus-minus-one",
            malformed_path.read_bytes(),
        ),
    ]
    parsed_valid = parse_matrix(valid_path)
    parsed_equivalent = parse_matrix(equivalent_path)
    fixtures.append(
        fixture_record(
            "equivalent-plus-one-serialization",
            parsed_valid == parsed_equivalent
            and verify(parsed_equivalent, 4)["status"] == "shadow-verifier-pass",
            equivalent_path.read_bytes(),
        )
    )
    try:
        parse_matrix(malformed_path)
    except ValueError:
        malformed_rejected = True
    else:
        malformed_rejected = False
    fixtures.append(
        fixture_record(
            "malformed-csv-rejected",
            malformed_rejected,
            malformed_path.read_bytes(),
        )
    )
    return fixtures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix_csv", type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    checker_path = Path(__file__).resolve()
    fixtures = run_fixtures()
    candidate_hash: str | None = None
    contract: dict[str, object] | None = None
    contract_hash: str | None = None
    contract_id: str | None = None
    manifest_hash: str | None = None
    try:
        contract_hash = bytes_sha256(
            read_bytes_limited(args.contract, MAX_CONTRACT_BYTES, "contract")
        )
        contract, contract_hash, contract_id, manifest_hash = load_contract(
            args.contract
        )
        candidate_bytes = read_bytes_limited(
            args.matrix_csv, MAX_CANDIDATE_BYTES, "candidate"
        )
        candidate_hash = bytes_sha256(candidate_bytes)
        matrix = parse_matrix_bytes(candidate_bytes)
        target = contract["target"]
        assert isinstance(target, dict)
        result = verify(matrix, int(target["order"]))
    except (OSError, ValueError, csv.Error) as exc:
        result = {"status": "input-error", "error": str(exc)}
    if any(fixture["status"] != "pass" for fixture in fixtures):
        result = {
            "status": "checker-self-test-failed",
            "candidate_result": result,
        }
    result.setdefault("checked_predicates", [])
    result.setdefault(
        "unchecked_predicates",
        ["novelty-of-construction", "Epoch-private-verifier-predicates"],
    )
    result["prompt_snapshot"] = (
        {
            "contract_id": contract_id,
            "contract_sha256": contract_hash,
            "contract_registry": {
                "status": "bundled-manifest-match",
                "manifest_sha256": manifest_hash,
            },
            "problem_id": contract["problem_id"],
            "prompt_type": contract["prompt_type"],
            "source": contract["source"],
            "target": contract["target"],
        }
        if contract is not None
        else {
            "contract_id": None,
            "contract_sha256": contract_hash,
            "contract_registry": {
                "status": "unregistered-or-invalid",
                "manifest_sha256": None,
            },
        }
    )
    result["checker"] = {
        "name": "verify_hadamard",
        "version": CHECKER_VERSION,
        "sha256": file_sha256(checker_path),
    }
    result["candidate_sha256"] = candidate_hash
    result["fixtures"] = fixtures
    result["fixtures_sha256"] = bytes_sha256(
        json.dumps(fixtures, sort_keys=True, separators=(",", ":")).encode()
    )
    result["fixture_suite_status"] = (
        "pass" if all(fixture["status"] == "pass" for fixture in fixtures) else "fail"
    )
    environment = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }
    result["environment"] = environment
    result["environment_sha256"] = bytes_sha256(
        json.dumps(environment, sort_keys=True, separators=(",", ":")).encode()
    )
    result["runtime_seconds"] = round(time.perf_counter() - started, 6)
    result["claim_status"] = result["status"]
    result["epoch_verifier_equivalence"] = False
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] == "shadow-verifier-pass":
        return 0
    if result["status"] == "input-error":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
