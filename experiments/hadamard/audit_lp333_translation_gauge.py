#!/usr/bin/env python3
"""Independent audit of the ID4/ID5 normalized-translation singleton gauge."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


LENGTH = 333


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_translate(
    pattern: tuple[int, int, int], offset: int
) -> tuple[int, int, int]:
    return tuple(
        pattern[(index + offset) % 3] ^ pattern[offset]
        for index in range(3)
    )


def parse_clause(line: str) -> tuple[int, ...]:
    values = tuple(int(item) for item in line.split())
    if not values or values[-1] != 0:
        raise ValueError("invalid DIMACS clause")
    return values[:-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f"refusing to overwrite {args.output}")
    metadata = json.loads(args.metadata.read_text())
    gauge = metadata["independent_translation_gauge"]
    elements = metadata["subgroup"]["elements"]
    translations = [
        translation
        for translation in range(LENGTH)
        if all(
            ((unit - 1) * translation) % LENGTH == 0
            for unit in elements
        )
    ]
    if translations != [0, 111, 222]:
        raise ValueError("independent annihilator is not {0,111,222}")

    sizes = [len(orbit) for orbit in metadata["subgroup"]["orbits"]]
    if sizes.count(1) != 3 or sizes.count(3) != 110:
        raise ValueError("unexpected ID4/ID5 orbit signature")
    feasible = []
    cases = []
    for left in (0, 1):
        for right in (0, 1):
            for triples in range(111):
                weighted = left + right + 3 * triples
                if weighted in (166, 167):
                    feasible.append((0, left, right))
                    cases.append(((0, left, right), triples, weighted))
    feasible = sorted(set(feasible))
    expected = [(0, 0, 1), (0, 1, 0), (0, 1, 1)]
    if feasible != expected:
        raise ValueError("weighted row sums yield unexpected singleton patterns")
    for pattern in feasible:
        orbit = sorted(
            {normalized_translate(pattern, offset) for offset in range(3)}
        )
        if orbit != expected or min(orbit) != (0, 0, 1):
            raise ValueError("translation orbit lacks the declared canonical point")

    formula = Path(metadata["cnf"]["path"])
    if sha256(formula) != metadata["cnf"]["sha256"]:
        raise ValueError("formula hash mismatch")
    gadgets = gauge["serialized_unit_gadgets"]
    expected_clauses = set()
    for gadget in gadgets:
        literal = gadget["source_literal"]
        mask = gadget["mask_variable"]
        expected_clauses.add((literal, mask))
        expected_clauses.add((literal, -mask))
    found = set()
    with formula.open("r", encoding="ascii") as handle:
        header = handle.readline().split()
        if header != [
            "p",
            "cnf",
            str(metadata["cnf"]["variables"]),
            str(metadata["cnf"]["clauses"]),
        ]:
            raise ValueError("DIMACS header mismatch")
        for line in handle:
            clause = parse_clause(line)
            if clause in expected_clauses:
                found.add(clause)
    if found != expected_clauses:
        raise ValueError("serialized translation-gauge unit gadgets are incomplete")

    control = metadata["controls"]["normalized_translation_automorphism"]
    if (
        control["result"] != "PASS"
        or control["translations"] != translations
        or control["direct_paf_equalities"] != 16 * 3 * 332
    ):
        raise ValueError("generator automorphism control is incomplete")
    result = {
        "schema": "frontiermath-hadamard-translation-gauge-audit-v1",
        "status": "pass",
        "family_id": metadata["family_id"],
        "formula_sha256": metadata["cnf"]["sha256"],
        "metadata_sha256": sha256(args.metadata),
        "checks": {
            "annihilator": translations,
            "orbit_signature": {"1": 3, "3": 110},
            "row_sum_cases": [
                {
                    "pattern": list(pattern),
                    "triple_negative_orbits": triples,
                    "weighted_negative_count": weighted,
                }
                for pattern, triples, weighted in cases
            ],
            "one_size_three_singleton_orbit": True,
            "unique_canonical_pattern": [0, 0, 1],
            "independent_pair_action_order": 9,
            "serialized_gauge_clauses_checked": len(found),
            "direct_paf_automorphism_checks": control[
                "direct_paf_equalities"
            ],
        },
        "method": (
            "Recompute the modular annihilator, weighted row-sum cases, "
            "three-point normalized action, and exact DIMACS gauge gadgets "
            "without importing the generator or proof encoder."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
