#!/usr/bin/env python3
"""Run pinned Kissat on the unrestricted prescribed-pq2 LP333 formula."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import run_lp333_kissat_sat_discovery as common


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("--formula-audit", required=True, type=Path)
    parser.add_argument("--kissat", required=True, type=Path)
    parser.add_argument("--kissat-repo", required=True, type=Path)
    parser.add_argument("--sat-control-cnf", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument("--preregistration-audit", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=7200.0)
    parser.add_argument("--max-memory-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--progress-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if min(args.max_seconds, args.progress_seconds) <= 0:
        raise ValueError("time limits must be positive")
    if not args.kissat.is_file() or not os.access(args.kissat, os.X_OK):
        raise ValueError("Kissat binary missing or not executable")

    metadata = json.loads(args.encoding_metadata.read_text())
    formula_audit = json.loads(args.formula_audit.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    formula = Path(metadata["cnf"]["path"])
    generator = Path(__file__).with_name(
        "generate_lp333_pq2_cnf.py"
    )
    common_generator = Path(__file__).with_name(
        "generate_lp333_symmetry_cnf.py"
    )
    kissat_version = subprocess.run(
        [str(args.kissat), "--version"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    binding_checks = {
        "metadata_status": metadata.get("status") == "generated",
        "metadata_schema": (
            metadata.get("schema")
            == "frontiermath-hadamard-lp333-pq2-cnf-v1"
        ),
        "identity_family": metadata.get("family_id") == 0,
        "unrestricted_scope": (
            "no nontrivial multiplier assumption"
            in metadata.get("scope", "")
        ),
        "generator_hash": (
            metadata["generator_sha256"]
            == common.sha256_file(generator)
        ),
        "common_generator_hash": (
            metadata["common_generator_sha256"]
            == common.sha256_file(common_generator)
        ),
        "formula_hash": (
            metadata["cnf"]["sha256"] == common.sha256_file(formula)
        ),
        "formula_audit": (
            formula_audit.get("status") == "pass"
            and formula_audit.get("formula_sha256")
            == metadata["cnf"]["sha256"]
        ),
        "pq2_channels_enabled": (
            metadata.get("pq2_compression_channels", {}).get("enabled")
            is True
        ),
        "pq2_compressed_rows": (
            metadata["pq2_compression_channels"]["compressed_rows"]
            == [[1, 11, -11], [1, -11, 11]]
        ),
        "pq2_symmetry_control": (
            metadata["controls"]["pq2_symmetry_action"]["result"]
            == "PASS"
        ),
        "counter_truth_table": (
            metadata["controls"]["sequential_cardinality_truth_table"][
                "result"
            ]
            == "PASS"
        ),
        "kissat_version": (
            kissat_version == common.EXPECTED_KISSAT_VERSION
        ),
        "kissat_hash": (
            common.sha256_file(args.kissat)
            == common.EXPECTED_KISSAT_SHA256
        ),
        "kissat_revision": (
            common.git_revision(args.kissat_repo)
            == common.EXPECTED_KISSAT_REVISION
        ),
        "sat_control_hash": (
            common.sha256_file(args.sat_control_cnf)
            == common.EXPECTED_SAT_CONTROL_SHA256
        ),
        "preregistration_schema": (
            preregistration.get("schema")
            == "computational-experiment-preregistration/v1"
        ),
        "preregistration_audit": (
            preregistration_audit.get("status") == "pass"
        ),
        "preregistered_identity_slice": (
            "ID0" in preregistration.get("evidence_unit", "")
            and "pq2" in preregistration.get("evidence_unit", "")
        ),
    }
    if not all(binding_checks.values()):
        raise ValueError(f"input binding failed: {binding_checks}")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    positive_log = args.output_dir / "positive-control-kissat.log"
    positive_model = args.output_dir / "positive-control.model"
    positive_solver = common.run_kissat(
        args.kissat,
        args.sat_control_cnf,
        positive_log,
        120,
        args.max_memory_bytes,
        args.progress_seconds,
        "positive-control",
    )
    if positive_solver["termination"] != "sat":
        raise ValueError("Kissat did not solve the SAT positive control")
    positive_extraction = common.extract_model(
        positive_log, positive_model
    )
    positive_variables, _ = common.formula_dimensions(
        args.sat_control_cnf
    )
    positive_assignments = common.parse_complete_model(
        positive_model, positive_variables
    )
    positive_cnf = common.stream_check_cnf(
        args.sat_control_cnf, positive_assignments
    )
    positive_control = {
        "status": "pass" if positive_cnf["satisfied"] else "fail",
        "solver": positive_solver,
        "model": positive_extraction,
        "cnf_check": positive_cnf,
    }
    if positive_control["status"] != "pass":
        raise ValueError("Kissat positive-control model failed CNF audit")

    target_log = args.output_dir / "lp333-pq2-kissat.log"
    target_model = args.output_dir / "lp333-pq2-kissat.model"
    target_solver = common.run_kissat(
        args.kissat,
        formula,
        target_log,
        args.max_seconds,
        args.max_memory_bytes,
        args.progress_seconds,
        "pq2-unrestricted",
    )
    model_extraction = None
    model_audit = None
    if target_solver["termination"] == "sat":
        model_extraction = common.extract_model(
            target_log, target_model
        )
        verifier = Path(__file__).with_name(
            "verify_lp333_pq2_model.py"
        )
        model_audit_path = args.output_dir / "model-audit.json"
        command = [
            sys.executable,
            str(verifier),
            str(args.encoding_metadata),
            str(target_model),
            "--cnf",
            str(formula),
            "--output",
            str(model_audit_path),
        ]
        verification = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        model_audit = {
            "command": command,
            "returncode": verification.returncode,
            "stdout_tail": verification.stdout[-4000:],
            "exists": model_audit_path.is_file(),
            "sha256": (
                common.sha256_file(model_audit_path)
                if model_audit_path.is_file()
                else None
            ),
            "result": (
                json.loads(model_audit_path.read_text())
                if model_audit_path.is_file()
                else None
            ),
        }
    directly_verified = bool(
        model_audit
        and model_audit["returncode"] == 0
        and model_audit["result"]["status"] == "pass"
    )
    if directly_verified:
        status = "directly-verified-sat"
    elif target_solver["termination"] == "sat":
        status = "sat-model-verification-failed"
    elif target_solver["termination"] == "unsat":
        status = "proofless-unsat-nonclaim"
    else:
        status = "unknown"
    verifier = Path(__file__).with_name("verify_lp333_pq2_model.py")
    base_verifier = Path(__file__).with_name(
        "verify_lp333_family_model.py"
    )
    manifest = {
        "schema": "frontiermath-hadamard-lp333-pq2-kissat-run-v1",
        "status": status,
        "family_id": 0,
        "scope": "unrestricted prescribed pq2-compression slice",
        "claim_boundary": (
            "Only directly-verified-sat decides this slice. A proofless "
            "UNSAT status is explicitly nondecisive."
        ),
        "binding_checks": binding_checks,
        "positive_control": positive_control,
        "solver": target_solver,
        "model_extraction": model_extraction,
        "model_audit": model_audit,
        "budgets": {
            "max_seconds": args.max_seconds,
            "max_memory_bytes": args.max_memory_bytes,
            "progress_seconds": args.progress_seconds,
        },
        "tools": {
            "kissat": {
                "path": str(args.kissat),
                "version": kissat_version,
                "sha256": common.sha256_file(args.kissat),
                "source_repo": str(args.kissat_repo),
                "source_revision": common.git_revision(
                    args.kissat_repo
                ),
            }
        },
        "inputs": {
            "encoding_metadata": str(args.encoding_metadata),
            "encoding_metadata_sha256": common.sha256_file(
                args.encoding_metadata
            ),
            "formula": str(formula),
            "formula_sha256": metadata["cnf"]["sha256"],
            "formula_audit": str(args.formula_audit),
            "formula_audit_sha256": common.sha256_file(
                args.formula_audit
            ),
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
            "sat_control_cnf": str(args.sat_control_cnf),
            "sat_control_cnf_sha256": (
                common.EXPECTED_SAT_CONTROL_SHA256
            ),
            "verifier_sha256": common.sha256_file(verifier),
            "base_verifier_sha256": common.sha256_file(base_verifier),
        },
        "runner_sha256": common.sha256_file(Path(__file__).resolve()),
        "shared_runner_sha256": common.sha256_file(
            Path(common.__file__).resolve()
        ),
    }
    manifest_path = args.output_dir / "run-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "status": status,
                "scope": manifest["scope"],
                "manifest_sha256": common.sha256_file(manifest_path),
                "solver": target_solver,
                "model_audit_status": (
                    model_audit["result"]["status"]
                    if model_audit and model_audit["result"]
                    else None
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if status != "sat-model-verification-failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
