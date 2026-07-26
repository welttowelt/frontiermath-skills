#!/usr/bin/env python3
"""Run the proof-producing ID10 calibration with static symmetry breaking."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import subprocess
import time
from typing import Any, Sequence


DRAT_BASELINE_BYTES = 712_682_070
PROMOTION_PROOF_BYTES = 237_560_690


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def git_revision(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def run_drat_trim(
    checker: Path,
    formula: Path,
    proof: Path,
    log_path: Path,
    max_seconds: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    with log_path.open("wb") as log:
        try:
            process = subprocess.run(
                [str(checker), str(formula), str(proof), "-I"],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=max_seconds,
                check=False,
            )
            returncode = process.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            returncode = None
            timed_out = True
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "accepted": (
            returncode == 0
            and exact_marker(text, "s VERIFIED")
            and not exact_marker(text, "s NOT VERIFIED")
        ),
        "returncode": returncode,
        "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - started,
        "verified_marker": exact_marker(text, "s VERIFIED"),
        "not_verified_marker": exact_marker(text, "s NOT VERIFIED"),
        "log_sha256": sha256_file(log_path),
    }


def bogus_control(
    checker: Path,
    sat_formula: Path,
    proof_path: Path,
    log_path: Path,
    max_seconds: float,
) -> dict[str, Any]:
    proof_path.write_bytes(b"")
    result = run_drat_trim(
        checker, sat_formula, proof_path, log_path, max_seconds
    )
    return {
        **result,
        "rejected": not result["accepted"],
        "proof_sha256": sha256_file(proof_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("--cadical", required=True, type=Path)
    parser.add_argument("--cadical-repo", required=True, type=Path)
    parser.add_argument("--checker", required=True, type=Path)
    parser.add_argument("--sat-control-cnf", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--max-verification-seconds", type=float, default=120.0)
    parser.add_argument("--max-proof-bytes", type=int, default=1024**3)
    parser.add_argument("--max-memory-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--progress-seconds", type=float, default=15.0)
    args = parser.parse_args()
    if min(
        args.max_seconds,
        args.max_verification_seconds,
        args.progress_seconds,
    ) <= 0:
        raise ValueError("time limits must be positive")

    metadata = json.loads(
        args.encoding_metadata.read_text(encoding="utf-8")
    )
    formula = Path(metadata["cnf"]["path"])
    generator = Path(__file__).with_name(
        "generate_lp333_symmetry_cnf.py"
    )
    binding_checks = {
        "metadata_status": metadata.get("status") == "generated",
        "generator_hash": (
            metadata["generator_sha256"] == sha256_file(generator)
        ),
        "formula_hash": (
            metadata["cnf"]["sha256"] == sha256_file(formula)
        ),
        "symmetry_group_control": (
            metadata["controls"]["exact_decimation_group"]["result"]
            == "PASS"
        ),
        "lp63_positive_control": (
            metadata["controls"]["lp63_positive_canonicalization"]["result"]
            == "PASS"
        ),
        "full_group_order": (
            metadata["symmetry"]["full_group_order"] == 72
            and metadata["symmetry"]["nonidentity_lex_leaders"] == 71
        ),
    }
    if not all(binding_checks.values()):
        raise ValueError(f"input binding failed: {binding_checks}")
    for tool in (args.cadical, args.checker):
        if not tool.is_file() or not os.access(tool, os.X_OK):
            raise ValueError(f"tool missing or not executable: {tool}")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    family_id = metadata["family_id"]
    proof_path = args.output_dir / f"id{family_id}-symmetry.drat"
    model_path = args.output_dir / f"id{family_id}-symmetry.model"
    solver_log = args.output_dir / f"id{family_id}-cadical.log"
    replay_log = args.output_dir / f"id{family_id}-drat-trim.log"
    fresh_replay_log = args.output_dir / f"id{family_id}-drat-trim-fresh.log"
    bogus_proof = args.output_dir / "bogus-empty.drat"
    bogus_log = args.output_dir / "bogus-empty.log"
    fresh_bogus_proof = args.output_dir / "bogus-empty-fresh.drat"
    fresh_bogus_log = args.output_dir / "bogus-empty-fresh.log"
    manifest_path = args.output_dir / "run-manifest.json"

    cadical_hash = sha256_file(args.cadical)
    checker_hash = sha256_file(args.checker)
    first_bogus = bogus_control(
        args.checker,
        args.sat_control_cnf,
        bogus_proof,
        bogus_log,
        args.max_verification_seconds,
    )
    if not first_bogus["rejected"]:
        raise ValueError("drat-trim accepted an empty SAT-control proof")

    command = [
        str(args.cadical),
        "--binary=false",
        "--factor=false",
        "--checkproof=1",
        "--checkwitness=true",
        "-t",
        str(math.ceil(args.max_seconds)),
        "-w",
        str(model_path),
        str(formula),
        str(proof_path),
    ]
    started = time.perf_counter()
    termination = None
    maximum_observed_rss = 0
    next_progress = args.progress_seconds
    with solver_log.open("wb") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT
        )
        while process.poll() is None:
            time.sleep(min(0.5, args.progress_seconds))
            elapsed = time.perf_counter() - started
            proof_bytes = (
                proof_path.stat().st_size if proof_path.exists() else 0
            )
            rss = process_rss_bytes(process.pid)
            if rss is not None:
                maximum_observed_rss = max(maximum_observed_rss, rss)
            if proof_bytes > args.max_proof_bytes:
                termination = "proof-size-ceiling"
                terminate_process(process)
                break
            if rss is not None and rss > args.max_memory_bytes:
                termination = "memory-ceiling"
                terminate_process(process)
                break
            if elapsed > args.max_seconds + 15:
                termination = "external-wall-ceiling"
                terminate_process(process)
                break
            if elapsed >= next_progress:
                print(
                    json.dumps(
                        {
                            "family_id": family_id,
                            "elapsed_seconds": round(elapsed, 1),
                            "proof_bytes": proof_bytes,
                            "rss_bytes": rss,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                next_progress += args.progress_seconds
        returncode = process.wait()
    solver_wall = time.perf_counter() - started
    solver_text = solver_log.read_text(encoding="utf-8", errors="replace")
    if termination is None:
        if returncode == 20 or exact_marker(
            solver_text, "s UNSATISFIABLE"
        ):
            termination = "unsat"
        elif returncode == 10 or exact_marker(
            solver_text, "s SATISFIABLE"
        ):
            termination = "sat"
        else:
            termination = "solver-ceiling-or-error"

    proof_exists = proof_path.is_file()
    proof_bytes = proof_path.stat().st_size if proof_exists else 0
    proof_hash = sha256_file(proof_path) if proof_exists else None
    first_replay = None
    fresh_replay = None
    fresh_bogus = None
    replay_bindings = None
    if termination == "unsat" and proof_exists:
        first_replay = run_drat_trim(
            args.checker,
            formula,
            proof_path,
            replay_log,
            args.max_verification_seconds,
        )
        replay_bindings = {
            "formula_sha256_unchanged": (
                sha256_file(formula) == metadata["cnf"]["sha256"]
            ),
            "proof_sha256_unchanged": (
                sha256_file(proof_path) == proof_hash
            ),
            "cadical_sha256_unchanged": (
                sha256_file(args.cadical) == cadical_hash
            ),
            "checker_sha256_unchanged": (
                sha256_file(args.checker) == checker_hash
            ),
        }
        if first_replay["accepted"] and all(replay_bindings.values()):
            fresh_replay = run_drat_trim(
                args.checker,
                formula,
                proof_path,
                fresh_replay_log,
                args.max_verification_seconds,
            )
            fresh_bogus = bogus_control(
                args.checker,
                args.sat_control_cnf,
                fresh_bogus_proof,
                fresh_bogus_log,
                args.max_verification_seconds,
            )

    accepted_twice = bool(
        first_replay
        and first_replay["accepted"]
        and fresh_replay
        and fresh_replay["accepted"]
    )
    fresh_bogus_rejected = bool(
        fresh_bogus and fresh_bogus["rejected"]
    )
    volume_gate = proof_bytes <= PROMOTION_PROOF_BYTES
    if accepted_twice and fresh_bogus_rejected and volume_gate:
        status = "gate-pass"
    elif accepted_twice and fresh_bogus_rejected:
        status = "proof-certified-volume-gate-fail"
    elif termination == "sat":
        status = "sat-needs-direct-model-audit"
    else:
        status = "unknown"

    manifest = {
        "schema": "frontiermath-hadamard-lp333-symmetry-run-v1",
        "status": status,
        "family_id": family_id,
        "claim_boundary": (
            "Only gate-pass promotes this exact static mechanism to ID9; "
            "resource ceilings remain UNKNOWN."
        ),
        "binding_checks": binding_checks,
        "budgets": {
            "max_wall_seconds": args.max_seconds,
            "max_memory_bytes": args.max_memory_bytes,
            "max_proof_bytes": args.max_proof_bytes,
            "max_verification_seconds": args.max_verification_seconds,
            "promotion_proof_bytes": PROMOTION_PROOF_BYTES,
            "drat_baseline_bytes": DRAT_BASELINE_BYTES,
        },
        "solver": {
            "command": command,
            "returncode": returncode,
            "termination": termination,
            "wall_seconds": solver_wall,
            "maximum_observed_rss_bytes": maximum_observed_rss,
            "log_sha256": sha256_file(solver_log),
            "model": {
                "exists": model_path.is_file(),
                "bytes": model_path.stat().st_size
                if model_path.is_file()
                else 0,
                "sha256": sha256_file(model_path)
                if model_path.is_file()
                else None,
            },
            "proof": {
                "exists": proof_exists,
                "bytes": proof_bytes,
                "sha256": proof_hash,
            },
        },
        "proof_checks": {
            "first_bogus": first_bogus,
            "first_replay": first_replay,
            "fresh_replay_bindings": replay_bindings,
            "fresh_replay": fresh_replay,
            "fresh_bogus": fresh_bogus,
        },
        "significance": {
            "accepted_twice": accepted_twice,
            "fresh_bogus_rejected": fresh_bogus_rejected,
            "proof_volume_gate_pass": volume_gate,
            "proof_reduction_over_drat": (
                DRAT_BASELINE_BYTES / proof_bytes if proof_bytes else None
            ),
        },
        "tools": {
            "cadical": {
                "path": str(args.cadical),
                "source_repo": str(args.cadical_repo),
                "source_revision": git_revision(args.cadical_repo),
                "sha256": cadical_hash,
            },
            "drat_trim": {
                "path": str(args.checker),
                "sha256": checker_hash,
            },
        },
        "inputs": {
            "encoding_metadata": str(args.encoding_metadata),
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "formula_sha256": sha256_file(formula),
            "sat_control_cnf_sha256": sha256_file(
                args.sat_control_cnf
            ),
        },
        "environment": {
            "machine": platform.machine(),
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": status,
                "family_id": family_id,
                "solver": manifest["solver"],
                "proof_checks": manifest["proof_checks"],
                "significance": manifest["significance"],
                "manifest_sha256": sha256_file(manifest_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
