#!/usr/bin/env python3
"""Independently audit an LP333 ID5 double-orbit anneal endpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import audit_lp333_id5_orbit_anneal as common


EXPECTED_SOURCE_SHA256 = (
    "4f289cdc21bc8fd1758bd585b2f338fb56c415c0d7bc84d9bc95a3e90459f2ac"
)
EXPECTED_BASELINE_SHA256 = (
    "7a3bf72d06023658850d9e95ebc4d4eb0b3ba885da6d748a78abd5c297df486d"
)
EXPECTED_BINARY_SHA256 = (
    "4996b99299e8a556959b71856df96da92944c87888d68c76e1a72606c0a48a1a"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
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
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    a = result.get("a_sequence")
    b = result.get("b_sequence")
    domains = (
        isinstance(a, list)
        and isinstance(b, list)
        and len(a) == common.LENGTH
        and len(b) == common.LENGTH
        and set(a) <= {-1, 1}
        and set(b) <= {-1, 1}
    )
    if not domains:
        raise ValueError("result lacks two binary length-333 rows")
    a_paf = common.paf(a)
    b_paf = common.paf(b)
    residual = [
        a_paf[shift] + b_paf[shift] + 2
        for shift in range(1, common.HALF + 1)
    ]
    objective = sum(value * value for value in residual)
    l1 = sum(abs(value) for value in residual)
    maximum = max(map(abs, residual))
    candidate = objective == 0
    a_profile = common.invariance_profile(a)
    b_profile = common.invariance_profile(b)
    mutation = common.mutation_control(a, a_paf)
    profiles = (a_profile, b_profile)
    iterations = result.get("iterations")
    double_proposals = result.get("double_triple_proposals")

    checks = {
        "result_schema": (
            result.get("schema")
            == "frontiermath-lp333-id5-double-orbit-anneal-result-v1"
        ),
        "family_and_subgroup": (
            result.get("family_id") == 5
            and result.get("subgroup") == list(common.SUBGROUP)
        ),
        "binary_length_333_rows": domains,
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
            == a_paf[1 : common.HALF + 1]
        ),
        "stored_b_paf": (
            result.get("b_paf_independent")
            == b_paf[1 : common.HALF + 1]
        ),
        "stored_residual": (
            result.get("combined_residual_independent") == residual
        ),
        "stored_objective": (
            result.get("best_objective") == objective
        ),
        "stored_l1": result.get("best_l1_residual") == l1,
        "stored_maximum": (
            result.get("best_max_abs_residual") == maximum
        ),
        "status_matches_candidate": (
            result.get("status")
            == ("candidate" if candidate else "nonterminal")
        ),
        "full_paf_symmetry": all(
            a_paf[shift] == a_paf[common.LENGTH - shift]
            and b_paf[shift] == b_paf[common.LENGTH - shift]
            for shift in range(1, common.LENGTH)
        ),
        "double_neighborhood_fired": (
            isinstance(iterations, int)
            and isinstance(double_proposals, int)
            and 0 < double_proposals < iterations
            and result.get("incremental_self_test") == "PASS"
            and result.get("incremental_self_test_trials") == 2000
        ),
        "source_pin": (
            common.sha256_file(args.source)
            == EXPECTED_SOURCE_SHA256
        ),
        "baseline_pin": (
            common.sha256_file(args.baseline)
            == EXPECTED_BASELINE_SHA256
        ),
        "binary_pin": (
            common.sha256_file(args.binary)
            == EXPECTED_BINARY_SHA256
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
            "frontiermath-lp333-id5-double-orbit-anneal-audit-v1"
        ),
        "status": status,
        "family_id": 5,
        "candidate": candidate,
        "objective": objective,
        "l1_residual": l1,
        "maximum_absolute_residual": maximum,
        "a_profile": a_profile,
        "b_profile": b_profile,
        "double_triple_proposals": double_proposals,
        "mutation_control": mutation,
        "checks": checks,
        "inputs": {
            "result": str(args.result),
            "result_sha256": common.sha256_file(args.result),
            "source": str(args.source),
            "source_sha256": common.sha256_file(args.source),
            "baseline": str(args.baseline),
            "baseline_sha256": common.sha256_file(args.baseline),
            "binary": str(args.binary),
            "binary_sha256": common.sha256_file(args.binary),
            "preregistration": str(args.preregistration),
            "preregistration_sha256": common.sha256_file(
                args.preregistration
            ),
            "preregistration_audit": str(
                args.preregistration_audit
            ),
            "preregistration_audit_sha256": common.sha256_file(
                args.preregistration_audit
            ),
            "auditor_sha256": common.sha256_file(
                Path(__file__).resolve()
            ),
        },
    }
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
