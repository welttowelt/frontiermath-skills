#!/usr/bin/env python3
"""Exact shadow verifier for the public Ramsey book-graph contract."""

from __future__ import annotations

import argparse
import hashlib
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
MAX_CANDIDATE_BYTES = 2 * 1024 * 1024
MAX_RAMSEY_N = 256


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
    if contract.get("checker") != "ramsey-book":
        raise ValueError("contract checker must be 'ramsey-book'")
    if contract.get("problem_id") != "ramsey-book-graphs":
        raise ValueError("contract problem_id must be 'ramsey-book-graphs'")
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
    n = target.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n < 2:
        raise ValueError("contract target.n must be an integer of at least 2")
    if n > MAX_RAMSEY_N:
        raise ValueError(f"contract target.n exceeds supported ceiling {MAX_RAMSEY_N}")
    contract_id, manifest_hash = load_manifest_entry(contract, contract_hash)
    return contract, contract_hash, contract_id, manifest_hash


def normalized_bits(text: str) -> str:
    bits = text.strip()
    if any(character.isspace() for character in bits):
        raise ValueError("adjacency string contains internal whitespace")
    invalid = sorted(set(bits) - {"0", "1"})
    if invalid:
        raise ValueError(f"adjacency string contains non-binary characters: {invalid}")
    return bits


def decode_adjacency(bits: str, vertex_count: int) -> list[int]:
    expected = vertex_count * (vertex_count - 1) // 2
    if len(bits) != expected:
        raise ValueError(
            f"wrong adjacency length: expected {expected}, found {len(bits)}"
        )
    adjacency = [0] * vertex_count
    cursor = 0
    for right in range(1, vertex_count):
        for left in range(right):
            if bits[cursor] == "1":
                adjacency[left] |= 1 << right
                adjacency[right] |= 1 << left
            cursor += 1
    return adjacency


def edge_set(adjacency: list[int]) -> set[tuple[int, int]]:
    return {
        (left, right)
        for right in range(1, len(adjacency))
        for left in range(right)
        if (adjacency[left] >> right) & 1
    }


def verify(bits: str, n: int) -> dict[str, object]:
    if n < 2:
        raise ValueError("n must be at least 2")
    vertex_count = 4 * n - 2
    adjacency = decode_adjacency(bits, vertex_count)
    full_mask = (1 << vertex_count) - 1

    max_graph_pages = -1
    max_graph_pair: tuple[int, int] | None = None
    max_complement_pages = -1
    max_complement_pair: tuple[int, int] | None = None

    for right in range(1, vertex_count):
        for left in range(right):
            if (adjacency[left] >> right) & 1:
                pages = popcount(adjacency[left] & adjacency[right])
                if pages > max_graph_pages:
                    max_graph_pages = pages
                    max_graph_pair = (left, right)
                if pages >= n - 1:
                    return {
                        "status": "shadow-verifier-reject",
                        "failure": "graph-contains-forbidden-book",
                        "n": n,
                        "vertex_count": vertex_count,
                        "spine_edge": [left, right],
                        "pages": pages,
                        "forbidden_pages": n - 1,
                        "checked_predicates": [
                            "column-major-adjacency-shape",
                            "forbidden-B_(n-1)-witness-in-graph",
                        ],
                    }
            else:
                endpoints = (1 << left) | (1 << right)
                common_non_neighbors = (
                    full_mask & ~endpoints & ~adjacency[left] & ~adjacency[right]
                )
                pages = popcount(common_non_neighbors)
                if pages > max_complement_pages:
                    max_complement_pages = pages
                    max_complement_pair = (left, right)
                if pages >= n:
                    return {
                        "status": "shadow-verifier-reject",
                        "failure": "complement-contains-forbidden-book",
                        "n": n,
                        "vertex_count": vertex_count,
                        "spine_edge_in_complement": [left, right],
                        "pages": pages,
                        "forbidden_pages": n,
                        "checked_predicates": [
                            "column-major-adjacency-shape",
                            "forbidden-B_n-witness-in-complement",
                        ],
                    }

    return {
        "status": "shadow-verifier-pass",
        "n": n,
        "vertex_count": vertex_count,
        "max_graph_book_pages": max_graph_pages,
        "max_graph_book_spine": list(max_graph_pair) if max_graph_pair else None,
        "max_complement_book_pages": max_complement_pages,
        "max_complement_book_spine": (
            list(max_complement_pair) if max_complement_pair else None
        ),
        "checked_predicates": [
            "column-major-adjacency-shape",
            "no-B_(n-1)-in-graph",
            "no-B_n-in-complement",
        ],
        "unchecked_predicates": [
            "algorithm-valid-for-all-required-n",
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
    valid_n_two = "000011101011000"
    vertex_count = 6
    edge_count = vertex_count * (vertex_count - 1) // 2
    fixtures = [
        fixture_record(
            "known-valid-n-two",
            verify(valid_n_two, 2)["status"] == "shadow-verifier-pass",
            valid_n_two.encode(),
        ),
        fixture_record(
            "complete-graph-defect",
            verify("1" * edge_count, 2).get("failure")
            == "graph-contains-forbidden-book",
            ("1" * edge_count).encode(),
        ),
        fixture_record(
            "empty-graph-defect",
            verify("0" * edge_count, 2).get("failure")
            == "complement-contains-forbidden-book",
            ("0" * edge_count).encode(),
        ),
        fixture_record(
            "column-major-decoding",
            edge_set(decode_adjacency("011010", 4))
            == {(0, 2), (1, 2), (1, 3)},
            b"011010",
        ),
    ]
    try:
        normalized_bits("010 101")
    except ValueError:
        fixtures.append(
            fixture_record("internal-whitespace-rejected", True, b"010 101")
        )
    else:
        fixtures.append(
            fixture_record("internal-whitespace-rejected", False, b"010 101")
        )
    try:
        decode_adjacency("0", 4)
    except ValueError:
        fixtures.append(fixture_record("wrong-length-rejected", True, b"0"))
    else:
        fixtures.append(fixture_record("wrong-length-rejected", False, b"0"))
    return fixtures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--adjacency-file", type=Path)
    source.add_argument("--adjacency-string")
    args = parser.parse_args()
    started = time.perf_counter()
    checker_path = Path(__file__).resolve()
    fixtures = run_fixtures()
    candidate_hash: str | None = None
    normalized_hash: str | None = None
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
        if args.adjacency_file:
            raw_bytes = read_bytes_limited(
                args.adjacency_file, MAX_CANDIDATE_BYTES, "candidate"
            )
            raw = raw_bytes.decode("utf-8")
        else:
            assert args.adjacency_string is not None
            raw = args.adjacency_string
            raw_bytes = raw.encode("utf-8")
            if len(raw_bytes) > MAX_CANDIDATE_BYTES:
                raise ValueError(
                    f"candidate exceeds {MAX_CANDIDATE_BYTES} bytes"
                )
        assert raw is not None
        candidate_hash = hashlib.sha256(raw_bytes).hexdigest()
        bits = normalized_bits(raw)
        normalized_hash = hashlib.sha256(bits.encode()).hexdigest()
        target = contract["target"]
        assert isinstance(target, dict)
        result = verify(bits, int(target["n"]))
    except (OSError, UnicodeError, ValueError) as exc:
        result = {"status": "input-error", "error": str(exc)}
    if any(fixture["status"] != "pass" for fixture in fixtures):
        result = {
            "status": "checker-self-test-failed",
            "candidate_result": result,
        }
    result.setdefault("checked_predicates", [])
    result.setdefault(
        "unchecked_predicates",
        ["algorithm-valid-for-all-required-n", "Epoch-private-verifier-predicates"],
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
        "name": "verify_ramsey_book",
        "version": CHECKER_VERSION,
        "sha256": file_sha256(checker_path),
    }
    result["candidate_sha256"] = candidate_hash
    result["normalized_candidate_sha256"] = normalized_hash
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
