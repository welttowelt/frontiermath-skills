from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path


HADAMARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HADAMARD))

from generate_id3_profile_cell_cnf import (  # noqa: E402
    CNF,
    build_cell,
    twos_complement_bits,
)


def clauses_hold(cnf: CNF, assignment: dict[int, bool]) -> bool:
    return all(
        any(assignment[abs(literal)] == (literal > 0) for literal in clause)
        for clause in cnf.clauses
    )


def base_assignment(cnf: CNF) -> dict[int, bool]:
    return {cnf.false: False, cnf.true: True}


def test_twos_complement_bits_round_trip() -> None:
    for width in range(2, 10):
        for value in range(-(1 << (width - 1)), 1 << (width - 1)):
            bits = twos_complement_bits(value, width)
            encoded = sum(bit << index for index, bit in enumerate(bits))
            decoded = encoded if encoded < 1 << (width - 1) else encoded - (1 << width)
            assert decoded == value


def test_xor_gate_truth_table() -> None:
    cnf = CNF()
    left = cnf.new_var("left")
    right = cnf.new_var("right")
    output = cnf.xor2(left, right, "output")
    for left_value, right_value, output_value in itertools.product(
        (False, True), repeat=3
    ):
        assignment = base_assignment(cnf)
        assignment.update(
            {
                left: left_value,
                right: right_value,
                output: output_value,
            }
        )
        assert clauses_hold(cnf, assignment) == (
            output_value == (left_value ^ right_value)
        )


def test_majority_gate_truth_table() -> None:
    cnf = CNF()
    a = cnf.new_var("a")
    b = cnf.new_var("b")
    c = cnf.new_var("c")
    output = cnf.majority3(a, b, c, "output")
    for a_value, b_value, c_value, output_value in itertools.product(
        (False, True), repeat=4
    ):
        assignment = base_assignment(cnf)
        assignment.update(
            {
                a: a_value,
                b: b_value,
                c: c_value,
                output: output_value,
            }
        )
        expected = sum((a_value, b_value, c_value)) >= 2
        assert clauses_hold(cnf, assignment) == (output_value == expected)


def test_pilot_encoding_shapes_are_locked() -> None:
    cell_0, description_0 = build_cell(0, {25: 12, 49: 6})
    assert cell_0.variable_count == 12_044
    assert len(cell_0.clauses) == 67_572
    assert description_0["allowed_values"] == [-7, -5, 5, 7]

    cell_73, description_73 = build_cell(
        73, {1: 12, 49: 2, 121: 4}
    )
    assert cell_73.variable_count == 12_728
    assert len(cell_73.clauses) == 92_904
    assert description_73["allowed_values"] == [-11, -7, -1, 1, 7, 11]


def test_saved_pilot_controls_pass() -> None:
    result_dir = HADAMARD / "results" / "id3-profile-proof-pilot"
    manifest = json.loads(
        (result_dir / "pilot-manifest.json").read_text(encoding="utf-8")
    )
    direct = json.loads(
        (
            result_dir
            / "id3-profile-cell-73-model-verification.json"
        ).read_text(encoding="utf-8")
    )
    arithmetic = json.loads(
        (
            result_dir
            / "id3-profile-cell-73-arithmetic-verification.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["status"] == "pass"
    assert all(manifest["gate_a_checks"].values())
    assert direct["status"] == "pass"
    assert direct["cnf_model_satisfied"] is True
    assert arithmetic["status"] == "pass"
