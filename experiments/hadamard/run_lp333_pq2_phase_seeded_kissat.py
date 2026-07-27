#!/usr/bin/env python3
"""Run pinned Kissat on a heuristic-phase-renamed LP333 pq2 formula."""

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


def run_phase_kissat(
    kissat: Path,
    formula: Path,
    log_path: Path,
    max_seconds: float,
    max_memory_bytes: int,
    progress_seconds: float,
) -> dict[str, Any]:
    command = [
        str(kissat),
        "--sat",
        "--seed=0",
        "--phase=true",
        "--forcephase=true",
        "--rephase=false",
        f"--time={math.ceil(max_seconds)}",
        "-s",
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
                            "label": "pq2-phase-seeded",
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
    statistics = {}
    for line in text.splitlines():
        match = re.match(
            r"^c\s+([a-z][a-z0-9_ -]*?):\s+"
            r"([0-9]+(?:\.[0-9]+)?)",
            line,
        )
        if match:
            statistics[
                match.group(1).strip().replace(" ", "_")
            ] = match.group(2)
    return {
        "command": command,
        "returncode": returncode,
        "termination": termination,
        "wall_seconds": wall_seconds,
        "maximum_observed_rss_bytes": maximum_observed_rss,
        "log": str(log_path),
        "log_sha256": common.sha256_file(log_path),
        "statistics": statistics,
    }


def write_decoded_model(
    path: Path, assignments: list[bool]
) -> None:
    with path.open("w", encoding="ascii") as handle:
        handle.write("s SATISFIABLE\n")
        literals = [
            str(variable if assignments[variable] else -variable)
            for variable in range(1, len(assignments))
        ]
        for start in range(0, len(literals), 100):
            suffix = " 0" if start + 100 >= len(literals) else ""
            handle.write(
                "v " + " ".join(literals[start : start + 100])
                + suffix + "\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("phase_metadata", type=Path)
    parser.add_argument("--phase-audit", required=True, type=Path)
    parser.add_argument("--formula-audit", required=True, type=Path)
    parser.add_argument("--kissat", required=True, type=Path)
    parser.add_argument("--kissat-repo", required=True, type=Path)
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
    if not args.kissat.is_file() or not os.access(args.kissat, os.X_OK):
        raise ValueError("Kissat binary missing or not executable")

    metadata = json.loads(args.encoding_metadata.read_text())
    phase = json.loads(args.phase_metadata.read_text())
    phase_audit = json.loads(args.phase_audit.read_text())
    formula_audit = json.loads(args.formula_audit.read_text())
    preregistration = json.loads(args.preregistration.read_text())
    preregistration_audit = json.loads(
        args.preregistration_audit.read_text()
    )
    original_formula = Path(metadata["cnf"]["path"])
    transformed_formula = Path(
        phase["phase_seeded_formula"]["path"]
    )
    heuristic = Path(phase["heuristic"]["path"])
    flipped = set(
        phase["literal_renaming"]["flipped_primary_variables"]
    )
    kissat_version = subprocess.run(
        [str(args.kissat), "--version"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    binding_checks = {
        "metadata_schema": (
            metadata.get("schema")
            == "frontiermath-hadamard-lp333-pq2-cnf-v1"
        ),
        "phase_metadata_schema": (
            phase.get("schema")
            == "frontiermath-lp333-pq2-phase-seeded-cnf-v1"
        ),
        "original_formula_hash": (
            common.sha256_file(original_formula)
            == metadata["cnf"]["sha256"]
            == phase["source_formula"]["sha256"]
        ),
        "transformed_formula_hash": (
            common.sha256_file(transformed_formula)
            == phase["phase_seeded_formula"]["sha256"]
        ),
        "heuristic_hash": (
            common.sha256_file(heuristic)
            == phase["heuristic"]["sha256"]
        ),
        "formula_audit": (
            formula_audit.get("status") == "pass"
            and formula_audit.get("formula_sha256")
            == metadata["cnf"]["sha256"]
        ),
        "phase_audit": (
            phase_audit.get("status") == "pass"
            and phase_audit["inputs"][
                "transformed_formula_sha256"
            ]
            == phase["phase_seeded_formula"]["sha256"]
        ),
        "phase_mapping": (
            phase_audit["checks"][
                "all_true_phase_maps_to_heuristic"
            ]
            and len(flipped) == 334
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
        "preregistered_phase_seed": (
            "phase" in preregistration.get("name", "").lower()
            and "Kissat" in preregistration.get("name", "")
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
        "phase-seed-positive-control",
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
        raise ValueError("Kissat positive control failed")

    target_log = args.output_dir / "phase-seeded-kissat.log"
    transformed_model = (
        args.output_dir / "phase-seeded-kissat.model"
    )
    decoded_model = args.output_dir / "decoded-original.model"
    target_solver = run_phase_kissat(
        args.kissat,
        transformed_formula,
        target_log,
        args.max_seconds,
        args.max_memory_bytes,
        args.progress_seconds,
    )
    model_extraction = None
    transformed_cnf_audit = None
    model_audit = None
    if target_solver["termination"] == "sat":
        model_extraction = common.extract_model(
            target_log, transformed_model
        )
        variable_count, _ = common.formula_dimensions(
            transformed_formula
        )
        transformed_assignments = common.parse_complete_model(
            transformed_model, variable_count
        )
        transformed_cnf_audit = common.stream_check_cnf(
            transformed_formula, transformed_assignments
        )
        decoded_assignments = list(transformed_assignments)
        for variable in flipped:
            decoded_assignments[variable] = not decoded_assignments[
                variable
            ]
        write_decoded_model(decoded_model, decoded_assignments)
        verifier = Path(__file__).with_name(
            "verify_lp333_pq2_model.py"
        )
        model_audit_path = args.output_dir / "model-audit.json"
        command = [
            sys.executable,
            str(verifier),
            str(args.encoding_metadata),
            str(decoded_model),
            "--cnf",
            str(original_formula),
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
        and transformed_cnf_audit
        and transformed_cnf_audit["satisfied"]
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
    manifest = {
        "schema": (
            "frontiermath-hadamard-lp333-pq2-"
            "phase-seeded-kissat-run-v1"
        ),
        "status": status,
        "family_id": 0,
        "scope": (
            "literal-renamed unrestricted prescribed "
            "pq2-compression slice"
        ),
        "claim_boundary": (
            "Only a transformed model satisfying the renamed CNF and "
            "decoding to a directly verified model of the original CNF "
            "decides the slice."
        ),
        "binding_checks": binding_checks,
        "positive_control": positive_control,
        "solver": target_solver,
        "model_extraction": model_extraction,
        "transformed_cnf_audit": transformed_cnf_audit,
        "model_audit": model_audit,
        "phase_policy": {
            "renamed_phase": True,
            "force_phase": True,
            "rephase": False,
            "flipped_primary_variables": len(flipped),
        },
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
            "phase_metadata": str(args.phase_metadata),
            "phase_metadata_sha256": common.sha256_file(
                args.phase_metadata
            ),
            "phase_audit": str(args.phase_audit),
            "phase_audit_sha256": common.sha256_file(
                args.phase_audit
            ),
            "formula_audit": str(args.formula_audit),
            "formula_audit_sha256": common.sha256_file(
                args.formula_audit
            ),
            "heuristic": str(heuristic),
            "heuristic_sha256": common.sha256_file(heuristic),
            "original_formula": str(original_formula),
            "original_formula_sha256": common.sha256_file(
                original_formula
            ),
            "transformed_formula": str(transformed_formula),
            "transformed_formula_sha256": common.sha256_file(
                transformed_formula
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
                "manifest_sha256": common.sha256_file(manifest_path),
                "solver": target_solver,
                "transformed_cnf_satisfied": (
                    transformed_cnf_audit["satisfied"]
                    if transformed_cnf_audit
                    else None
                ),
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
