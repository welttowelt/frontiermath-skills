#!/usr/bin/env python3
"""Run pinned CryptoMiniSat parity recovery on the unrestricted pq2 CNF."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

import run_lp333_kissat_sat_discovery as common


EXPECTED_VERSION = "5.14.7"
EXPECTED_EXECUTABLE_SHA256 = (
    "a3f85c3709b5e2a040bf82a4a604d1c7b9f10219bbf180a9e0f72319a2e892ac"
)
EXPECTED_LIBRARY_SHA256 = (
    "7952e5a5c77ac8b56253c7a2ad88c62648f20698004338bad9a443efb55b2f84"
)
EXPECTED_RECEIPT_SHA256 = (
    "0309c0559340b1a766058556fad6691da0a97983d7a1195dcd4b7236f1ab33a3"
)
EXPECTED_BOTTLE_SHA256 = (
    "7793bdca8de1ecaf72fd743f85fe381db98d4d48012b24eeeaa6cb0daa7ed41d"
)
PARITY_ARGUMENTS = [
    "--threads=1",
    "--random=0",
    "--xor=1",
    "--maxxorsize=7",
    "--xorfindtout=400",
    "--maxxormat=400",
    "--maxmatrixrows=2000",
    "--maxmatrixcols=1000",
    "--autodisablegauss=1",
    "--minmatrixrows=3",
    "--maxnummatrices=5",
    "--gaussusefulcutoff=0.2",
    "--verb=1",
    "--printsol=1",
]


def parity_trace(text: str) -> dict[str, Any]:
    found = [
        int(match.group(1))
        for match in re.finditer(
            r"^\s*c \[occ-xor\] found\s+([0-9]+)\b",
            text,
            re.MULTILINE,
        )
    ]
    used = [
        (int(match.group(1)), int(match.group(2)))
        for match in re.finditer(
            r"^\s*c \[matrix\] Using\s+([0-9]+) matrices recovered "
            r"from\s+([0-9]+) xors\b",
            text,
            re.MULTILINE,
        )
    ]
    return {
        "xor_recovery_reports": found,
        "matrix_use_reports": [
            {"matrices": matrices, "recovered_xors": xors}
            for matrices, xors in used
        ],
        "recovered_xors": max(found, default=0),
        "used_matrices": max(
            (matrices for matrices, _ in used), default=0
        ),
        "fired": bool(
            found
            and used
            and max(found) > 0
            and max(matrices for matrices, _ in used) > 0
        ),
    }


def run_cryptominisat(
    executable: Path,
    formula: Path,
    log_path: Path,
    max_seconds: float,
    max_memory_bytes: int,
    progress_seconds: float,
    label: str,
) -> dict[str, Any]:
    command = [
        str(executable),
        *PARITY_ARGUMENTS,
        f"--maxtime={math.ceil(max_seconds)}",
        str(formula),
    ]
    started = time.perf_counter()
    termination = None
    maximum_observed_rss = 0
    next_progress = progress_seconds
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        while process.poll() is None:
            time.sleep(min(0.5, progress_seconds))
            elapsed = time.perf_counter() - started
            rss = common.process_rss_bytes(process.pid)
            if rss is not None:
                maximum_observed_rss = max(
                    maximum_observed_rss, rss
                )
            if rss is not None and rss > max_memory_bytes:
                termination = "memory-ceiling"
                common.terminate_process(process)
                break
            if elapsed > max_seconds + 15:
                termination = "external-wall-ceiling"
                common.terminate_process(process)
                break
            if elapsed >= next_progress:
                print(
                    json.dumps(
                        {
                            "elapsed_seconds": round(elapsed, 1),
                            "label": label,
                            "rss_bytes": rss,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                next_progress += progress_seconds
        returncode = process.wait()
    wall_seconds = time.perf_counter() - started
    text = log_path.read_text(encoding="ascii", errors="replace")
    if termination is None:
        if returncode == 10 or common.exact_marker(
            text, "s SATISFIABLE"
        ):
            termination = "sat"
        elif returncode == 20 or common.exact_marker(
            text, "s UNSATISFIABLE"
        ):
            termination = "unsat"
        else:
            termination = "solver-ceiling-or-error"
    selected_statistics = {}
    for key, pattern in {
        "conflicts": r"^c conflicts\s+:\s+([0-9]+)",
        "decisions": r"^c decisions\s+:\s+([0-9]+)",
        "propagations": r"^c propagations\s+:\s+([0-9]+[KMG]?)",
        "solver_reported_seconds": (
            r"^c Total time \(this thread\)\s+:\s+([0-9.]+)"
        ),
    }.items():
        matches = re.findall(pattern, text, re.MULTILINE)
        selected_statistics[key] = matches[-1] if matches else None
    return {
        "command": command,
        "returncode": returncode,
        "termination": termination,
        "wall_seconds": wall_seconds,
        "maximum_observed_rss_bytes": maximum_observed_rss,
        "log_sha256": common.sha256_file(log_path),
        "parity_trace": parity_trace(text),
        "statistics": selected_statistics,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("--formula-audit", required=True, type=Path)
    parser.add_argument(
        "--cryptominisat", required=True, type=Path
    )
    parser.add_argument(
        "--cryptominisat-library", required=True, type=Path
    )
    parser.add_argument(
        "--homebrew-receipt", required=True, type=Path
    )
    parser.add_argument("--sat-control-cnf", required=True, type=Path)
    parser.add_argument(
        "--preregistration", required=True, type=Path
    )
    parser.add_argument(
        "--preregistration-audit", required=True, type=Path
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=7200.0)
    parser.add_argument(
        "--max-memory-bytes", type=int, default=4 * 1024**3
    )
    parser.add_argument(
        "--progress-seconds", type=float, default=60.0
    )
    args = parser.parse_args()
    if min(args.max_seconds, args.progress_seconds) <= 0:
        raise ValueError("time limits must be positive")
    if not args.cryptominisat.is_file() or not os.access(
        args.cryptominisat, os.X_OK
    ):
        raise ValueError(
            "CryptoMiniSat binary missing or not executable"
        )

    metadata = json.loads(args.encoding_metadata.read_text())
    formula_audit = json.loads(args.formula_audit.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    receipt = json.loads(args.homebrew_receipt.read_text())
    formula = Path(metadata["cnf"]["path"])
    generator = Path(__file__).with_name(
        "generate_lp333_pq2_cnf.py"
    )
    common_generator = Path(__file__).with_name(
        "generate_lp333_symmetry_cnf.py"
    )
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
            metadata["cnf"]["sha256"]
            == common.sha256_file(formula)
        ),
        "formula_audit": (
            formula_audit.get("status") == "pass"
            and formula_audit.get("formula_sha256")
            == metadata["cnf"]["sha256"]
        ),
        "pq2_channels_enabled": (
            metadata.get("pq2_compression_channels", {}).get(
                "enabled"
            )
            is True
        ),
        "pq2_seed_identity": (
            metadata["pq2_compression_channels"][
                "compressed_length"
            ]
            == 37
            and metadata["pq2_compression_channels"][
                "compression_factor"
            ]
            == 9
            and metadata["controls"]["compressed_seed_identity"][
                "result"
            ]
            == "PASS"
        ),
        "pq2_symmetry_control": (
            metadata["controls"]["pq2_symmetry_action"]["result"]
            == "PASS"
        ),
        "cryptominisat_version": (
            f"c CryptoMiniSat version {EXPECTED_VERSION}"
            in version_output
        ),
        "cryptominisat_hash": (
            common.sha256_file(args.cryptominisat)
            == EXPECTED_EXECUTABLE_SHA256
        ),
        "cryptominisat_library_hash": (
            common.sha256_file(args.cryptominisat_library)
            == EXPECTED_LIBRARY_SHA256
        ),
        "homebrew_receipt_hash": (
            common.sha256_file(args.homebrew_receipt)
            == EXPECTED_RECEIPT_SHA256
        ),
        "homebrew_bottle_install": (
            receipt.get("built_as_bottle") is True
            and receipt.get("poured_from_bottle") is True
            and receipt.get("source", {})
            .get("versions", {})
            .get("stable")
            == EXPECTED_VERSION
        ),
        "sat_control_hash": (
            common.sha256_file(args.sat_control_cnf)
            == common.EXPECTED_SAT_CONTROL_SHA256
        ),
        "preregistration_schema": (
            preregistration.get("schema")
            == "computational-experiment-preregistration/v1"
        ),
        "preregistration_name": (
            preregistration.get("name")
            == (
                "Unrestricted LP333 pq2 CryptoMiniSat "
                "parity-recovery discovery"
            )
        ),
        "preregistration_audit": (
            preregistration_audit.get("status") == "pass"
        ),
    }
    if not all(binding_checks.values()):
        raise ValueError(f"input binding failed: {binding_checks}")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    positive_log = (
        args.output_dir / "positive-control-cryptominisat.log"
    )
    positive_model = args.output_dir / "positive-control.model"
    positive_solver = run_cryptominisat(
        args.cryptominisat,
        args.sat_control_cnf,
        positive_log,
        120,
        args.max_memory_bytes,
        args.progress_seconds,
        "positive-control",
    )
    if positive_solver["termination"] != "sat":
        raise ValueError(
            "CryptoMiniSat did not solve the SAT positive control"
        )
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
        raise ValueError(
            "CryptoMiniSat positive-control audit or parity trace failed"
        )

    target_log = args.output_dir / "lp333-pq2-cryptominisat.log"
    target_model = (
        args.output_dir / "lp333-pq2-cryptominisat.model"
    )
    target_solver = run_cryptominisat(
        args.cryptominisat,
        formula,
        target_log,
        args.max_seconds,
        args.max_memory_bytes,
        args.progress_seconds,
        "pq2-parity-recovery",
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
        "verify_lp333_pq2_model.py"
    )
    base_verifier = Path(__file__).with_name(
        "verify_lp333_family_model.py"
    )
    manifest = {
        "schema": (
            "frontiermath-hadamard-lp333-pq2-"
            "cryptominisat-run-v1"
        ),
        "status": status,
        "family_id": 0,
        "scope": "unrestricted prescribed pq2-compression slice",
        "claim_boundary": (
            "Only directly-verified-sat decides this slice. XOR/Gauss "
            "telemetry and proofless UNSAT are explicitly nondecisive."
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
            "cryptominisat": {
                "path": str(args.cryptominisat),
                "version": EXPECTED_VERSION,
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
                    EXPECTED_BOTTLE_SHA256
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
            "base_verifier_sha256": common.sha256_file(
                base_verifier
            ),
        },
        "runner_sha256": common.sha256_file(
            Path(__file__).resolve()
        ),
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
                "manifest_sha256": common.sha256_file(
                    manifest_path
                ),
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
    return 0 if status not in {
        "sat-model-verification-failed",
        "audit-failed-parity-not-fired",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
