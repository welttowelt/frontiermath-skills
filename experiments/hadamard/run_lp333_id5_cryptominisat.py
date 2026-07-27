#!/usr/bin/env python3
"""Run pinned CryptoMiniSat parity recovery on the exact LP333 ID5 CNF."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import run_lp333_kissat_sat_discovery as common
import run_lp333_pq2_cryptominisat as cms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("--formula-audit", required=True, type=Path)
    parser.add_argument("--cryptominisat", required=True, type=Path)
    parser.add_argument(
        "--cryptominisat-library", required=True, type=Path
    )
    parser.add_argument("--homebrew-receipt", required=True, type=Path)
    parser.add_argument("--sat-control-cnf", required=True, type=Path)
    parser.add_argument("--preregistration", required=True, type=Path)
    parser.add_argument(
        "--preregistration-audit", required=True, type=Path
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=3600.0)
    parser.add_argument(
        "--max-memory-bytes", type=int, default=4 * 1024**3
    )
    parser.add_argument("--progress-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if min(args.max_seconds, args.progress_seconds) <= 0:
        raise ValueError("time limits must be positive")
    if not args.cryptominisat.is_file() or not os.access(
        args.cryptominisat, os.X_OK
    ):
        raise ValueError("CryptoMiniSat binary missing or not executable")

    metadata = json.loads(args.encoding_metadata.read_text())
    formula_audit = json.loads(args.formula_audit.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    receipt = json.loads(args.homebrew_receipt.read_text())
    formula = Path(metadata["cnf"]["path"])
    version_output = subprocess.run(
        [str(args.cryptominisat), "--version"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    binding_checks = {
        "metadata_status": metadata.get("status") == "generated",
        "metadata_schema": (
            metadata.get("schema")
            == "frontiermath-hadamard-lp333-symmetry-cnf-v1"
        ),
        "family_id": metadata.get("family_id") == 5,
        "subgroup": (
            metadata.get("subgroup", {}).get("elements")
            == [1, 211, 232]
        ),
        "formula_hash": (
            metadata["cnf"]["sha256"]
            == common.sha256_file(formula)
        ),
        "formula_audit": (
            formula_audit.get("status") == "pass"
            and formula_audit.get("family_id") == 5
            and formula_audit.get("formula_sha256")
            == metadata["cnf"]["sha256"]
        ),
        "cryptominisat_version": (
            f"c CryptoMiniSat version {cms.EXPECTED_VERSION}"
            in version_output
        ),
        "cryptominisat_hash": (
            common.sha256_file(args.cryptominisat)
            == cms.EXPECTED_EXECUTABLE_SHA256
        ),
        "cryptominisat_library_hash": (
            common.sha256_file(args.cryptominisat_library)
            == cms.EXPECTED_LIBRARY_SHA256
        ),
        "homebrew_receipt_hash": (
            common.sha256_file(args.homebrew_receipt)
            == cms.EXPECTED_RECEIPT_SHA256
        ),
        "homebrew_bottle_install": (
            receipt.get("built_as_bottle") is True
            and receipt.get("poured_from_bottle") is True
            and receipt.get("source", {})
            .get("versions", {})
            .get("stable")
            == cms.EXPECTED_VERSION
        ),
        "sat_control_hash": (
            common.sha256_file(args.sat_control_cnf)
            == common.EXPECTED_SAT_CONTROL_SHA256
        ),
        "preregistration": (
            preregistration.get("schema")
            == "computational-experiment-preregistration/v1"
            and preregistration.get("name")
            == "LP333 ID5 CryptoMiniSat parity-recovery discovery"
            and preregistration_audit.get("status") == "pass"
        ),
    }
    if not all(binding_checks.values()):
        raise ValueError(f"input binding failed: {binding_checks}")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    positive_log = (
        args.output_dir / "positive-control-cryptominisat.log"
    )
    positive_model = args.output_dir / "positive-control.model"
    positive_solver = cms.run_cryptominisat(
        args.cryptominisat,
        args.sat_control_cnf,
        positive_log,
        120,
        args.max_memory_bytes,
        args.progress_seconds,
        "positive-control",
    )
    if positive_solver["termination"] != "sat":
        raise ValueError("CryptoMiniSat did not solve SAT control")
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
        "status": (
            "pass"
            if positive_cnf["satisfied"]
            and positive_solver["parity_trace"]["fired"]
            else "fail"
        ),
        "solver": positive_solver,
        "model": positive_extraction,
        "cnf_check": positive_cnf,
    }
    if positive_control["status"] != "pass":
        raise ValueError("positive-control audit failed")

    target_log = args.output_dir / "id5-cryptominisat.log"
    target_model = args.output_dir / "id5-cryptominisat.model"
    target_solver = cms.run_cryptominisat(
        args.cryptominisat,
        formula,
        target_log,
        args.max_seconds,
        args.max_memory_bytes,
        args.progress_seconds,
        "id5-parity-recovery",
    )
    model_extraction = None
    model_audit = None
    if target_solver["termination"] == "sat":
        model_extraction = common.extract_model(
            target_log, target_model
        )
        verifier = Path(__file__).with_name(
            "verify_lp333_family_model.py"
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
    parity_fired = target_solver["parity_trace"]["fired"]
    if directly_verified:
        status = "directly-verified-sat"
    elif target_solver["termination"] == "sat":
        status = "sat-model-verification-failed"
    elif not parity_fired:
        status = "audit-failed-parity-not-fired"
    elif target_solver["termination"] == "unsat":
        status = "proofless-unsat-nonclaim"
    else:
        status = "unknown"

    verifier = Path(__file__).with_name(
        "verify_lp333_family_model.py"
    )
    manifest = {
        "schema": (
            "frontiermath-hadamard-lp333-id5-"
            "cryptominisat-run-v1"
        ),
        "status": status,
        "family_id": 5,
        "scope": "fixed multiplier subgroup {1,211,232}",
        "claim_boundary": (
            "Only directly-verified-sat decides ID5. XOR/Gauss "
            "telemetry and proofless UNSAT are nondecisive."
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
        },
        "tools": {
            "cryptominisat": {
                "path": str(args.cryptominisat),
                "version": cms.EXPECTED_VERSION,
                "version_output": version_output,
                "executable_sha256": common.sha256_file(
                    args.cryptominisat
                ),
                "library": str(args.cryptominisat_library),
                "library_sha256": common.sha256_file(
                    args.cryptominisat_library
                ),
                "homebrew_receipt": str(args.homebrew_receipt),
                "homebrew_receipt_sha256": common.sha256_file(
                    args.homebrew_receipt
                ),
                "homebrew_bottle_sha256": (
                    cms.EXPECTED_BOTTLE_SHA256
                ),
            }
        },
        "runner_sha256": common.sha256_file(
            Path(__file__).resolve()
        ),
        "parity_runner_sha256": common.sha256_file(
            Path(cms.__file__).resolve()
        ),
        "shared_runner_sha256": common.sha256_file(
            Path(common.__file__).resolve()
        ),
    }
    manifest_path = args.output_dir / "run-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(manifest, sort_keys=True))
    if status == "directly-verified-sat":
        return 0
    if status in {"unknown", "proofless-unsat-nonclaim"}:
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
