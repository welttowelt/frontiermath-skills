from __future__ import annotations

import importlib.util
import itertools
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hadamard = load("verify_hadamard", ROOT / "scripts" / "verify_hadamard.py")
ramsey = load("verify_ramsey_book", ROOT / "scripts" / "verify_ramsey_book.py")
arithmetic_kakeya = load(
    "verify_arithmetic_kakeya",
    ROOT / "scripts" / "verify_arithmetic_kakeya.py",
)


def test_hadamard_order_four_passes():
    matrix = [
        [1, 1, 1, 1],
        [1, -1, 1, -1],
        [1, 1, -1, -1],
        [1, -1, -1, 1],
    ]
    assert hadamard.verify(matrix, 4)["status"] == "shadow-verifier-pass"


def test_hadamard_contract_binds_order_four():
    contract, contract_hash, contract_id, manifest_hash = hadamard.load_contract(
        ROOT / "tests" / "fixtures" / "hadamard-order-4-contract.json"
    )
    assert contract["target"]["order"] == 4
    assert len(contract_hash) == 64
    assert contract_id == "fixture-hadamard-order-4"
    assert len(manifest_hash) == 64


def test_hadamard_order_one_boundary_passes():
    assert hadamard.verify([[1]], 1)["status"] == "shadow-verifier-pass"


def test_hadamard_direct_semantics_reject_invalid_entry():
    result = hadamard.verify([[1, 0], [1, -1]], 2)
    assert result["status"] == "shadow-verifier-reject"
    assert result["failure"] == "entry-outside-plus-minus-one"


def test_hadamard_local_defect_has_row_witness():
    matrix = [
        [1, 1, 1, 1],
        [1, -1, 1, -1],
        [1, 1, -1, -1],
        [1, -1, -1, -1],
    ]
    result = hadamard.verify(matrix, 4)
    assert result["status"] == "shadow-verifier-reject"
    assert result["failure"] == "non-orthogonal-row-pair"
    assert len(result["rows_zero_indexed"]) == 2


def test_ramsey_published_column_major_example():
    adjacency = ramsey.decode_adjacency("011010", 4)
    assert ramsey.edge_set(adjacency) == {(0, 2), (1, 2), (1, 3)}


def test_ramsey_rejects_malformed_length():
    try:
        ramsey.decode_adjacency("0", 4)
    except ValueError as exc:
        assert "wrong adjacency length" in str(exc)
    else:
        raise AssertionError("malformed adjacency string was accepted")


def test_ramsey_rejects_internal_whitespace():
    try:
        ramsey.normalized_bits("010 101")
    except ValueError as exc:
        assert "internal whitespace" in str(exc)
    else:
        raise AssertionError("internal whitespace was silently normalized")


def test_ramsey_known_valid_n_two_passes():
    result = ramsey.verify("000011101011000", 2)
    assert result["status"] == "shadow-verifier-pass"


def test_arithmetic_kakeya_katz_tao_warmup_passes():
    candidate = arithmetic_kakeya.parse_candidate_bytes(
        (
            ROOT
            / "tests"
            / "fixtures"
            / "arithmetic-kakeya-katz-tao-7-over-4.txt"
        ).read_bytes()
    )
    result = arithmetic_kakeya.verify(
        candidate,
        arithmetic_kakeya.Fraction(7, 4),
    )
    assert result["status"] == "shadow-verifier-pass"
    assert result["score"] == "7/4"
    assert result["parameters"] == {"m": 4, "r": 3, "n": 4, "t": 0}
    assert result["forcing_rounds"][0] == [[2, 2]]


def test_arithmetic_kakeya_warmup_misses_full_threshold():
    candidate = arithmetic_kakeya.parse_candidate_bytes(
        (
            ROOT
            / "tests"
            / "fixtures"
            / "arithmetic-kakeya-katz-tao-7-over-4.txt"
        ).read_bytes()
    )
    result = arithmetic_kakeya.verify(
        candidate,
        arithmetic_kakeya.Fraction(67, 40),
    )
    assert result["status"] == "shadow-verifier-reject"
    assert result["failure"] == "score-above-contract-threshold"


def test_arithmetic_kakeya_ignores_false_human_header():
    path = (
        ROOT
        / "tests"
        / "fixtures"
        / "arithmetic-kakeya-katz-tao-7-over-4.txt"
    )
    raw = path.read_bytes().replace(
        b"7/4; m=4, |R|=3, n=4, |T|=0",
        b"1/1; m=0, |R|=0, n=99, |T|=0",
        1,
    )
    candidate = arithmetic_kakeya.parse_candidate_bytes(raw)
    result = arithmetic_kakeya.verify(
        candidate,
        arithmetic_kakeya.Fraction(7, 4),
    )
    assert result["score"] == "7/4"
    assert result["parameters"] == {"m": 4, "r": 3, "n": 4, "t": 0}


def test_arithmetic_kakeya_parser_requires_exactly_six_lines():
    path = (
        ROOT
        / "tests"
        / "fixtures"
        / "arithmetic-kakeya-katz-tao-7-over-4.txt"
    )
    raw = path.read_bytes() + b"extra\n"
    try:
        arithmetic_kakeya.parse_candidate_bytes(raw)
    except ValueError as exc:
        assert "exactly six lines" in str(exc)
    else:
        raise AssertionError("seven-line candidate was accepted")


def test_arithmetic_kakeya_rejects_bare_integer_vertex_key():
    path = (
        ROOT
        / "tests"
        / "fixtures"
        / "arithmetic-kakeya-katz-tao-7-over-4.txt"
    )
    raw = path.read_bytes().replace(b"{(1,): (1, 0)}", b"{1: (1, 0)}", 1)
    try:
        arithmetic_kakeya.parse_candidate_bytes(raw)
    except ValueError as exc:
        assert "exactly 1 coordinates" in str(exc)
    else:
        raise AssertionError("unstated bare-integer vertex normalization was accepted")


def test_arithmetic_kakeya_rejects_non_singleton_R_row():
    path = (
        ROOT
        / "tests"
        / "fixtures"
        / "arithmetic-kakeya-katz-tao-7-over-4.txt"
    )
    raw = path.read_bytes().replace(
        b"{(1, 1): (1, 1)}",
        b"{(1, 1): (1, 1), (2, 2): (1, 0)}",
        1,
    )
    try:
        arithmetic_kakeya.parse_candidate_bytes(raw)
    except ValueError as exc:
        assert "exactly one nonzero support" in str(exc)
    else:
        raise AssertionError("multi-support submitted row was accepted")


def test_arithmetic_kakeya_contract_binds_exact_score():
    contract, contract_hash, contract_id, manifest_hash = (
        arithmetic_kakeya.load_contract(
            ROOT
            / "contracts"
            / "arithmetic-kakeya-warmup-2026-06-27.json"
        )
    )
    assert contract["target"] == {
        "score_numerator": 7,
        "score_denominator": 4,
    }
    assert len(contract_hash) == 64
    assert contract_id == "arithmetic-kakeya-warmup-2026-06-27"
    assert len(manifest_hash) == 64


def test_arithmetic_kakeya_same_tail_expansion():
    candidate = arithmetic_kakeya.Candidate(
        claimed_header="fixture",
        x_set=((0, 0), (1, 0)),
        dimensions=(2, 3),
        graph_functions=({(1,): (1, 0)}, {}),
        initial_known=(),
        singleton_rows=(),
    )
    edges = arithmetic_kakeya.graph_edges(candidate)
    assert len(edges) == 3
    assert {left[1] for left, _, _ in edges} == {1, 2, 3}
    assert all(left[1:] == right[1:] for left, right, _ in edges)


def test_arithmetic_kakeya_rational_span_is_integer_witness_equivalent():
    basis, pivots = arithmetic_kakeya.rref_rows([[2, -2]])
    assert arithmetic_kakeya.in_row_span([1, -1], basis, pivots)


def test_ramsey_contract_binds_n_two():
    contract, contract_hash, contract_id, manifest_hash = ramsey.load_contract(
        ROOT / "tests" / "fixtures" / "ramsey-book-n-2-contract.json"
    )
    assert contract["target"]["n"] == 2
    assert len(contract_hash) == 64
    assert contract_id == "fixture-ramsey-book-n-2"
    assert len(manifest_hash) == 64


def test_ramsey_complete_graph_is_rejected_with_spine():
    n = 2
    vertices = 4 * n - 2
    bits = "1" * (vertices * (vertices - 1) // 2)
    result = ramsey.verify(bits, n)
    assert result["status"] == "shadow-verifier-reject"
    assert result["failure"] == "graph-contains-forbidden-book"
    assert len(result["spine_edge"]) == 2
    assert "forbidden-B_(n-1)-witness-in-graph" in result["checked_predicates"]


def naive_ramsey_accepts(bits: str, n: int) -> bool:
    vertex_count = 4 * n - 2
    adjacency = ramsey.edge_set(ramsey.decode_adjacency(bits, vertex_count))
    vertices = set(range(vertex_count))
    for left, right in itertools.combinations(range(vertex_count), 2):
        common = vertices - {left, right}
        if (left, right) in adjacency:
            pages = sum(
                (min(left, page), max(left, page)) in adjacency
                and (min(right, page), max(right, page)) in adjacency
                for page in common
            )
            if pages >= n - 1:
                return False
        else:
            pages = sum(
                (min(left, page), max(left, page)) not in adjacency
                and (min(right, page), max(right, page)) not in adjacency
                for page in common
            )
            if pages >= n:
                return False
    return True


def test_ramsey_n_two_exhaustive_cross_check():
    vertex_count = 6
    edge_count = vertex_count * (vertex_count - 1) // 2
    for encoded in range(1 << edge_count):
        bits = f"{encoded:0{edge_count}b}"
        bitset_result = ramsey.verify(bits, 2)["status"] == "shadow-verifier-pass"
        assert bitset_result == naive_ramsey_accepts(bits, 2)


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_hadamard_rejects_registered_prompt_with_mutated_target(tmp_path: Path):
    original = ROOT / "contracts" / "hadamard-668-full-2026-06-27.json"
    contract = json.loads(original.read_text(encoding="utf-8"))
    contract["target"]["order"] = 4
    forged = tmp_path / "forged-hadamard-contract.json"
    forged.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    completed = run_cli(
        str(ROOT / "scripts" / "verify_hadamard.py"),
        str(ROOT / "tests" / "fixtures" / "hadamard-order-4.csv"),
        "--contract",
        str(forged),
    )
    packet = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert packet["status"] == "input-error"
    assert "not registered in the bundled manifest" in packet["error"]
    assert packet["prompt_snapshot"]["contract_registry"]["status"] == (
        "unregistered-or-invalid"
    )


def test_ramsey_rejects_registered_prompt_with_mutated_target(tmp_path: Path):
    original = ROOT / "contracts" / "ramsey-book-n25-warmup-2026-06-27.json"
    contract = json.loads(original.read_text(encoding="utf-8"))
    contract["target"]["n"] = 2
    forged = tmp_path / "forged-ramsey-contract.json"
    forged.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    completed = run_cli(
        str(ROOT / "scripts" / "verify_ramsey_book.py"),
        "--adjacency-file",
        str(ROOT / "tests" / "fixtures" / "ramsey-book-n-2.txt"),
        "--contract",
        str(forged),
    )
    packet = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert packet["status"] == "input-error"
    assert "not registered in the bundled manifest" in packet["error"]
    assert packet["prompt_snapshot"]["contract_registry"]["status"] == (
        "unregistered-or-invalid"
    )


def test_arithmetic_kakeya_rejects_registered_prompt_with_mutated_target(
    tmp_path: Path,
):
    original = (
        ROOT
        / "contracts"
        / "arithmetic-kakeya-warmup-2026-06-27.json"
    )
    contract = json.loads(original.read_text(encoding="utf-8"))
    contract["target"] = {
        "score_numerator": 67,
        "score_denominator": 40,
    }
    forged = tmp_path / "forged-arithmetic-kakeya-contract.json"
    forged.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    completed = run_cli(
        str(ROOT / "scripts" / "verify_arithmetic_kakeya.py"),
        str(
            ROOT
            / "tests"
            / "fixtures"
            / "arithmetic-kakeya-katz-tao-7-over-4.txt"
        ),
        "--contract",
        str(forged),
    )
    packet = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert packet["status"] == "input-error"
    assert "not registered in the bundled manifest" in packet["error"]
    assert packet["prompt_snapshot"]["contract_registry"]["status"] == (
        "unregistered-or-invalid"
    )


def test_hadamard_packet_uses_privacy_safe_contract_id():
    completed = run_cli(
        str(ROOT / "scripts" / "verify_hadamard.py"),
        str(ROOT / "tests" / "fixtures" / "hadamard-order-4.csv"),
        "--contract",
        str(ROOT / "tests" / "fixtures" / "hadamard-order-4-contract.json"),
    )
    packet = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert packet["prompt_snapshot"]["contract_id"] == "fixture-hadamard-order-4"
    assert "contract_path" not in packet["prompt_snapshot"]


def test_ramsey_packet_uses_privacy_safe_contract_id():
    completed = run_cli(
        str(ROOT / "scripts" / "verify_ramsey_book.py"),
        "--adjacency-file",
        str(ROOT / "tests" / "fixtures" / "ramsey-book-n-2.txt"),
        "--contract",
        str(ROOT / "tests" / "fixtures" / "ramsey-book-n-2-contract.json"),
    )
    packet = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert packet["prompt_snapshot"]["contract_id"] == "fixture-ramsey-book-n-2"
    assert "contract_path" not in packet["prompt_snapshot"]


def test_hadamard_contract_reader_rejects_oversize_file(tmp_path: Path):
    oversized = tmp_path / "oversized-contract.json"
    oversized.write_bytes(b"x" * (hadamard.MAX_CONTRACT_BYTES + 1))
    try:
        hadamard.load_contract(oversized)
    except ValueError as exc:
        assert "exceeds" in str(exc)
    else:
        raise AssertionError("oversized Hadamard contract was accepted")


def test_ramsey_candidate_reader_rejects_oversize_file(tmp_path: Path):
    oversized = tmp_path / "oversized-candidate.txt"
    oversized.write_bytes(b"0" * (ramsey.MAX_CANDIDATE_BYTES + 1))
    try:
        ramsey.read_bytes_limited(
            oversized,
            ramsey.MAX_CANDIDATE_BYTES,
            "candidate",
        )
    except ValueError as exc:
        assert "exceeds" in str(exc)
    else:
        raise AssertionError("oversized Ramsey candidate was accepted")


def test_all_bundled_public_contracts_resolve_through_manifest():
    expected = {
        "hadamard-428-warmup-2026-06-27",
        "hadamard-668-full-2026-06-27",
        "ramsey-book-n25-warmup-2026-06-27",
        "arithmetic-kakeya-warmup-2026-06-27",
        "arithmetic-kakeya-full-2026-06-27",
    }
    observed = {
        hadamard.load_contract(
            ROOT / "contracts" / "hadamard-428-warmup-2026-06-27.json"
        )[2],
        hadamard.load_contract(
            ROOT / "contracts" / "hadamard-668-full-2026-06-27.json"
        )[2],
        ramsey.load_contract(
            ROOT / "contracts" / "ramsey-book-n25-warmup-2026-06-27.json"
        )[2],
        arithmetic_kakeya.load_contract(
            ROOT / "contracts" / "arithmetic-kakeya-warmup-2026-06-27.json"
        )[2],
        arithmetic_kakeya.load_contract(
            ROOT / "contracts" / "arithmetic-kakeya-full-2026-06-27.json"
        )[2],
    }
    assert observed == expected
