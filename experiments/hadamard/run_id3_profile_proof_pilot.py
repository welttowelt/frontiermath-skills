#!/usr/bin/env python3
"""Run and record the proof-producing id3 profile-cell control pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from generate_id3_profile_cell_cnf import generate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_timed(
    command: list[str],
    log_path: Path,
    timeout_seconds: int,
    accepted_returncodes: set[int],
) -> dict[str, object]:
    started = time.perf_counter()
    timed_command = ["/usr/bin/time", "-l", *command]
    try:
        completed = subprocess.run(
            timed_command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        timed_out = False
        stdout = completed.stdout
        stderr = completed.stderr
        returncode = completed.returncode
    except subprocess.TimeoutExpired as error:
        timed_out = True
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        returncode = None
    elapsed = time.perf_counter() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "command: "
        + " ".join(command)
        + "\n\nstdout:\n"
        + stdout
        + "\n\nstderr:\n"
        + stderr,
        encoding="utf-8",
    )
    resident_match = re.search(
        r"^\s*(\d+)\s+maximum resident set size\s*$",
        stderr,
        flags=re.MULTILINE,
    )
    return {
        "command": command,
        "returncode": returncode,
        "accepted_returncodes": sorted(accepted_returncodes),
        "timed_out": timed_out,
        "accepted": not timed_out and returncode in accepted_returncodes,
        "wall_seconds": elapsed,
        "maximum_resident_set_size_bytes": (
            int(resident_match.group(1)) if resident_match else None
        ),
        "log": str(log_path),
        "log_sha256": sha256_file(log_path),
    }


def run_python(
    command: list[str],
    log_path: Path,
    timeout_seconds: int = 300,
) -> dict[str, object]:
    return run_timed(command, log_path, timeout_seconds, {0})


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cadical", required=True, type=Path)
    parser.add_argument("--drat-trim", required=True, type=Path)
    parser.add_argument("--solver-timeout", type=int, default=7200)
    parser.add_argument("--proof-timeout", type=int, default=7200)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    direct_checker = script_dir / "verify_id3_profile_cell_model.py"
    arithmetic_checker = script_dir / "verify_id3_compressed_witness.py"
    if not args.cadical.is_file():
        raise SystemExit(f"missing CaDiCaL binary: {args.cadical}")
    if not args.drat_trim.is_file():
        raise SystemExit(f"missing drat-trim binary: {args.drat_trim}")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    paths = {}
    encodings = {}
    for cell_id in (0, 73):
        stem = f"id3-profile-cell-{cell_id:02d}"
        cell_paths = {
            "cnf": output_dir / f"{stem}.cnf",
            "metadata": output_dir / f"{stem}-encoding.json",
            "solver_log": output_dir / f"{stem}-cadical.log",
        }
        paths[cell_id] = cell_paths
        encodings[cell_id] = generate(
            args.ledger,
            cell_id,
            cell_paths["cnf"],
            cell_paths["metadata"],
        )

    positive = paths[73]
    positive_model = output_dir / "id3-profile-cell-73.model"
    positive_model.unlink(missing_ok=True)
    positive_solver = run_timed(
        [
            str(args.cadical),
            "--factor=false",
            "--checkwitness=true",
            "-q",
            "-w",
            str(positive_model),
            str(positive["cnf"]),
        ],
        positive["solver_log"],
        args.solver_timeout,
        {10},
    )
    if not positive_solver["accepted"] or not positive_model.is_file():
        raise SystemExit("positive cell 73 did not produce a SAT model")

    positive_direct_result = output_dir / (
        "id3-profile-cell-73-model-verification.json"
    )
    positive_witness = output_dir / "id3-profile-cell-73-witness.json"
    positive_direct_log = output_dir / (
        "id3-profile-cell-73-model-verification.log"
    )
    positive_direct = run_python(
        [
            sys.executable,
            str(direct_checker),
            "--metadata",
            str(positive["metadata"]),
            "--cnf",
            str(positive["cnf"]),
            "--model",
            str(positive_model),
            "--output",
            str(positive_direct_result),
            "--witness-output",
            str(positive_witness),
        ],
        positive_direct_log,
    )
    if not positive_direct["accepted"]:
        raise SystemExit("positive cell 73 failed direct model verification")

    positive_arithmetic_result = output_dir / (
        "id3-profile-cell-73-arithmetic-verification.json"
    )
    positive_arithmetic_log = output_dir / (
        "id3-profile-cell-73-arithmetic-verification.log"
    )
    positive_arithmetic = run_python(
        [
            sys.executable,
            str(arithmetic_checker),
            str(positive_witness),
            "--output",
            str(positive_arithmetic_result),
        ],
        positive_arithmetic_log,
    )
    if not positive_arithmetic["accepted"]:
        raise SystemExit("positive cell 73 failed independent arithmetic check")

    negative = paths[0]
    negative_proof = output_dir / "id3-profile-cell-00.drat"
    negative_proof.unlink(missing_ok=True)
    negative_solver = run_timed(
        [
            str(args.cadical),
            "--binary=false",
            "--factor=false",
            "--checkproof=1",
            "-q",
            str(negative["cnf"]),
            str(negative_proof),
        ],
        negative["solver_log"],
        args.solver_timeout,
        {20},
    )
    if not negative_solver["accepted"] or not negative_proof.is_file():
        raise SystemExit("negative cell 0 did not produce an UNSAT proof")

    negative_replay_log = output_dir / (
        "id3-profile-cell-00-drat-trim.log"
    )
    negative_replay = run_timed(
        [
            str(args.drat_trim),
            str(negative["cnf"]),
            str(negative_proof),
            "-I",
        ],
        negative_replay_log,
        args.proof_timeout,
        {0},
    )
    replay_text = negative_replay_log.read_text(encoding="utf-8")
    negative_replay["verified_marker"] = "s VERIFIED" in replay_text
    negative_replay["accepted"] = bool(
        negative_replay["accepted"] and negative_replay["verified_marker"]
    )
    if not negative_replay["accepted"]:
        raise SystemExit("independent drat-trim replay rejected cell 0")

    bogus_proof = output_dir / "bogus-empty-proof-on-sat-cell-73.drat"
    bogus_proof.write_text("0\n", encoding="ascii")
    bogus_log = output_dir / "bogus-empty-proof-on-sat-cell-73.log"
    bogus_run = run_timed(
        [
            str(args.drat_trim),
            str(positive["cnf"]),
            str(bogus_proof),
            "-I",
        ],
        bogus_log,
        min(args.proof_timeout, 300),
        set(),
    )
    bogus_text = bogus_log.read_text(encoding="utf-8")
    bogus_rejected = (
        bogus_run["returncode"] != 0 and "s VERIFIED" not in bogus_text
    )

    cadical_version = subprocess.run(
        [str(args.cadical), "--version"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = {
        "schema": "frontiermath-hadamard-id3-profile-proof-pilot-v1",
        "status": "pass" if bogus_rejected else "fail",
        "claim_status": {
            "cell_0": "proof-certified-infeasible",
            "cell_73": "model-verified-feasible",
        },
        "scope": (
            "named compressed profile cells only; no full LP(333) or H(668) "
            "claim"
        ),
        "refined_ledger_sha256": encodings[0]["refined_ledger_sha256"],
        "budget": {
            "clause_ceiling_per_cell": 2_000_000,
            "proof_byte_ceiling": 5 * 1024**3,
            "replay_wall_seconds_ceiling": 7200,
            "memory_byte_ceiling": 12 * 1024**3,
        },
        "tools": {
            "cadical": {
                "path": str(args.cadical),
                "version": cadical_version,
                "binary_sha256": sha256_file(args.cadical),
            },
            "drat_trim": {
                "path": str(args.drat_trim),
                "binary_sha256": sha256_file(args.drat_trim),
                "source_sha256": sha256_file(
                    args.drat_trim.parent / "drat-trim.c"
                ),
            },
        },
        "cell_0": {
            "encoding": {
                key: encodings[0][key]
                for key in (
                    "cnf_sha256",
                    "cnf_bytes",
                    "variables",
                    "clauses",
                    "square_counts",
                )
            },
            "encoding_metadata": file_record(negative["metadata"]),
            "solver": negative_solver,
            "proof": file_record(negative_proof),
            "independent_replay": negative_replay,
        },
        "cell_73": {
            "encoding": {
                key: encodings[73][key]
                for key in (
                    "cnf_sha256",
                    "cnf_bytes",
                    "variables",
                    "clauses",
                    "square_counts",
                )
            },
            "encoding_metadata": file_record(positive["metadata"]),
            "solver": positive_solver,
            "model": file_record(positive_model),
            "direct_model_verification": file_record(
                positive_direct_result
            ),
            "arithmetic_verification": file_record(
                positive_arithmetic_result
            ),
            "witness": file_record(positive_witness),
        },
        "bogus_proof_control": {
            "target": "SAT cell 73",
            "proof": file_record(bogus_proof),
            "run": bogus_run,
            "rejected": bogus_rejected,
        },
        "gate_a_checks": {
            "both_bound_to_same_ledger": (
                encodings[0]["refined_ledger_sha256"]
                == encodings[73]["refined_ledger_sha256"]
            ),
            "both_under_clause_ceiling": all(
                encodings[cell_id]["clauses"] < 2_000_000
                for cell_id in (0, 73)
            ),
            "negative_proof_under_byte_ceiling": (
                negative_proof.stat().st_size < 5 * 1024**3
            ),
            "negative_replay_under_wall_ceiling": (
                negative_replay["wall_seconds"] < 7200
            ),
            "negative_replay_under_memory_ceiling": (
                negative_replay["maximum_resident_set_size_bytes"] is not None
                and negative_replay["maximum_resident_set_size_bytes"]
                < 12 * 1024**3
            ),
            "positive_direct_check_passed": positive_direct["accepted"],
            "positive_arithmetic_check_passed": positive_arithmetic["accepted"],
            "bogus_proof_rejected": bogus_rejected,
        },
        "runtime_seconds": time.perf_counter() - started,
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    if not all(result["gate_a_checks"].values()):
        result["status"] = "fail"

    manifest = output_dir / "pilot-manifest.json"
    manifest.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "claim_status": result["claim_status"],
                "gate_a_checks": result["gate_a_checks"],
                "manifest": str(manifest),
                "manifest_sha256": sha256_file(manifest),
                "runtime_seconds": result["runtime_seconds"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
