#!/usr/bin/env python3
"""Independently audit an LP333 ID5 weighted-shift tabu endpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_lp333_id5_orbit_tabu import (
    HALF,
    SUBGROUP,
    mutation_control,
    pair_measurements,
    sha256_file,
)


EXPECTED_SOURCE_SHA256 = (
    "13cb66830fc984f1024d0ca54034ee5ba3fe15a46f98b593bf907e558dc38575"
)
EXPECTED_BASELINE_SHA256 = (
    "7a3bf72d06023658850d9e95ebc4d4eb0b3ba885da6d748a78abd5c297df486d"
)
EXPECTED_BINARY_SHA256 = (
    "a92acc7743d1eb6ccf1eb7f051ece0ab0024ffa91b3504c90a7f9499144b6992"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--mechanism", required=True, type=Path)
    parser.add_argument("--start", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument(
        "--preregistration-audit", required=True, type=Path
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    result = json.loads(args.result.read_text())
    mechanism = json.loads(args.mechanism.read_text())
    start = json.loads(args.start.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    measured = pair_measurements(result)
    start_measured = pair_measurements(start)
    candidate = measured["objective"] == 0
    mutation = mutation_control(measured["a"], measured["a_paf"])
    profiles = (measured["a_profile"], measured["b_profile"])

    shift_classes: dict[tuple[int, ...], list[int]] = {}
    for shift in range(1, HALF + 1):
        orbit = tuple(
            sorted(
                {
                    min(
                        (shift * unit) % 333,
                        333 - ((shift * unit) % 333),
                    )
                    for unit in SUBGROUP
                }
            )
        )
        shift_classes.setdefault(orbit, []).append(shift)
    shift_weights = sorted(len(orbit) for orbit in shift_classes)
    weighted_objective = 0
    for orbit in shift_classes:
        representative = orbit[0]
        residual = measured["residual"][representative - 1]
        weighted_objective += len(orbit) * residual * residual

    checks = {
        "result_schema": (
            result.get("schema")
            == (
                "frontiermath-lp333-id5-weighted-shift-"
                "tabu-result-v1"
            )
        ),
        "family_and_subgroup": (
            result.get("family_id") == 5
            and result.get("subgroup") == list(SUBGROUP)
        ),
        "binary_length_333_rows": measured["domains"],
        "row_sums_one": all(
            profile["row_sum"] == 1 for profile in profiles
        ),
        "id5_invariance": all(
            profile["invariant"] for profile in profiles
        ),
        "forced_orbit_margins": all(
            profile["negative_singletons"] == 1
            and profile["negative_triples"] == 55
            for profile in profiles
        ),
        "stored_a_paf": (
            result.get("a_paf_independent")
            == measured["a_paf"][1 : HALF + 1]
        ),
        "stored_b_paf": (
            result.get("b_paf_independent")
            == measured["b_paf"][1 : HALF + 1]
        ),
        "stored_residual": (
            result.get("combined_residual_independent")
            == measured["residual"]
        ),
        "stored_objective": (
            result.get("best_objective") == measured["objective"]
        ),
        "weighted_objective_is_exact": (
            weighted_objective == measured["objective"]
        ),
        "stored_l1": (
            result.get("best_l1_residual") == measured["l1"]
        ),
        "stored_maximum": (
            result.get("best_max_abs_residual")
            == measured["maximum"]
        ),
        "status_matches_candidate": (
            result.get("status")
            == ("candidate" if candidate else "nonterminal")
        ),
        "full_paf_symmetry": all(
            measured["a_paf"][shift]
            == measured["a_paf"][333 - shift]
            and measured["b_paf"][shift]
            == measured["b_paf"][333 - shift]
            for shift in range(1, 333)
        ),
        "start_state_is_id5": (
            start_measured["a_profile"]["invariant"]
            and start_measured["b_profile"]["invariant"]
            and start_measured["a_profile"]["row_sum"] == 1
            and start_measured["b_profile"]["row_sum"] == 1
        ),
        "start_objective_reconstructed": (
            mechanism.get("start_objective")
            == start_measured["objective"]
        ),
        "best_not_worse_than_start": (
            measured["objective"] <= start_measured["objective"]
        ),
        "shift_partition_reconstructed": (
            len(shift_classes) == 56
            and shift_weights.count(1) == 1
            and shift_weights.count(3) == 55
            and sum(shift_weights) == HALF
        ),
        "mechanism_schema": (
            mechanism.get("schema")
            == "frontiermath-lp333-id5-weighted-shift-tabu-v1"
        ),
        "weighted_full_neighborhood_mechanism": (
            mechanism.get("independent_shifts") == 166
            and mechanism.get("weighted_shift_classes") == 56
            and mechanism.get("shift_class_weights")
            == {"1": 1, "3": 55}
            and mechanism.get("legal_neighbors_per_state") == 6054
            and mechanism.get("full_neighborhood_sweeps")
            == mechanism.get("applied_moves")
            and mechanism.get("tabu_tenure_min") == 7
            and mechanism.get("tabu_tenure_max") == 14
            and mechanism.get("stagnation_restart_sweeps") == 5000
            and mechanism.get("perturbation_moves") == 64
            and mechanism.get(
                "complete_weighted_neighborhood_self_test"
            )
            == "PASS"
        ),
        "source_pin": (
            sha256_file(args.source) == EXPECTED_SOURCE_SHA256
        ),
        "baseline_pin": (
            sha256_file(args.baseline) == EXPECTED_BASELINE_SHA256
        ),
        "binary_pin": (
            sha256_file(args.binary) == EXPECTED_BINARY_SHA256
        ),
        "preregistration_schema": (
            preregistration.get("schema")
            == "computational-experiment-preregistration/v1"
        ),
        "preregistration_audit": (
            preregistration_audit.get("status") == "pass"
        ),
        "mutation_preserves_slice_and_changes_paf": (
            mutation["preserves_id5_invariance"]
            and mutation["preserves_row_sum"]
            and mutation["changes_full_paf"]
        ),
    }
    status = "pass" if all(checks.values()) else "fail"
    document = {
        "schema": (
            "frontiermath-lp333-id5-weighted-shift-"
            "tabu-audit-v1"
        ),
        "status": status,
        "candidate": candidate and status == "pass",
        "checks": checks,
        "measurements": {
            "objective": measured["objective"],
            "weighted_objective": weighted_objective,
            "l1_residual": measured["l1"],
            "maximum_absolute_residual": measured["maximum"],
            "shift_classes": len(shift_classes),
            "shift_weight_histogram": {
                "1": shift_weights.count(1),
                "3": shift_weights.count(3),
            },
            "a_profile": measured["a_profile"],
            "b_profile": measured["b_profile"],
        },
        "mutation_control": mutation,
        "artifact_hashes": {
            "result_sha256": sha256_file(args.result),
            "mechanism_sha256": sha256_file(args.mechanism),
            "start_sha256": sha256_file(args.start),
            "source_sha256": sha256_file(args.source),
            "baseline_sha256": sha256_file(args.baseline),
            "binary_sha256": sha256_file(args.binary),
            "preregistration_sha256": sha256_file(
                args.preregistration
            ),
            "preregistration_audit_sha256": sha256_file(
                args.preregistration_audit
            ),
        },
        "claim_boundary": (
            "Only candidate=true after every independent check passes "
            "is a Legendre-pair candidate. A nonzero endpoint closes "
            "no family."
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
