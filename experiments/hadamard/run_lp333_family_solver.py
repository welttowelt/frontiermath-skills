#!/usr/bin/env python3
"""Run and verify a proof-producing LP333 multiplier-family formula."""

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


def bogus_proof_control(
    checker: Path, sat_control_cnf: Path, output_dir: Path
) -> dict[str, Any]:
    proof = output_dir / "bogus-empty-proof-on-sat-control.drat"
    log_path = output_dir / "bogus-empty-proof-on-sat-control.log"
    proof.write_bytes(b"")
    started = time.perf_counter()
    with log_path.open("wb") as log:
        try:
            process = subprocess.run(
                [str(checker), str(sat_control_cnf), str(proof), "-I"],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=120,
            )
            returncode = process.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            returncode = None
            timed_out = True
    text = log_path.read_text(encoding="utf-8", errors="replace")
    accepted = returncode == 0 and "VERIFIED" in text
    return {
        "accepted": accepted,
        "rejected": not accepted,
        "returncode": returncode,
        "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - started,
        "empty_proof_sha256": sha256_file(proof),
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
            returncode = process.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            returncode = None
            timed_out = True
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    accepted = returncode == 0 and "VERIFIED" in text
    return {
        "accepted": accepted,
        "returncode": returncode,
        "timed_out": timed_out,
        "verified_marker": "VERIFIED" in text,
        "wall_seconds": time.perf_counter() - started,
        "maximum_resident_set_size_bytes": max(
            0, int(usage_after.ru_maxrss - usage_before.ru_maxrss)
        ),
        "log_sha256": sha256_file(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("--cnf-audit", required=True, type=Path)
    parser.add_argument("--cadical", required=True, type=Path)
    parser.add_argument("--checker", required=True, type=Path)
    parser.add_argument("--sat-control-cnf", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--max-replay-seconds", type=float, default=7200.0)
    parser.add_argument("--max-proof-bytes", type=int, default=1024**3)
    parser.add_argument("--max-memory-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--progress-seconds", type=float, default=15.0)
    args = parser.parse_args()
    if (
        args.max_seconds <= 0
        or args.max_replay_seconds <= 0
        or args.progress_seconds <= 0
    ):
        raise ValueError("time controls must be positive")

    metadata = json.loads(
        args.encoding_metadata.read_text(encoding="utf-8")
    )
    audit = json.loads(args.cnf_audit.read_text(encoding="utf-8"))
    family_id = metadata["family_id"]
    if audit.get("status") != "pass" or audit.get("family_id") != family_id:
        raise ValueError("CNF audit did not pass for this family")
    if audit["inputs"]["encoding_metadata_sha256"] != sha256_file(
        args.encoding_metadata
    ):
        raise ValueError("CNF audit is bound to different metadata")
    cnf = Path(metadata["cnf"]["path"])
    if metadata["cnf"]["sha256"] != sha256_file(cnf):
        raise ValueError("CNF hash does not match metadata")
    generator = Path(__file__).with_name("generate_lp333_family_cnf.py")
    if metadata["generator_sha256"] != sha256_file(generator):
        raise ValueError("generator source changed after formula creation")
    for tool in (args.cadical, args.checker):
        if not tool.is_file() or not os.access(tool, os.X_OK):
            raise ValueError(f"tool missing or not executable: {tool}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"id{family_id}"
    proof_path = args.output_dir / f"{prefix}.drat"
    model_path = args.output_dir / f"{prefix}.model"
    solver_log = args.output_dir / f"{prefix}-cadical.log"
    replay_log = args.output_dir / f"{prefix}-drat-trim.log"
    model_audit_path = args.output_dir / "model-audit.json"
    manifest_path = args.output_dir / "run-manifest.json"
    control_paths = (
        args.output_dir / "bogus-empty-proof-on-sat-control.drat",
        args.output_dir / "bogus-empty-proof-on-sat-control.log",
    )
    for path in (
        proof_path,
        model_path,
        solver_log,
        replay_log,
        model_audit_path,
        manifest_path,
        *control_paths,
    ):
        if path.exists():
            raise ValueError(f"refusing to overwrite {path}")

    control = bogus_proof_control(
        args.checker, args.sat_control_cnf, args.output_dir
    )
    if not control["rejected"]:
        raise ValueError("proof checker accepted an empty SAT-control proof")

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
            command, stdout=log, stderr=subprocess.STDOUT
        )
        while process.poll() is None:
            time.sleep(min(1.0, args.progress_seconds))
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
            if elapsed > args.max_seconds + 30:
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
            0, int(usage_after.ru_maxrss - usage_before.ru_maxrss)
        ),
        "log_sha256": sha256_file(solver_log),
        "proof": {
            "exists": proof_path.exists(),
            "bytes": proof_path.stat().st_size if proof_path.exists() else 0,
            "sha256": (
                sha256_file(proof_path) if proof_path.exists() else None
            ),
        },
        "model": {
            "exists": model_path.exists(),
            "bytes": model_path.stat().st_size if model_path.exists() else 0,
            "sha256": (
                sha256_file(model_path) if model_path.exists() else None
            ),
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
            "verify_lp333_family_model.py"
        )
        verifier_command = [
            sys.executable,
            str(verifier),
            str(args.encoding_metadata),
            str(model_path),
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
        "schema": "frontiermath-hadamard-lp333-family-run-v1",
        "status": status,
        "family_id": family_id,
        "claim_boundary": (
            "only proof-certified-unsat or directly-verified-sat decides "
            "the named family; every resource ceiling remains UNKNOWN"
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
            "cnf_audit_sha256": sha256_file(args.cnf_audit),
            "cnf_sha256": sha256_file(cnf),
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
        "environment": {
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "bogus_proof_control": control,
        "solver": solver_record,
        "proof_replay": proof_replay,
        "model_audit": model_audit,
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "family_id": family_id,
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
        )
    )
    return 0 if status in (
        "proof-certified-unsat",
        "directly-verified-sat",
        "unknown-resource-ceiling",
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
