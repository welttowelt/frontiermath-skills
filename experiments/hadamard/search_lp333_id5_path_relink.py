#!/usr/bin/env python3
"""Greedy exact path relinking between two audited LP333 ID5 states."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


LENGTH = 333
HALF = 166
SUBGROUP = (1, 211, 232)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def paf(sequence: list[int]) -> list[int]:
    return [
        sum(
            sequence[index] * sequence[(index + shift) % LENGTH]
            for index in range(LENGTH)
        )
        for shift in range(LENGTH)
    ]


def coordinate_orbits() -> list[list[int]]:
    unseen = set(range(LENGTH))
    result = []
    while unseen:
        seed = min(unseen)
        orbit = sorted({seed * unit % LENGTH for unit in SUBGROUP})
        unseen.difference_update(orbit)
        result.append(orbit)
    if (
        len(result) != 113
        or sum(len(orbit) == 1 for orbit in result) != 3
        or sum(len(orbit) == 3 for orbit in result) != 110
    ):
        raise ValueError("ID5 coordinate-orbit signature changed")
    return result


def shift_classes() -> list[tuple[int, list[int]]]:
    seen: set[int] = set()
    result = []
    for shift in range(1, HALF + 1):
        if shift in seen:
            continue
        members = sorted(
            {
                min(
                    (shift * unit) % LENGTH,
                    LENGTH - ((shift * unit) % LENGTH),
                )
                for unit in SUBGROUP
            }
        )
        seen.update(members)
        result.append((members[0], members))
    weights = [len(members) for _, members in result]
    if (
        len(result) != 56
        or weights.count(1) != 1
        or weights.count(3) != 55
        or sum(weights) != HALF
    ):
        raise ValueError("ID5 shift-class signature changed")
    return result


ORBITS = coordinate_orbits()
SHIFT_CLASSES = shift_classes()


def measurements(rows: list[list[int]]) -> dict[str, Any]:
    row_pafs = [paf(row) for row in rows]
    residual = [
        row_pafs[0][shift] + row_pafs[1][shift] + 2
        for shift in range(1, HALF + 1)
    ]
    return {
        "pafs": row_pafs,
        "residual": residual,
        "objective": sum(value * value for value in residual),
        "l1": sum(abs(value) for value in residual),
        "maximum": max(map(abs, residual)),
    }


def profile(row: list[int]) -> dict[str, Any]:
    invariant = all(
        len({row[index] for index in orbit}) == 1
        for orbit in ORBITS
    )
    return {
        "invariant": invariant,
        "row_sum": sum(row),
        "negative_singletons": sum(
            len(orbit) == 1 and row[orbit[0]] == -1
            for orbit in ORBITS
        ),
        "negative_triples": sum(
            len(orbit) == 3 and row[orbit[0]] == -1
            for orbit in ORBITS
        ),
    }


def load_state(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text())
    rows = [document.get("a_sequence"), document.get("b_sequence")]
    if not all(
        isinstance(row, list)
        and len(row) == LENGTH
        and set(row) <= {-1, 1}
        for row in rows
    ):
        raise ValueError(f"{path} lacks two binary length-333 rows")
    row_profiles = [profile(row) for row in rows]
    if not all(
        item["invariant"]
        and item["row_sum"] == 1
        and item["negative_singletons"] == 1
        and item["negative_triples"] == 55
        for item in row_profiles
    ):
        raise ValueError(f"{path} is not in fixed family ID5")
    measured = measurements(rows)
    if document.get("best_objective") != measured["objective"]:
        raise ValueError(f"{path} has a stale objective")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "rows": rows,
        "measurements": measured,
        "profiles": row_profiles,
    }


def orbit_values(row: list[int]) -> list[int]:
    return [row[orbit[0]] for orbit in ORBITS]


def flip_delta(
    row: list[int], positions: list[int]
) -> dict[int, int]:
    flipped = set(positions)
    delta = {}
    for representative, _ in SHIFT_CLASSES:
        starts = set(positions)
        starts.update(
            (position - representative) % LENGTH
            for position in positions
        )
        change = 0
        for start in starts:
            end = (start + representative) % LENGTH
            old = row[start] * row[end]
            new_start = -row[start] if start in flipped else row[start]
            new_end = -row[end] if end in flipped else row[end]
            change += new_start * new_end - old
        delta[representative] = change
    return delta


def objective_after(
    residual: dict[int, int], delta: dict[int, int]
) -> int:
    return sum(
        len(members)
        * (residual[representative] + delta[representative]) ** 2
        for representative, members in SHIFT_CLASSES
    )


def apply_move(
    rows: list[list[int]],
    residual: dict[int, int],
    row_index: int,
    left: int,
    right: int,
    delta: dict[int, int],
) -> None:
    for orbit_id in (left, right):
        for index in ORBITS[orbit_id]:
            rows[row_index][index] *= -1
    for representative, _ in SHIFT_CLASSES:
        residual[representative] += delta[representative]


def mismatch_moves(
    rows: list[list[int]], target: list[list[int]]
) -> list[tuple[int, int, int, int]]:
    result = []
    for row_index in range(2):
        current_values = orbit_values(rows[row_index])
        target_values = orbit_values(target[row_index])
        for size in (1, 3):
            negative_to_positive = [
                orbit
                for orbit in range(len(ORBITS))
                if len(ORBITS[orbit]) == size
                and current_values[orbit] == -1
                and target_values[orbit] == 1
            ]
            positive_to_negative = [
                orbit
                for orbit in range(len(ORBITS))
                if len(ORBITS[orbit]) == size
                and current_values[orbit] == 1
                and target_values[orbit] == -1
            ]
            if len(negative_to_positive) != len(positive_to_negative):
                raise ValueError("target-reducing mismatch counts differ")
            result.extend(
                (row_index, size, left, right)
                for left in negative_to_positive
                for right in positive_to_negative
            )
    return result


def run_direction(
    source: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any]:
    rows = copy.deepcopy(source["rows"])
    residual = {
        representative: source["measurements"]["residual"][
            representative - 1
        ]
        for representative, _ in SHIFT_CLASSES
    }
    best_rows = copy.deepcopy(rows)
    best_objective = source["measurements"]["objective"]
    moves = []
    candidates_evaluated = 0
    while rows != target["rows"]:
        candidates = mismatch_moves(rows, target["rows"])
        if not candidates:
            raise ValueError("path stalled before target")
        selected = None
        selected_delta = None
        selected_objective = None
        for row_index, size, left, right in candidates:
            positions = ORBITS[left] + ORBITS[right]
            delta = flip_delta(rows[row_index], positions)
            proposed = objective_after(residual, delta)
            key = (proposed, row_index, size, left, right)
            if selected is None or key < selected:
                selected = key
                selected_delta = delta
                selected_objective = proposed
        assert selected is not None
        assert selected_delta is not None
        assert selected_objective is not None
        _, row_index, size, left, right = selected
        apply_move(
            rows,
            residual,
            row_index,
            left,
            right,
            selected_delta,
        )
        direct = measurements(rows)
        if direct["objective"] != selected_objective:
            raise ValueError("weighted score disagrees with full PAF")
        moves.append(
            {
                "row": row_index,
                "orbit_size": size,
                "negative_to_positive": left,
                "positive_to_negative": right,
                "objective_after": selected_objective,
            }
        )
        candidates_evaluated += len(candidates)
        if selected_objective < best_objective:
            best_objective = selected_objective
            best_rows = copy.deepcopy(rows)
    if rows != target["rows"]:
        raise ValueError("path endpoint mismatch")
    return {
        "source_sha256": source["sha256"],
        "target_sha256": target["sha256"],
        "steps": len(moves),
        "candidates_evaluated": candidates_evaluated,
        "moves": moves,
        "best_objective": best_objective,
        "best_rows": best_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    left = load_state(args.left)
    right = load_state(args.right)
    directions = [
        run_direction(left, right),
        run_direction(right, left),
    ]
    best_direction = min(
        directions, key=lambda item: item["best_objective"]
    )
    best = measurements(best_direction["best_rows"])
    document = {
        "schema": "frontiermath-lp333-id5-path-relink-result-v1",
        "status": "candidate" if best["objective"] == 0 else "nonterminal",
        "family_id": 5,
        "subgroup": list(SUBGROUP),
        "inputs": {
            "left": {
                "path": left["path"],
                "sha256": left["sha256"],
                "objective": left["measurements"]["objective"],
            },
            "right": {
                "path": right["path"],
                "sha256": right["sha256"],
                "objective": right["measurements"]["objective"],
            },
        },
        "mechanism": {
            "directions": [
                {
                    key: value
                    for key, value in direction.items()
                    if key != "best_rows"
                }
                for direction in directions
            ],
            "independent_shifts": 166,
            "weighted_shift_classes": 56,
            "shift_class_weights": {"1": 1, "3": 55},
            "full_paf_check_after_every_step": "PASS",
        },
        "best_objective": best["objective"],
        "best_l1_residual": best["l1"],
        "best_max_abs_residual": best["maximum"],
        "a_sequence": best_direction["best_rows"][0],
        "b_sequence": best_direction["best_rows"][1],
        "a_paf_independent": best["pafs"][0][1 : HALF + 1],
        "b_paf_independent": best["pafs"][1][1 : HALF + 1],
        "combined_residual_independent": best["residual"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "best_objective": best["objective"],
                "best_l1_residual": best["l1"],
                "best_max_abs_residual": best["maximum"],
                "directions": [
                    {
                        "steps": direction["steps"],
                        "candidates_evaluated": direction[
                            "candidates_evaluated"
                        ],
                        "best_objective": direction["best_objective"],
                    }
                    for direction in directions
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
