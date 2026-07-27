#!/usr/bin/env python3
"""Bind the matched ID9/ID10 proof calibration into one result record."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id9-encoding", required=True, type=Path)
    parser.add_argument("--id9-audit", required=True, type=Path)
    parser.add_argument("--id9-run", required=True, type=Path)
    parser.add_argument("--id10-encoding", required=True, type=Path)
    parser.add_argument("--id10-audit", required=True, type=Path)
    parser.add_argument("--id10-run", required=True, type=Path)
    parser.add_argument("--id10-run-audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    encodings = {
        9: load(args.id9_encoding),
        10: load(args.id10_encoding),
    }
    audits = {
        9: load(args.id9_audit),
        10: load(args.id10_audit),
    }
    runs = {
        9: load(args.id9_run),
        10: load(args.id10_run),
    }
    run_audit = load(args.id10_run_audit)
    checks = {
        "family_ids": all(
            encodings[family]["family_id"] == family
            and audits[family]["family_id"] == family
            and runs[family]["family_id"] == family
            for family in (9, 10)
        ),
        "formula_audits_pass": all(
            audits[family]["status"] == "pass"
            and all(audits[family]["checks"].values())
            for family in (9, 10)
        ),
        "matched_formula_size": (
            encodings[9]["cnf"]["variables"]
            == encodings[10]["cnf"]["variables"]
            and encodings[9]["cnf"]["clauses"]
            == encodings[10]["cnf"]["clauses"]
            and encodings[9]["cnf"]["bytes"]
            == encodings[10]["cnf"]["bytes"]
        ),
        "matched_budgets": runs[9]["budgets"] == runs[10]["budgets"],
        "both_bogus_controls_rejected": all(
            runs[family]["bogus_proof_control"]["rejected"]
            for family in (9, 10)
        ),
        "id9_unknown_at_proof_ceiling": (
            runs[9]["status"] == "unknown-resource-ceiling"
            and runs[9]["solver"]["termination"] == "proof-size-ceiling"
        ),
        "id10_proof_certified": (
            runs[10]["status"] == "proof-certified-unsat"
            and runs[10]["solver"]["termination"] == "unsat"
            and runs[10]["proof_replay"]["accepted"]
        ),
        "id10_independent_run_audit": (
            run_audit["status"] == "pass"
            and run_audit["family_id"] == 10
            and all(run_audit["checks"].values())
        ),
    }
    status = "id10-proof-certified" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-hadamard-lp333-twin-calibration-v1",
        "status": status,
        "claim": (
            "Fixed common-multiplier family ID10 is proof-certified "
            "infeasible. ID9 remains UNKNOWN at the matched proof ceiling."
        ),
        "claim_boundary": (
            "Through the separately audited affine-normalization result, "
            "ID10's coherent translated versions are also excluded. This "
            "does not decide ID9, the other seven open fixed families, "
            "unrestricted LP(333), or H(668)."
        ),
        "checks": checks,
        "formula": {
            "variables_each": encodings[9]["cnf"]["variables"],
            "clauses_each": encodings[9]["cnf"]["clauses"],
            "bytes_each": encodings[9]["cnf"]["bytes"],
            "id9_sha256": encodings[9]["cnf"]["sha256"],
            "id10_sha256": encodings[10]["cnf"]["sha256"],
        },
        "id9": {
            "status": runs[9]["status"],
            "termination": runs[9]["solver"]["termination"],
            "wall_seconds": runs[9]["solver"]["wall_seconds"],
            "proof_bytes": runs[9]["solver"]["proof"]["bytes"],
            "proof_sha256": runs[9]["solver"]["proof"]["sha256"],
            "maximum_observed_rss_bytes": runs[9]["solver"][
                "maximum_observed_rss_bytes"
            ],
        },
        "id10": {
            "status": runs[10]["status"],
            "termination": runs[10]["solver"]["termination"],
            "solver_wall_seconds": runs[10]["solver"]["wall_seconds"],
            "proof_bytes": runs[10]["solver"]["proof"]["bytes"],
            "proof_sha256": runs[10]["solver"]["proof"]["sha256"],
            "first_replay_seconds": runs[10]["proof_replay"]["wall_seconds"],
            "fresh_replay_seconds": run_audit["fresh_replay"]["wall_seconds"],
            "maximum_observed_rss_bytes": runs[10]["solver"][
                "maximum_observed_rss_bytes"
            ],
        },
        "open_fixed_family_ids_after_result": [0, 1, 2, 3, 4, 5, 7, 9],
        "inputs": {
            "id9_encoding_sha256": sha256_file(args.id9_encoding),
            "id9_audit_sha256": sha256_file(args.id9_audit),
            "id9_run_sha256": sha256_file(args.id9_run),
            "id10_encoding_sha256": sha256_file(args.id10_encoding),
            "id10_audit_sha256": sha256_file(args.id10_audit),
            "id10_run_sha256": sha256_file(args.id10_run),
            "id10_run_audit_sha256": sha256_file(args.id10_run_audit),
        },
        "source_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if status == "id10-proof-certified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
