#!/usr/bin/env python3
"""Run, monitor, and verify the proof-producing full profile-ID3 CNF."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
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
    if not output:
        return None
    return int(output.split()[0]) * 1024


def terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_checked_control(
    checker: Path,
    sat_control_cnf: Path,
    output_dir: Path,
) -> dict[str, Any]:
    empty_proof = output_dir / "bogus-empty-proof-on-sat-control.drat"
    log_path = output_dir / "bogus-empty-proof-on-sat-control.log"
    empty_proof.write_bytes(b"")
    started = time.perf_counter()
    with log_path.open("wb") as log:
        try:
            process = subprocess.run(
                [str(checker), str(sat_control_cnf), str(empty_proof), "-I"],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=120,
            )
            timed_out = False
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    accepted = returncode == 0 and "VERIFIED" in text
    return {
        "accepted": accepted,
        "rejected": not accepted,
        "returncode": returncode,
        "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - started,
        "empty_proof_sha256": sha256_file(empty_proof),
        "log_sha256": sha256_file(log_path),
    }


def replay_proof(
    checker: Path,
    cnf: Path,
    proof: Path,
    log_path: Path,
    max_seconds: float,
) -> dict[str, Any]:
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    with log_path.open("wb") as log:
        try:
            process = subprocess.run(
                [str(checker), str(cnf), str(proof), "-I"],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=max_seconds,
            )
            timed_out = False
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            returncode = None
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    verified = returncode == 0 and "VERIFIED" in text
    return {
        "accepted": verified,
        "returncode": returncode,
        "timed_out": timed_out,
        "verified_marker": "VERIFIED" in text,
        "wall_seconds": time.perf_counter() - started,
        "maximum_resident_set_size_bytes": max(
            0,
            int(usage_after.ru_maxrss - usage_before.ru_maxrss),
        ),
        "log_sha256": sha256_file(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("--profile-ledger", required=True, type=Path)
    parser.add_argument("--cadical", required=True, type=Path)
    parser.add_argument("--checker", required=True, type=Path)
    parser.add_argument("--sat-control-cnf", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=28_800.0)
    parser.add_argument("--max-replay-seconds", type=float, default=7_200.0)
    parser.add_argument(
        "--max-proof-bytes", type=int, default=5 * 1024**3
    )
    parser.add_argument(
        "--max-memory-bytes", type=int, default=12 * 1024**3
    )
    parser.add_argument("--progress-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.max_seconds <= 0 or args.max_replay_seconds <= 0:
        raise ValueError("time ceilings must be positive")

    encoding = json.loads(
        args.encoding_metadata.read_text(encoding="utf-8")
    )
    cnf = Path(encoding["cnf"]["path"])
    if encoding["cnf"]["sha256"] != sha256_file(cnf):
        raise ValueError("CNF hash does not match encoding metadata")
    generator = Path(__file__).with_name("generate_id3_profile_full_cnf.py")
    if encoding["generator_sha256"] != sha256_file(generator):
        raise ValueError("encoding was produced by another generator revision")
    if encoding["inputs"]["profile_ledger_sha256"] != sha256_file(
        args.profile_ledger
    ):
        raise ValueError("profile ledger does not match the encoding")
    for tool in (args.cadical, args.checker):
        if not tool.is_file() or not os.access(tool, os.X_OK):
            raise ValueError(f"tool is missing or not executable: {tool}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    proof_path = args.output_dir / "profile-73-full.drat"
    model_path = args.output_dir / "profile-73-full.model"
    solver_log = args.output_dir / "profile-73-full-cadical.log"
    replay_log = args.output_dir / "profile-73-full-drat-trim.log"
    model_audit_path = args.output_dir / "model-audit.json"
    manifest_path = args.output_dir / "run-manifest.json"
    for path in (
        proof_path,
        model_path,
        solver_log,
        replay_log,
        model_audit_path,
        manifest_path,
    ):
        if path.exists():
            raise ValueError(f"refusing to overwrite existing run artifact: {path}")

    bogus_control = run_checked_control(
        args.checker, args.sat_control_cnf, args.output_dir
    )
    if not bogus_control["rejected"]:
        raise ValueError("proof checker accepted an empty proof on the SAT control")

    command = [
        str(args.cadical),
        "--binary=false",
        "--factor=false",
        "--checkproof=1",
        "--checkwitness=true",
        "-q",
        "-t",
        str(math.ceil(args.max_seconds)),
        "-w",
        str(model_path),
        str(cnf),
        str(proof_path),
    ]
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    termination = None
    maximum_observed_rss = 0
    next_progress = args.progress_seconds
    with solver_log.open("wb") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        while process.poll() is None:
            time.sleep(min(1.0, args.progress_seconds))
            elapsed = time.perf_counter() - started
            proof_bytes = proof_path.stat().st_size if proof_path.exists() else 0
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
            if elapsed > args.max_seconds + 30:
                termination = "external-wall-ceiling"
                terminate_process(process)
                break
            if elapsed >= next_progress:
                print(
                    json.dumps(
                        {
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
    elapsed = time.perf_counter() - started
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if termination is None:
        termination = (
            "sat"
            if returncode == 10
            else ("unsat" if returncode == 20 else "solver-ceiling-or-error")
        )

    solver_record = {
        "command": command,
        "returncode": returncode,
        "termination": termination,
        "wall_seconds": elapsed,
        "maximum_observed_rss_bytes": maximum_observed_rss,
        "child_maximum_resident_set_size_bytes": max(
            0,
            int(usage_after.ru_maxrss - usage_before.ru_maxrss),
        ),
        "log_sha256": sha256_file(solver_log),
        "proof": {
            "exists": proof_path.exists(),
            "bytes": proof_path.stat().st_size if proof_path.exists() else 0,
            "sha256": sha256_file(proof_path) if proof_path.exists() else None,
        },
        "model": {
            "exists": model_path.exists(),
            "bytes": model_path.stat().st_size if model_path.exists() else 0,
            "sha256": sha256_file(model_path) if model_path.exists() else None,
        },
    }

    proof_replay = None
    model_audit = None
    if returncode == 20 and proof_path.exists():
        proof_replay = replay_proof(
            args.checker,
            cnf,
            proof_path,
            replay_log,
            args.max_replay_seconds,
        )
        status = (
            "proof-certified-unsat"
            if proof_replay["accepted"]
            else "unsat-proof-replay-failed"
        )
    elif returncode == 10 and model_path.exists():
        verifier = Path(__file__).with_name(
            "verify_id3_profile_full_model.py"
        )
        verifier_command = [
            sys.executable,
            str(verifier),
            str(args.encoding_metadata),
            str(model_path),
            str(args.profile_ledger),
            "--cnf",
            str(cnf),
            "--output",
            str(model_audit_path),
        ]
        verification = subprocess.run(
            verifier_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        model_audit = {
            "command": verifier_command,
            "returncode": verification.returncode,
            "stdout": verification.stdout[-4000:],
            "exists": model_audit_path.exists(),
            "sha256": (
                sha256_file(model_audit_path)
                if model_audit_path.exists()
                else None
            ),
        }
        if model_audit_path.exists():
            model_audit["result"] = json.loads(
                model_audit_path.read_text(encoding="utf-8")
            )
        status = (
            "directly-verified-sat"
            if verification.returncode == 0
            else "sat-model-verification-failed"
        )
    else:
        status = "unknown-resource-ceiling"

    manifest = {
        "schema": "frontiermath-hadamard-id3-profile-full-run-v1",
        "status": status,
        "claim_boundary": (
            "only proof-certified-unsat or directly-verified-sat decides "
            "profile 73; every resource-ceiling result remains UNKNOWN"
        ),
        "budgets": {
            "max_wall_seconds": args.max_seconds,
            "max_replay_seconds": args.max_replay_seconds,
            "max_proof_bytes": args.max_proof_bytes,
            "max_memory_bytes": args.max_memory_bytes,
        },
        "inputs": {
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "cnf_sha256": sha256_file(cnf),
            "profile_ledger_sha256": sha256_file(args.profile_ledger),
        },
        "tools": {
            "cadical": {
                "path": str(args.cadical),
                "sha256": sha256_file(args.cadical),
            },
            "drat_trim": {
                "path": str(args.checker),
                "sha256": sha256_file(args.checker),
            },
        },
        "bogus_proof_control": bogus_control,
        "solver": solver_record,
        "proof_replay": proof_replay,
        "model_audit": model_audit,
        "environment": {
            "python": platform.python_version(),
            "machine": platform.machine(),
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
                "solver": solver_record,
                "proof_replay": proof_replay,
                "model_audit_status": (
                    model_audit.get("result", {}).get("status")
                    if model_audit
                    else None
                ),
                "manifest_sha256": sha256_file(manifest_path),
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

