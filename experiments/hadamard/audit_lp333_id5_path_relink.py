#!/usr/bin/env python3
"""Independently replay and audit an LP333 ID5 path-relink result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audit_lp333_id5_orbit_tabu import (
    HALF,
    SUBGROUP,
    orbits,
    pair_measurements,
    sha256_file,
)


def rows(document: dict[str, Any]) -> list[list[int]]:
    return [document["a_sequence"], document["b_sequence"]]


def replay_direction(
    source: dict[str, Any],
    target: dict[str, Any],
    direction: dict[str, Any],
) -> dict[str, Any]:
    orbit_list = orbits()
    current = [list(row) for row in rows(source)]
    target_rows = rows(target)
    best_objective = pair_measurements(source)["objective"]
    best_states = [[list(row) for row in current]]
    legal = True
    objectives_match = True
    target_reducing = True
    for move in direction["moves"]:
        row = move["row"]
        left = move["negative_to_positive"]
        right = move["positive_to_negative"]
        legal &= (
            row in (0, 1)
            and 0 <= left < len(orbit_list)
            and 0 <= right < len(orbit_list)
            and len(orbit_list[left]) == move["orbit_size"]
            and len(orbit_list[right]) == move["orbit_size"]
            and current[row][orbit_list[left][0]] == -1
            and current[row][orbit_list[right][0]] == 1
        )
        target_reducing &= (
            target_rows[row][orbit_list[left][0]] == 1
            and target_rows[row][orbit_list[right][0]] == -1
        )
        for orbit_id in (left, right):
            for index in orbit_list[orbit_id]:
                current[row][index] *= -1
        objective = pair_measurements(
            {"a_sequence": current[0], "b_sequence": current[1]}
        )["objective"]
        objectives_match &= objective == move["objective_after"]
        if objective < best_objective:
            best_objective = objective
            best_states = [[list(row) for row in current]]
        elif objective == best_objective:
            best_states.append([list(row) for row in current])
    return {
        "legal_moves": legal,
        "target_reducing": target_reducing,
        "objectives_match": objectives_match,
        "reaches_target": current == target_rows,
        "steps_match": len(direction["moves"]) == direction["steps"],
        "best_objective": best_objective,
        "best_states": best_states,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument(
        "--preregistration-audit", required=True, type=Path
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = json.loads(args.result.read_text())
    left = json.loads(args.left.read_text())
    right = json.loads(args.right.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    measured = pair_measurements(result)
    directions = result["mechanism"]["directions"]
    replayed = [
        replay_direction(left, right, directions[0]),
        replay_direction(right, left, directions[1]),
    ]
    best_objective = min(item["best_objective"] for item in replayed)
    best_rows = [
        state
        for item in replayed
        if item["best_objective"] == best_objective
        for state in item["best_states"]
    ]
    candidate = measured["objective"] == 0
    profiles = (measured["a_profile"], measured["b_profile"])
    checks = {
        "schema": (
            result.get("schema")
            == "frontiermath-lp333-id5-path-relink-result-v1"
        ),
        "family_and_subgroup": (
            result.get("family_id") == 5
            and result.get("subgroup") == list(SUBGROUP)
        ),
        "input_hashes": (
            result["inputs"]["left"]["sha256"]
            == sha256_file(args.left)
            and result["inputs"]["right"]["sha256"]
            == sha256_file(args.right)
        ),
        "two_directions_replayed": (
            len(replayed) == 2
            and all(
                item["legal_moves"]
                and item["target_reducing"]
                and item["objectives_match"]
                and item["reaches_target"]
                and item["steps_match"]
                for item in replayed
            )
        ),
        "best_path_state_reproduced": (
            measured["objective"] == best_objective
            and rows(result) in best_rows
        ),
        "binary_rows": measured["domains"],
        "id5_invariance_and_margins": all(
            profile["invariant"]
            and profile["row_sum"] == 1
            and profile["negative_singletons"] == 1
            and profile["negative_triples"] == 55
            for profile in profiles
        ),
        "stored_pafs": (
            result.get("a_paf_independent")
            == measured["a_paf"][1 : HALF + 1]
            and result.get("b_paf_independent")
            == measured["b_paf"][1 : HALF + 1]
        ),
        "stored_residual_and_scores": (
            result.get("combined_residual_independent")
            == measured["residual"]
            and result.get("best_objective") == measured["objective"]
            and result.get("best_l1_residual") == measured["l1"]
            and result.get("best_max_abs_residual")
            == measured["maximum"]
        ),
        "status_matches_candidate": (
            result.get("status")
            == ("candidate" if candidate else "nonterminal")
        ),
        "weighted_partition_telemetry": (
            result["mechanism"].get("independent_shifts") == 166
            and result["mechanism"].get("weighted_shift_classes") == 56
            and result["mechanism"].get("shift_class_weights")
            == {"1": 1, "3": 55}
            and result["mechanism"].get(
                "full_paf_check_after_every_step"
            )
            == "PASS"
        ),
        "source_pin": (
            sha256_file(args.source)
            == preregistration["controls"][-1]["expected"].split(
                "source SHA-256 "
            )[1].split(",")[0]
        ),
        "preregistration": (
            preregistration.get("schema")
            == "computational-experiment-preregistration/v1"
            and preregistration_audit.get("status") == "pass"
        ),
    }
    status = "pass" if all(checks.values()) else "fail"
    document = {
        "schema": "frontiermath-lp333-id5-path-relink-audit-v1",
        "status": status,
        "candidate": candidate and status == "pass",
        "checks": checks,
        "objective": measured["objective"],
        "l1_residual": measured["l1"],
        "maximum_absolute_residual": measured["maximum"],
        "replayed_directions": [
            {
                key: value
                for key, value in item.items()
                if key != "best_states"
            }
            for item in replayed
        ],
        "inputs": {
            "result_sha256": sha256_file(args.result),
            "left_sha256": sha256_file(args.left),
            "right_sha256": sha256_file(args.right),
            "source_sha256": sha256_file(args.source),
            "preregistration_sha256": sha256_file(
                args.preregistration
            ),
            "preregistration_audit_sha256": sha256_file(
                args.preregistration_audit
            ),
        },
        "claim_boundary": (
            "Only candidate=true after every independent replay and "
            "full PAF check passes is a Legendre-pair candidate."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(document, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
