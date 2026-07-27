#!/usr/bin/env python3
"""Run a pinned proofless Kissat SAT-discovery arm with direct model audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any


EXPECTED_KISSAT_VERSION = "4.0.4"
EXPECTED_KISSAT_SHA256 = (
    "ca26c445800f6a88caebe925ee5b60d0907da4f1c8418f4044a51b1a22224983"
)
EXPECTED_KISSAT_REVISION = "8af8e56f174b778aef3aa45af9f739b2a5f492c2"
EXPECTED_SAT_CONTROL_SHA256 = (
    "255879dc8c072d6d0fa621d6dc1bfd752b13d71946baf94c7ae86d2e1b4f4da3"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_revision(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def process_rss_bytes(pid: int) -> int | None:
    try:
        output = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return int(output.split()[0]) * 1024 if output else None


def terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def exact_marker(text: str, marker: str) -> bool:
    return any(line.strip() == marker for line in text.splitlines())


def extract_model(log_path: Path, model_path: Path) -> dict[str, Any]:
    lines = []
    for line in log_path.read_text(
        encoding="ascii", errors="replace"
    ).splitlines():
        if line.startswith("s ") or line.startswith("v "):
            lines.append(line)
    model_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return {
        "lines": len(lines),
        "bytes": model_path.stat().st_size,
        "sha256": sha256_file(model_path),
    }


def parse_complete_model(
    model_path: Path, variable_count: int
) -> list[bool]:
    values: list[bool | None] = [None] * (variable_count + 1)
    status = None
    for line in model_path.read_text(encoding="ascii").splitlines():
        if line.startswith("s "):
            status = line[2:].strip()
        elif line.startswith("v "):
            for token in line[2:].split():
                literal = int(token)
                if not literal:
                    continue
                variable = abs(literal)
                if not 1 <= variable <= variable_count:
                    raise ValueError("positive-control model variable out of range")
                assignment = literal > 0
                if (
                    values[variable] is not None
                    and values[variable] != assignment
                ):
                    raise ValueError(
                        "positive-control model assigns a variable inconsistently"
                    )
                values[variable] = assignment
    if status != "SATISFIABLE":
        raise ValueError(f"positive-control model status is {status!r}")
    missing = [
        variable
        for variable in range(1, variable_count + 1)
        if values[variable] is None
    ]
    if missing:
        raise ValueError(
            f"positive-control model omits variables: {missing[:5]}"
        )
    return [False] + [bool(value) for value in values[1:]]


def stream_check_cnf(
    formula: Path, assignments: list[bool]
) -> dict[str, Any]:
    declared_variables = None
    declared_clauses = None
    clauses = 0
    unsatisfied = 0
    with formula.open("r", encoding="ascii") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("c"):
                continue
            if stripped.startswith("p "):
                fields = stripped.split()
                if len(fields) != 4 or fields[1] != "cnf":
                    raise ValueError("invalid DIMACS header")
                declared_variables = int(fields[2])
                declared_clauses = int(fields[3])
                if declared_variables != len(assignments) - 1:
                    raise ValueError("model and CNF variable counts differ")
                continue
            literals = [int(token) for token in stripped.split()]
            if not literals or literals[-1] != 0:
                raise ValueError("unterminated DIMACS clause")
            clauses += 1
            if not any(
                assignments[abs(literal)] == (literal > 0)
                for literal in literals[:-1]
            ):
                unsatisfied += 1
                if unsatisfied >= 10:
                    break
    if declared_variables is None or declared_clauses is None:
        raise ValueError("DIMACS header missing")
    if unsatisfied == 0 and clauses != declared_clauses:
        raise ValueError("DIMACS clause count differs from header")
    return {
        "declared_variables": declared_variables,
        "declared_clauses": declared_clauses,
        "clauses_checked": clauses,
        "unsatisfied_clauses": unsatisfied,
        "satisfied": unsatisfied == 0,
    }


def formula_dimensions(path: Path) -> tuple[int, int]:
    with path.open("r", encoding="ascii") as handle:
        for line in handle:
            if line.startswith("p "):
                fields = line.split()
                if len(fields) != 4 or fields[1] != "cnf":
                    raise ValueError("invalid DIMACS header")
                return int(fields[2]), int(fields[3])
    raise ValueError("DIMACS header missing")


def run_kissat(
    kissat: Path,
    formula: Path,
    log_path: Path,
    max_seconds: float,
    max_memory_bytes: int,
    progress_seconds: float,
    family_id: int | str,
) -> dict[str, Any]:
    command = [
        str(kissat),
        "--sat",
        "--seed=0",
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
            rss = process_rss_bytes(process.pid)
            if rss is not None:
                maximum_observed_rss = max(maximum_observed_rss, rss)
            if rss is not None and rss > max_memory_bytes:
                termination = "memory-ceiling"
                terminate_process(process)
                break
            if elapsed > max_seconds + 15:
                termination = "external-wall-ceiling"
                terminate_process(process)
                break
            if elapsed >= next_progress:
                print(
                    json.dumps(
                        {
                            "elapsed_seconds": round(elapsed, 1),
                            "family_id": family_id,
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
        if returncode == 10 or exact_marker(text, "s SATISFIABLE"):
            termination = "sat"
        elif returncode == 20 or exact_marker(text, "s UNSATISFIABLE"):
            termination = "unsat"
        else:
            termination = "solver-ceiling-or-error"
    statistics = {}
    for line in text.splitlines():
        match = re.match(
            r"^c\s+([a-z][a-z0-9_ -]*?):\s+([0-9]+(?:\.[0-9]+)?)",
            line,
        )
        if match:
            statistics[match.group(1).strip().replace(" ", "_")] = (
                match.group(2)
            )
    return {
        "command": command,
        "returncode": returncode,
        "termination": termination,
        "wall_seconds": wall_seconds,
        "maximum_observed_rss_bytes": maximum_observed_rss,
        "log_sha256": sha256_file(log_path),
        "statistics": statistics,
    }


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
    parser.add_argument("--max-seconds", type=float, default=3600.0)
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
    kissat_version = subprocess.run(
        [str(args.kissat), "--version"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    binding_checks = {
        "metadata_status": metadata.get("status") == "generated",
        "family_in_frozen_schedule": metadata.get("family_id") in (4, 5),
        "generator_hash_recorded": (
            isinstance(metadata.get("generator_sha256"), str)
            and len(metadata["generator_sha256"]) == 64
        ),
        "formula_hash": (
            metadata["cnf"]["sha256"] == sha256_file(formula)
        ),
        "formula_audit": (
            formula_audit.get("status") == "pass"
            and formula_audit.get("formula_sha256")
            == metadata["cnf"]["sha256"]
        ),
        "unary_channels_enabled": (
            metadata.get("unary_cardinality_channels", {}).get("enabled")
            is True
        ),
        "unary_truth_table": (
            metadata["controls"]["sequential_cardinality_truth_table"][
                "result"
            ]
            == "PASS"
        ),
        "parent_formula_binding": (
            metadata["controls"]["parent_formula_binding"]["result"]
            == "PASS"
        ),
        "kissat_version": kissat_version == EXPECTED_KISSAT_VERSION,
        "kissat_hash": (
            sha256_file(args.kissat) == EXPECTED_KISSAT_SHA256
        ),
        "kissat_revision": (
            git_revision(args.kissat_repo) == EXPECTED_KISSAT_REVISION
        ),
        "sat_control_hash": (
            sha256_file(args.sat_control_cnf)
            == EXPECTED_SAT_CONTROL_SHA256
        ),
        "preregistration_schema": (
            preregistration.get("schema")
            == "computational-experiment-preregistration/v1"
        ),
        "preregistration_audit": (
            preregistration_audit.get("status") == "pass"
        ),
        "preregistered_family": (
            f"ID{metadata['family_id']}"
            in preregistration.get("evidence_unit", "")
        ),
    }
    if not all(binding_checks.values()):
        raise ValueError(f"input binding failed: {binding_checks}")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    positive_log = args.output_dir / "positive-control-kissat.log"
    positive_model = args.output_dir / "positive-control.model"
    positive_solver = run_kissat(
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
    positive_extraction = extract_model(positive_log, positive_model)
    positive_variables, _ = formula_dimensions(args.sat_control_cnf)
    positive_assignments = parse_complete_model(
        positive_model, positive_variables
    )
    positive_cnf = stream_check_cnf(
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

    family_id = metadata["family_id"]
    target_log = args.output_dir / f"id{family_id}-kissat.log"
    target_model = args.output_dir / f"id{family_id}-kissat.model"
    target_solver = run_kissat(
        args.kissat,
        formula,
        target_log,
        args.max_seconds,
        args.max_memory_bytes,
        args.progress_seconds,
        family_id,
    )
    model_extraction = None
    model_audit = None
    if target_solver["termination"] == "sat":
        model_extraction = extract_model(target_log, target_model)
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
                sha256_file(model_audit_path)
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
    manifest = {
        "schema": "frontiermath-hadamard-kissat-sat-discovery-v1",
        "status": status,
        "family_id": family_id,
        "claim_boundary": (
            "Only directly-verified-sat decides this fixed family. A "
            "proofless UNSAT status is explicitly nondecisive."
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
                "sha256": sha256_file(args.kissat),
                "source_repo": str(args.kissat_repo),
                "source_revision": git_revision(args.kissat_repo),
            }
        },
        "inputs": {
            "encoding_metadata": str(args.encoding_metadata),
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "formula": str(formula),
            "formula_sha256": metadata["cnf"]["sha256"],
            "formula_audit": str(args.formula_audit),
            "formula_audit_sha256": sha256_file(args.formula_audit),
            "preregistration": str(args.preregistration),
            "preregistration_sha256": sha256_file(args.preregistration),
            "preregistration_audit": str(
                args.preregistration_audit
            ),
            "preregistration_audit_sha256": sha256_file(
                args.preregistration_audit
            ),
            "sat_control_cnf": str(args.sat_control_cnf),
            "sat_control_cnf_sha256": EXPECTED_SAT_CONTROL_SHA256,
        },
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    manifest_path = args.output_dir / "run-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": status,
                "family_id": family_id,
                "manifest_sha256": sha256_file(manifest_path),
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
