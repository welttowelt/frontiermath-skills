#!/usr/bin/env python3
"""Generate compact proof-carrying CNF controls for id3 profile cells.

The encoding is deliberately elementary and auditable:

* one-hot compressed values at each of the 18 positions;
* ripple-carry bit-vector sums for row sums and exact square counts;
* explicit 9 x 12 binary margin matrices for the prescribed q^2 profile;
* truth-table product bits followed by ripple-carry sums for the four
  independent length-9 periodic-autocorrelation equations.

The two pilot cells are bound to the refined finite-ledger artifact by hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable


P = 37
Q = 3
K37 = (1, 10, 26)
LENGTH = 9
TARGET_NORM = 594
TARGET_PAF = -74
EXPECTED_LEDGER_SHA256 = (
    "1760d0337f518fe7b6bc79bbd619d3ea07ba093c810f81cc9fe5bf8bd44f0532"
)
PILOT_CONTROL_SQUARE_COUNTS = {
    0: {25: 12, 49: 6},
    73: {1: 12, 49: 2, 121: 4},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def twos_complement_bits(value: int, width: int) -> list[int]:
    if not -(1 << (width - 1)) <= value < (1 << (width - 1)):
        raise ValueError(f"{value} does not fit signed width {width}")
    encoded = value if value >= 0 else (1 << width) + value
    return [(encoded >> bit) & 1 for bit in range(width)]


def unsigned_bits(value: int, width: int) -> list[int]:
    if not 0 <= value < (1 << width):
        raise ValueError(f"{value} does not fit unsigned width {width}")
    return [(value >> bit) & 1 for bit in range(width)]


class CNF:
    """Small deterministic Tseitin CNF builder."""

    def __init__(self) -> None:
        self.variable_count = 0
        self.clauses: list[tuple[int, ...]] = []
        self.names: dict[str, int] = {}
        self.false = self.new_var("constant_false")
        self.true = self.new_var("constant_true")
        self.add_clause(-self.false)
        self.add_clause(self.true)

    def new_var(self, name: str) -> int:
        if name in self.names:
            raise ValueError(f"duplicate variable name {name}")
        self.variable_count += 1
        self.names[name] = self.variable_count
        return self.variable_count

    def add_clause(self, *literals: int) -> None:
        if not literals:
            raise ValueError("refusing to add an empty clause")
        if any(literal == 0 for literal in literals):
            raise ValueError("zero is not a clause literal")
        self.clauses.append(tuple(literals))

    def exactly_one(self, variables: list[int]) -> None:
        if not variables:
            raise ValueError("exactly-one requires at least one variable")
        self.add_clause(*variables)
        for left_index, left in enumerate(variables):
            for right in variables[left_index + 1 :]:
                self.add_clause(-left, -right)

    def xor2(self, left: int, right: int, name: str) -> int:
        output = self.new_var(name)
        self.add_clause(-left, -right, -output)
        self.add_clause(left, right, -output)
        self.add_clause(left, -right, output)
        self.add_clause(-left, right, output)
        return output

    def majority3(self, a: int, b: int, c: int, name: str) -> int:
        output = self.new_var(name)
        self.add_clause(-a, -b, output)
        self.add_clause(-a, -c, output)
        self.add_clause(-b, -c, output)
        self.add_clause(a, b, -output)
        self.add_clause(a, c, -output)
        self.add_clause(b, c, -output)
        return output

    def add_vectors(
        self,
        left: list[int],
        right: list[int],
        name: str,
    ) -> list[int]:
        if len(left) != len(right):
            raise ValueError("bit-vector widths differ")
        carry = self.false
        result = []
        for bit, (a, b) in enumerate(zip(left, right)):
            partial = self.xor2(a, b, f"{name}_xor_ab_{bit}")
            result.append(
                self.xor2(partial, carry, f"{name}_sum_{bit}")
            )
            carry = self.majority3(
                a, b, carry, f"{name}_carry_{bit + 1}"
            )
        return result

    def sum_vectors(
        self,
        vectors: Iterable[list[int]],
        width: int,
        name: str,
    ) -> list[int]:
        total = [self.false] * width
        for index, vector in enumerate(vectors):
            if len(vector) != width:
                raise ValueError("summand has the wrong width")
            total = self.add_vectors(total, vector, f"{name}_add_{index}")
        return total

    def sum_booleans(
        self,
        variables: Iterable[int],
        width: int,
        name: str,
    ) -> list[int]:
        vectors = (
            [variable] + [self.false] * (width - 1)
            for variable in variables
        )
        return self.sum_vectors(vectors, width, name)

    def fix_bits(self, bits: list[int], expected: list[int]) -> None:
        if len(bits) != len(expected):
            raise ValueError("fixed bit-vector widths differ")
        for variable, value in zip(bits, expected):
            self.add_clause(variable if value else -variable)

    def selected_constant_bits(
        self,
        selectors: dict[int, int],
        width: int,
        name: str,
    ) -> list[int]:
        bits = [self.new_var(f"{name}_bit_{bit}") for bit in range(width)]
        for value, selector in sorted(selectors.items()):
            encoded = twos_complement_bits(value, width)
            for bit, expected in zip(bits, encoded):
                self.add_clause(-selector, bit if expected else -bit)
        return bits


def legendre_symbol(value: int) -> int:
    residue = pow(value % P, (P - 1) // 2, P)
    return 0 if residue == 0 else (1 if residue == 1 else -1)


def k37_orbits() -> list[list[int]]:
    unseen = set(range(P))
    orbits = []
    while unseen:
        seed = min(unseen)
        orbit = sorted({(multiplier * seed) % P for multiplier in K37})
        unseen.difference_update(orbit)
        orbits.append(orbit)
    return orbits


def prescribed_nonzero_column_degrees(sign: int) -> list[int]:
    return [
        (LENGTH + sign * Q * legendre_symbol(orbit[0])) // 2
        for orbit in k37_orbits()[1:]
    ]


def value_degree(value: int) -> tuple[int, int]:
    singleton = 1 if value % 3 == 1 else -1
    numerator = (value - singleton) // 3 + 12
    if numerator % 2:
        raise ValueError(f"value {value} has nonintegral id3 degree")
    degree = numerator // 2
    if not 0 <= degree <= 12:
        raise ValueError(f"value {value} has invalid id3 degree")
    return singleton, degree


def load_cell(
    ledger_path: Path,
    cell_id: int,
) -> tuple[dict[int, int], str]:
    ledger_hash = sha256_file(ledger_path)
    if ledger_hash != EXPECTED_LEDGER_SHA256:
        raise ValueError(
            "refined ledger hash mismatch: "
            f"{ledger_hash} != {EXPECTED_LEDGER_SHA256}"
        )
    document = json.loads(ledger_path.read_text(encoding="utf-8"))
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("ledger has no records list")
    matching = [
        record
        for record in records
        if isinstance(record, dict) and record.get("id") == cell_id
    ]
    if len(matching) != 1:
        raise ValueError(f"expected one ledger record for cell {cell_id}")
    raw_counts = matching[0].get("square_counts")
    if not isinstance(raw_counts, dict):
        raise ValueError(f"cell {cell_id} has no square counts")
    counts = {int(square): int(count) for square, count in raw_counts.items()}
    expected = PILOT_CONTROL_SQUARE_COUNTS.get(cell_id)
    if expected is not None and counts != expected:
        raise ValueError(
            f"control cell {cell_id} counts {counts} do not match {expected}"
        )
    if sum(counts.values()) != 2 * LENGTH:
        raise ValueError("square counts do not cover all 18 positions")
    if sum(square * count for square, count in counts.items()) != TARGET_NORM:
        raise ValueError("square counts do not have norm 594")
    return counts, ledger_hash


def build_cell(
    cell_id: int,
    square_counts: dict[int, int],
) -> tuple[CNF, dict[str, object]]:
    cnf = CNF()
    magnitudes = sorted(math.isqrt(square) for square in square_counts)
    if any(magnitude * magnitude not in square_counts for magnitude in magnitudes):
        raise ValueError("cell contains a nonsquare")
    allowed_values = sorted(
        value for magnitude in magnitudes for value in (-magnitude, magnitude)
    )

    value_variables: list[list[dict[int, int]]] = [[], []]
    value_bit_vectors: list[list[list[int]]] = [[], []]
    epsilon_variables: list[list[int]] = [[], []]
    margin_variables: list[list[list[int]]] = [[], []]

    for sequence_index, sequence_name in enumerate(("a", "b")):
        for row in range(LENGTH):
            selectors = {
                value: cnf.new_var(f"{sequence_name}_{row}_is_{value}")
                for value in allowed_values
            }
            cnf.exactly_one(list(selectors.values()))
            value_variables[sequence_index].append(selectors)
            value_bit_vectors[sequence_index].append(
                cnf.selected_constant_bits(
                    selectors, 10, f"{sequence_name}_{row}_value"
                )
            )

            epsilon_plus = cnf.new_var(
                f"{sequence_name}_{row}_singleton_plus"
            )
            epsilon_variables[sequence_index].append(epsilon_plus)
            for value, selector in selectors.items():
                singleton, _ = value_degree(value)
                cnf.add_clause(
                    -selector,
                    epsilon_plus if singleton == 1 else -epsilon_plus,
                )

            margin_row = [
                cnf.new_var(f"{sequence_name}_{row}_margin_{column}")
                for column in range(12)
            ]
            margin_variables[sequence_index].append(margin_row)
            row_degree = cnf.sum_booleans(
                margin_row, 4, f"{sequence_name}_{row}_margin_degree"
            )
            for value, selector in selectors.items():
                _, degree = value_degree(value)
                for bit, expected in zip(
                    row_degree, unsigned_bits(degree, 4)
                ):
                    cnf.add_clause(
                        -selector, bit if expected else -bit
                    )

        row_sum = cnf.sum_vectors(
            value_bit_vectors[sequence_index],
            10,
            f"{sequence_name}_row_sum",
        )
        cnf.fix_bits(row_sum, twos_complement_bits(1, 10))

        singleton_plus_count = cnf.sum_booleans(
            epsilon_variables[sequence_index],
            4,
            f"{sequence_name}_singleton_plus_count",
        )
        cnf.fix_bits(singleton_plus_count, unsigned_bits(5, 4))

        target_degrees = prescribed_nonzero_column_degrees(
            1 if sequence_index == 0 else -1
        )
        for column, target in enumerate(target_degrees):
            column_sum = cnf.sum_booleans(
                (
                    margin_variables[sequence_index][row][column]
                    for row in range(LENGTH)
                ),
                4,
                f"{sequence_name}_column_{column}_sum",
            )
            cnf.fix_bits(column_sum, unsigned_bits(target, 4))

    for magnitude in magnitudes:
        selectors = []
        for sequence_index in range(2):
            for row in range(LENGTH):
                selectors.extend(
                    (
                        value_variables[sequence_index][row][-magnitude],
                        value_variables[sequence_index][row][magnitude],
                    )
                )
        count_bits = cnf.sum_booleans(
            selectors, 6, f"magnitude_{magnitude}_count"
        )
        cnf.fix_bits(
            count_bits,
            unsigned_bits(square_counts[magnitude * magnitude], 6),
        )

    for shift in range(1, 5):
        products = []
        for sequence_index, sequence_name in enumerate(("a", "b")):
            for row in range(LENGTH):
                next_row = (row + shift) % LENGTH
                product_bits = [
                    cnf.new_var(
                        f"{sequence_name}_product_{shift}_{row}_bit_{bit}"
                    )
                    for bit in range(15)
                ]
                left = value_variables[sequence_index][row]
                right = value_variables[sequence_index][next_row]
                for left_value, left_selector in sorted(left.items()):
                    for right_value, right_selector in sorted(right.items()):
                        expected_bits = twos_complement_bits(
                            left_value * right_value, 15
                        )
                        for bit, expected in zip(
                            product_bits, expected_bits
                        ):
                            cnf.add_clause(
                                -left_selector,
                                -right_selector,
                                bit if expected else -bit,
                            )
                products.append(product_bits)
        paf_sum = cnf.sum_vectors(products, 15, f"paf_shift_{shift}")
        cnf.fix_bits(paf_sum, twos_complement_bits(TARGET_PAF, 15))

    variable_map = {
        "value_variables": [
            [
                {str(value): variable for value, variable in sorted(row.items())}
                for row in sequence
            ]
            for sequence in value_variables
        ],
        "epsilon_plus_variables": epsilon_variables,
        "margin_variables": margin_variables,
    }
    description = {
        "allowed_values": allowed_values,
        "square_counts": {
            str(square): count for square, count in sorted(square_counts.items())
        },
        "prescribed_column_plus_degrees": [
            prescribed_nonzero_column_degrees(1),
            prescribed_nonzero_column_degrees(-1),
        ],
        "variable_map": variable_map,
    }
    return cnf, description


def write_dimacs(
    cnf: CNF,
    output: Path,
    comments: dict[str, object],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="ascii", newline="\n") as handle:
        for key, value in comments.items():
            handle.write(f"c {key} {value}\n")
        handle.write(f"p cnf {cnf.variable_count} {len(cnf.clauses)}\n")
        for clause in cnf.clauses:
            handle.write(" ".join(map(str, clause)) + " 0\n")


def generate(
    ledger_path: Path,
    cell_id: int,
    cnf_path: Path,
    metadata_path: Path,
) -> dict[str, object]:
    square_counts, ledger_hash = load_cell(ledger_path, cell_id)
    cnf, description = build_cell(cell_id, square_counts)
    encoder_hash = sha256_file(Path(__file__).resolve())
    write_dimacs(
        cnf,
        cnf_path,
        {
            "schema": "frontiermath-hadamard-id3-profile-cell-cnf-v1",
            "cell_id": cell_id,
            "refined_ledger_sha256": ledger_hash,
            "encoder_sha256": encoder_hash,
        },
    )
    result = {
        "schema": "frontiermath-hadamard-id3-profile-cell-encoding-v1",
        "status": "generated",
        "cell_id": cell_id,
        "scope": (
            "length-9 PAF feasibility plus explicit prescribed q^2 margins; "
            "full LP(333) PAF equations are unchecked"
        ),
        "refined_ledger": str(ledger_path),
        "refined_ledger_sha256": ledger_hash,
        "encoder_sha256": encoder_hash,
        "cnf": str(cnf_path),
        "cnf_sha256": sha256_file(cnf_path),
        "cnf_bytes": cnf_path.stat().st_size,
        "variables": cnf.variable_count,
        "clauses": len(cnf.clauses),
        **description,
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--cell-id", required=True, type=int)
    parser.add_argument("--cnf-output", required=True, type=Path)
    parser.add_argument("--metadata-output", required=True, type=Path)
    args = parser.parse_args()

    if not 0 <= args.cell_id < 95:
        parser.error("--cell-id must be between 0 and 94")
    result = generate(
        args.ledger,
        args.cell_id,
        args.cnf_output,
        args.metadata_output,
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "status",
                    "cell_id",
                    "refined_ledger_sha256",
                    "cnf_sha256",
                    "cnf_bytes",
                    "variables",
                    "clauses",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
