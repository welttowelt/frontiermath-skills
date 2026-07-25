#!/usr/bin/env python3
"""Exact public-contract shadow verifier for Arithmetic Kakeya certificates."""

from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import platform
import re
import time
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence


CHECKER_VERSION = "0.2.0"
CONTRACT_SCHEMA = "frontiermath-shadow-contract-v1"
MANIFEST_SCHEMA = "frontiermath-contract-manifest-v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_CONTRACT_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CANDIDATE_BYTES = 8 * 1024 * 1024
MAX_VERTICES = 1024
MAX_GENERATORS = 8192

Pair = tuple[int, int]
Vertex = tuple[int, ...]


class Candidate:
    def __init__(
        self,
        *,
        claimed_header: str,
        x_set: tuple[Pair, ...],
        dimensions: tuple[int, ...],
        graph_functions: tuple[dict[Vertex, Pair], ...],
        initial_known: tuple[Vertex, ...],
        singleton_rows: tuple[dict[Vertex, Pair], ...],
    ) -> None:
        self.claimed_header = claimed_header
        self.x_set = x_set
        self.dimensions = dimensions
        self.graph_functions = graph_functions
        self.initial_known = initial_known
        self.singleton_rows = singleton_rows


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise ValueError("contract SHA-256 is not registered in the bundled manifest")
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
    if contract.get("checker") != "arithmetic-kakeya":
        raise ValueError("contract checker must be 'arithmetic-kakeya'")
    if contract.get("problem_id") != "arithmetic-kakeya":
        raise ValueError("contract problem_id must be 'arithmetic-kakeya'")
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
    numerator = target.get("score_numerator")
    denominator = target.get("score_denominator")
    if (
        not isinstance(numerator, int)
        or isinstance(numerator, bool)
        or numerator <= 0
    ):
        raise ValueError("contract target.score_numerator must be positive")
    if (
        not isinstance(denominator, int)
        or isinstance(denominator, bool)
        or denominator <= 0
    ):
        raise ValueError("contract target.score_denominator must be positive")
    if Fraction(numerator, denominator) >= 2:
        raise ValueError("contract target score must be below the trivial bound 2")

    contract_id, manifest_hash = load_manifest_entry(contract, contract_hash)
    return contract, contract_hash, contract_id, manifest_hash


def literal_line(line: str, label: str) -> object:
    try:
        return ast.literal_eval(line)
    except (ValueError, SyntaxError) as exc:
        raise ValueError(f"{label} is not a Python literal: {exc}") from exc


def integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def pair(value: object, label: str) -> Pair:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must be a pair of integers")
    return integer(value[0], f"{label}[0]"), integer(value[1], f"{label}[1]")


def vertex(value: object, arity: int, label: str) -> Vertex:
    if not isinstance(value, (list, tuple)) or len(value) != arity:
        raise ValueError(f"{label} must contain exactly {arity} coordinates")
    return tuple(integer(item, f"{label}[{index}]") for index, item in enumerate(value))


def parse_candidate_bytes(raw: bytes) -> Candidate:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError(f"candidate is not UTF-8: {exc}") from exc
    lines = text.strip().splitlines()
    if len(lines) != 6:
        raise ValueError(f"candidate must contain exactly six lines, found {len(lines)}")
    if not lines[0].strip():
        raise ValueError("candidate first line must be a nonempty human-readable header")

    raw_x = literal_line(lines[1], "X")
    if not isinstance(raw_x, list):
        raise ValueError("X must be serialized as a list")
    x_values = tuple(pair(item, f"X[{index}]") for index, item in enumerate(raw_x))
    if len(set(x_values)) != len(x_values):
        raise ValueError("X contains duplicate pairs")
    if (0, 0) not in x_values:
        raise ValueError("X must contain (0, 0)")
    forbidden = next(
        (item for item in x_values if item != (0, 0) and item[0] + item[1] == 0),
        None,
    )
    if forbidden is not None:
        raise ValueError(f"X contains forbidden nonzero pair with a+b=0: {forbidden}")

    raw_dimensions = literal_line(lines[2], "dimensions")
    if not isinstance(raw_dimensions, list):
        raise ValueError("dimensions must be serialized as a list")
    dimensions = tuple(
        integer(item, f"dimensions[{index}]")
        for index, item in enumerate(raw_dimensions)
    )
    if any(item < 0 for item in dimensions):
        raise ValueError("dimensions must be non-negative")
    arity = len(dimensions)

    raw_functions = literal_line(lines[3], "graph functions")
    if not isinstance(raw_functions, list) or len(raw_functions) != arity:
        raise ValueError(
            f"graph functions must be a list of length {arity}"
        )
    functions: list[dict[Vertex, Pair]] = []
    for function_index, raw_function in enumerate(raw_functions):
        if not isinstance(raw_function, dict):
            raise ValueError(f"f_{function_index + 1} must be a dictionary")
        normalized: dict[Vertex, Pair] = {}
        key_arity = function_index + 1
        for raw_key, raw_value in raw_function.items():
            key = vertex(
                raw_key,
                key_arity,
                f"f_{function_index + 1} key",
            )
            value = pair(raw_value, f"f_{function_index + 1}[{key}]")
            if value not in x_values:
                raise ValueError(
                    f"f_{function_index + 1}[{key}]={value} is not in X"
                )
            for coordinate_index, coordinate in enumerate(key[:-1]):
                if not 1 <= coordinate <= dimensions[coordinate_index]:
                    raise ValueError(
                        f"f_{function_index + 1} key {key} is outside its domain"
                    )
            if not 1 <= key[-1] <= dimensions[function_index] - 1:
                raise ValueError(
                    f"f_{function_index + 1} key {key} is outside its domain"
                )
            normalized[key] = value
        functions.append(normalized)

    raw_t = literal_line(lines[4], "T")
    if not isinstance(raw_t, list):
        raise ValueError("T must be serialized as a list")
    known = tuple(vertex(item, arity, f"T[{index}]") for index, item in enumerate(raw_t))
    if len(set(known)) != len(known):
        raise ValueError("T contains duplicate vertices")

    raw_r = literal_line(lines[5], "R")
    if not isinstance(raw_r, list):
        raise ValueError("R must be serialized as a list")
    singleton_rows: list[dict[Vertex, Pair]] = []
    for row_index, raw_row in enumerate(raw_r):
        if not isinstance(raw_row, dict):
            raise ValueError(f"R[{row_index}] must be a dictionary")
        normalized_row: dict[Vertex, Pair] = {}
        for raw_key, raw_value in raw_row.items():
            key = vertex(raw_key, arity, f"R[{row_index}] key")
            value = pair(raw_value, f"R[{row_index}][{key}]")
            if value not in x_values:
                raise ValueError(f"R[{row_index}][{key}]={value} is not in X")
            if value != (0, 0):
                normalized_row[key] = value
        if len(normalized_row) != 1:
            raise ValueError(
                f"R[{row_index}] must have exactly one nonzero support vertex"
            )
        singleton_rows.append(normalized_row)
    return Candidate(
        claimed_header=lines[0].strip(),
        x_set=x_values,
        dimensions=dimensions,
        graph_functions=tuple(functions),
        initial_known=known,
        singleton_rows=tuple(singleton_rows),
    )


def candidate_vertices(dimensions: Sequence[int]) -> tuple[Vertex, ...]:
    if not dimensions:
        return ((),)
    return tuple(
        itertools.product(*(range(1, dimension + 1) for dimension in dimensions))
    )


def graph_edges(candidate: Candidate) -> tuple[tuple[Vertex, Vertex, Pair], ...]:
    edges: list[tuple[Vertex, Vertex, Pair]] = []
    dimensions = candidate.dimensions
    for axis, function in enumerate(candidate.graph_functions):
        tail_ranges = [
            range(1, dimension + 1)
            for dimension in dimensions[axis + 1 :]
        ]
        tails: Iterable[tuple[int, ...]]
        tails = itertools.product(*tail_ranges) if tail_ranges else [()]
        cached_tails = tuple(tails)
        for prefix, label in function.items():
            if label == (0, 0):
                continue
            for tail in cached_tails:
                left = prefix + tail
                right = prefix[:-1] + (prefix[-1] + 1,) + tail
                edges.append((left, right, label))
    return tuple(edges)


def dense_row(
    values: dict[Vertex, Pair],
    vertex_index: dict[Vertex, int],
    width: int,
) -> list[int]:
    row = [0] * width
    for where, value in values.items():
        offset = 2 * vertex_index[where]
        row[offset], row[offset + 1] = value
    return row


def generator_rows(
    candidate: Candidate,
    vertices: Sequence[Vertex],
    edges: Sequence[tuple[Vertex, Vertex, Pair]],
) -> tuple[list[int], ...]:
    index = {item: position for position, item in enumerate(vertices)}
    rows = [
        dense_row(row, index, 2 * len(vertices))
        for row in candidate.singleton_rows
    ]
    for left, right, label in edges:
        rows.append(
            dense_row(
                {
                    left: label,
                    right: (-label[0], -label[1]),
                },
                index,
                2 * len(vertices),
            )
        )
    return tuple(rows)


def rref_rows(rows: Sequence[Sequence[int]]) -> tuple[list[list[Fraction]], list[int]]:
    matrix = [
        [Fraction(value) for value in row]
        for row in rows
        if any(value != 0 for value in row)
    ]
    if not matrix:
        return [], []
    width = len(matrix[0])
    pivot_row = 0
    pivots: list[int] = []
    for column in range(width):
        selected = next(
            (
                row_index
                for row_index in range(pivot_row, len(matrix))
                if matrix[row_index][column] != 0
            ),
            None,
        )
        if selected is None:
            continue
        matrix[pivot_row], matrix[selected] = matrix[selected], matrix[pivot_row]
        pivot = matrix[pivot_row][column]
        matrix[pivot_row] = [value / pivot for value in matrix[pivot_row]]
        for row_index, row in enumerate(matrix):
            if row_index == pivot_row or row[column] == 0:
                continue
            factor = row[column]
            matrix[row_index] = [
                value - factor * basis_value
                for value, basis_value in zip(row, matrix[pivot_row])
            ]
        pivots.append(column)
        pivot_row += 1
        if pivot_row == len(matrix):
            break
    return matrix[:pivot_row], pivots


def in_row_span(
    target: Sequence[int],
    basis: Sequence[Sequence[Fraction]],
    pivots: Sequence[int],
) -> bool:
    residual = [Fraction(value) for value in target]
    for row, pivot in zip(basis, pivots):
        if residual[pivot] == 0:
            continue
        factor = residual[pivot]
        residual = [
            value - factor * basis_value
            for value, basis_value in zip(residual, row)
        ]
    return all(value == 0 for value in residual)


def forcing_closure(
    vertices: Sequence[Vertex],
    rows: Sequence[Sequence[int]],
    initial_known: Sequence[Vertex],
) -> tuple[set[Vertex], list[list[Vertex]]]:
    known = set(initial_known)
    rounds: list[list[Vertex]] = []
    while len(known) < len(vertices):
        unknown = [item for item in vertices if item not in known]
        columns = [
            coordinate
            for item in unknown
            for coordinate in (2 * vertices.index(item), 2 * vertices.index(item) + 1)
        ]
        restricted_rows = [[row[column] for column in columns] for row in rows]
        basis, pivots = rref_rows(restricted_rows)
        forceable: list[Vertex] = []
        for unknown_index, item in enumerate(unknown):
            target = [0] * (2 * len(unknown))
            target[2 * unknown_index] = 1
            target[2 * unknown_index + 1] = -1
            if in_row_span(target, basis, pivots):
                forceable.append(item)
        if not forceable:
            break
        known.update(forceable)
        rounds.append(forceable)
    return known, rounds


def verify(
    candidate: Candidate,
    target_score: Fraction,
) -> dict[str, object]:
    vertices = candidate_vertices(candidate.dimensions)
    if not vertices:
        raise ValueError("graph has no vertices, so its score is undefined")
    if len(vertices) > MAX_VERTICES:
        raise ValueError(f"graph exceeds supported ceiling of {MAX_VERTICES} vertices")
    vertex_set = set(vertices)
    bad_t = next((item for item in candidate.initial_known if item not in vertex_set), None)
    if bad_t is not None:
        raise ValueError(f"T contains vertex outside the graph: {bad_t}")
    bad_r = next(
        (
            item
            for row in candidate.singleton_rows
            for item in row
            if item not in vertex_set
        ),
        None,
    )
    if bad_r is not None:
        raise ValueError(f"R contains vertex outside the graph: {bad_r}")

    edges = graph_edges(candidate)
    rows = generator_rows(candidate, vertices, edges)
    if len(rows) > MAX_GENERATORS:
        raise ValueError(
            f"graph and R exceed supported ceiling of {MAX_GENERATORS} generators"
        )
    denominator = len(vertices) - len(candidate.initial_known)
    if denominator <= 0:
        raise ValueError("score denominator n-|T| must be positive")
    score = Fraction(len(edges) + len(candidate.singleton_rows), denominator)
    known, rounds = forcing_closure(
        vertices,
        rows,
        candidate.initial_known,
    )
    common = {
        "claimed_header": candidate.claimed_header,
        "score": f"{score.numerator}/{score.denominator}",
        "target_score": f"{target_score.numerator}/{target_score.denominator}",
        "parameters": {
            "m": len(edges),
            "r": len(candidate.singleton_rows),
            "n": len(vertices),
            "t": len(candidate.initial_known),
        },
        "forcing_rounds": [
            [list(item) for item in round_items]
            for round_items in rounds
        ],
        "checked_predicates": [
            "six-line-public-serialization",
            "X-domain-and-excluded-output-slope",
            "constructible-product-graph-domains",
            "same-tail-edge-expansion",
            "singleton-support-R",
            "exact-m-and-score",
            "forcing-closure-by-rational-row-span",
            "score-threshold",
        ],
        "unchecked_predicates": [
            "Epoch-private-verifier-parser-equivalence",
            "novelty-and-prior-art",
            "publication-acceptance",
        ],
        "epoch_verifier_equivalence": False,
    }
    if len(known) != len(vertices):
        common.update(
            {
                "status": "shadow-verifier-reject",
                "failure": "forcing-closure-stuck",
                "unforced_vertices": [
                    list(item) for item in vertices if item not in known
                ],
            }
        )
        return common
    if score > target_score:
        common.update(
            {
                "status": "shadow-verifier-reject",
                "failure": "score-above-contract-threshold",
            }
        )
        return common
    common["status"] = "shadow-verifier-pass"
    return common


def fixture_record(name: str, passed: bool, artifact: bytes) -> dict[str, object]:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "artifact_sha256": bytes_sha256(artifact),
    }


def run_fixtures() -> list[dict[str, object]]:
    fixture_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    warmup_path = fixture_dir / "arithmetic-kakeya-katz-tao-7-over-4.txt"
    warmup_raw = warmup_path.read_bytes()
    warmup = parse_candidate_bytes(warmup_raw)
    warmup_result = verify(warmup, Fraction(7, 4))

    broken_raw = warmup_raw.rsplit(b", {(1, 2): (0, 1)}", 1)[0] + b"]\n"
    try:
        broken = parse_candidate_bytes(broken_raw)
        broken_result = verify(broken, Fraction(7, 4))
        broken_rejected = broken_result["status"] == "shadow-verifier-reject"
    except ValueError:
        broken_rejected = True

    forbidden_raw = warmup_raw.replace(b"(1, 2)]", b"(1, 2), (1, -1)]", 1)
    try:
        parse_candidate_bytes(forbidden_raw)
    except ValueError:
        forbidden_rejected = True
    else:
        forbidden_rejected = False

    return [
        fixture_record(
            "katz-tao-four-vertex-seven-over-four",
            warmup_result["status"] == "shadow-verifier-pass"
            and warmup_result["score"] == "7/4",
            warmup_raw,
        ),
        fixture_record(
            "removed-singleton-row-rejected",
            broken_rejected,
            broken_raw,
        ),
        fixture_record(
            "forbidden-output-slope-in-X-rejected",
            forbidden_rejected,
            forbidden_raw,
        ),
        fixture_record(
            "same-tail-edge-count",
            len(
                graph_edges(
                    Candidate(
                        claimed_header="fixture",
                        x_set=((0, 0), (1, 0)),
                        dimensions=(2, 3),
                        graph_functions=({(1,): (1, 0)}, {}),
                        initial_known=(),
                        singleton_rows=(),
                    )
                )
            )
            == 3,
            b"d=[2,3], f1(1)=(1,0)",
        ),
        fixture_record(
            "rational-span-clearing-denominators",
            in_row_span([1, -1], *rref_rows([[2, -2]])),
            b"span_Q{(2,-2)} contains (1,-1)",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
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
        contract, contract_hash, contract_id, manifest_hash = load_contract(args.contract)
        candidate_bytes = read_bytes_limited(
            args.candidate,
            MAX_CANDIDATE_BYTES,
            "candidate",
        )
        candidate_hash = bytes_sha256(candidate_bytes)
        candidate = parse_candidate_bytes(candidate_bytes)
        target = contract["target"]
        assert isinstance(target, dict)
        target_score = Fraction(
            int(target["score_numerator"]),
            int(target["score_denominator"]),
        )
        result = verify(candidate, target_score)
    except (OSError, ValueError) as exc:
        result = {"status": "input-error", "error": str(exc)}
    if any(fixture["status"] != "pass" for fixture in fixtures):
        result = {
            "status": "checker-self-test-failed",
            "candidate_result": result,
        }
    result.setdefault("checked_predicates", [])
    result.setdefault(
        "unchecked_predicates",
        [
            "Epoch-private-verifier-parser-equivalence",
            "novelty-and-prior-art",
            "publication-acceptance",
        ],
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
        "name": "verify_arithmetic_kakeya",
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
