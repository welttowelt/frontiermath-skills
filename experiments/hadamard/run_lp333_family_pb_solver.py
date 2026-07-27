#!/usr/bin/env python3
"""Run the preregistered native-PB proof calibration for one LP333 family."""

from __future__ import annotations

import argparse
import hashlib
import json
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


def git_revision(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def command_version(command: Sequence[str]) -> str:
    result = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )
    return (result.stdout + result.stderr).strip().splitlines()[0]


def exact_marker(output: str, marker: str) -> bool:
    return any(line.strip() == marker for line in output.splitlines())


def run_veripb(
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
                [str(checker), str(formula), str(proof)],
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
        "accepted_unsat": (
            returncode == 0 and exact_marker(text, "s VERIFIED UNSAT")
        ),
        "returncode": returncode,
        "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - started,
        "verified_unsat_marker": exact_marker(text, "s VERIFIED UNSAT"),
        "verified_no_conclusion_marker": exact_marker(
            text, "s VERIFIED NO CONCLUSION"
        ),
        "log_sha256": sha256_file(log_path),
    }


def bogus_control(
    checker: Path,
    formula: Path,
    proof_path: Path,
    log_path: Path,
    max_seconds: float,
) -> dict[str, Any]:
    proof_path.write_bytes(b"")
    result = run_veripb(
        checker, formula, proof_path, log_path, max_seconds
    )
    return {
        **result,
        "rejected_as_unsat": not result["accepted_unsat"],
        "proof_sha256": sha256_file(proof_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("--roundingsat", required=True, type=Path)
    parser.add_argument("--roundingsat-repo", required=True, type=Path)
    parser.add_argument("--veripb", required=True, type=Path)
    parser.add_argument("--veripb-repo", required=True, type=Path)
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
    if metadata.get("status") != "gate-a-pass":
        raise ValueError("native OPB semantic gate did not pass")
    formula = Path(metadata["opb"]["path"])
    lp63_formula = Path(
        metadata["controls"]["lp63_positive_fixture"]["opb_path"]
    )
    generator = Path(__file__).with_name(
        "generate_lp333_family_opb.py"
    )
    binding_checks = {
        "generator_hash": (
            metadata["generator_sha256"] == sha256_file(generator)
        ),
        "formula_hash": (
            metadata["opb"]["sha256"] == sha256_file(formula)
        ),
        "lp63_formula_hash": (
            metadata["controls"]["lp63_positive_fixture"]["opb_sha256"]
            == sha256_file(lp63_formula)
        ),
        "semantic_control": (
            metadata["controls"]["random_direct_semantic_equivalence"][
                "result"
            ]
            == "PASS"
        ),
        "direct_paf_control": (
            metadata["controls"]["random_direct_paf_equivalence"]["result"]
            == "PASS"
        ),
        "lp63_positive_control": (
            metadata["controls"]["lp63_positive_fixture"]["result"]
            == "PASS"
        ),
    }
    if not all(binding_checks.values()):
        raise ValueError(f"input binding failed: {binding_checks}")
    for tool in (args.roundingsat, args.veripb):
        if not tool.is_file() or not os.access(tool, os.X_OK):
            raise ValueError(f"tool missing or not executable: {tool}")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    family_id = metadata["family_id"]
    proof_path = args.output_dir / f"id{family_id}.pbp"
    solver_log = args.output_dir / f"id{family_id}-roundingsat.log"
    replay_log = args.output_dir / f"id{family_id}-veripb.log"
    fresh_replay_log = args.output_dir / f"id{family_id}-veripb-fresh.log"
    bogus_proof = args.output_dir / "bogus-empty-lp63.pbp"
    bogus_log = args.output_dir / "bogus-empty-lp63.log"
    fresh_bogus_proof = args.output_dir / "bogus-empty-lp63-fresh.pbp"
    fresh_bogus_log = args.output_dir / "bogus-empty-lp63-fresh.log"
    manifest_path = args.output_dir / "run-manifest.json"

    first_bogus = bogus_control(
        args.veripb,
        lp63_formula,
        bogus_proof,
        bogus_log,
        args.max_verification_seconds,
    )
    if not first_bogus["rejected_as_unsat"]:
        raise ValueError("VeriPB accepted an empty proof as LP63 UNSAT")

    command = [
        str(args.roundingsat),
        str(formula),
        f"--proof-log={proof_path}",
        f"--time-limit={args.max_seconds}",
        "--lp=0",
        "--verbosity=1",
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
        elif exact_marker(solver_text, "s TIMELIMIT"):
            termination = "solver-wall-ceiling"
        else:
            termination = "solver-error-or-unknown"

    proof_exists = proof_path.is_file()
    proof_bytes = proof_path.stat().st_size if proof_exists else 0
    proof_sha256 = sha256_file(proof_path) if proof_exists else None
    first_replay = None
    fresh_replay = None
    fresh_bogus = None
    replay_bindings = None
    if termination == "unsat" and proof_exists:
        first_replay = run_veripb(
            args.veripb,
            formula,
            proof_path,
            replay_log,
            args.max_verification_seconds,
        )
        replay_bindings = {
            "formula_sha256_unchanged": (
                sha256_file(formula) == metadata["opb"]["sha256"]
            ),
            "proof_sha256_unchanged": (
                sha256_file(proof_path) == proof_sha256
            ),
            "roundingsat_sha256_unchanged": True,
            "veripb_sha256_unchanged": True,
        }
        roundingsat_hash = sha256_file(args.roundingsat)
        veripb_hash = sha256_file(args.veripb)
        replay_bindings["roundingsat_sha256_unchanged"] = (
            sha256_file(args.roundingsat) == roundingsat_hash
        )
        replay_bindings["veripb_sha256_unchanged"] = (
            sha256_file(args.veripb) == veripb_hash
        )
        if first_replay["accepted_unsat"] and all(
            replay_bindings.values()
        ):
            fresh_replay = run_veripb(
                args.veripb,
                formula,
                proof_path,
                fresh_replay_log,
                args.max_verification_seconds,
            )
            fresh_bogus = bogus_control(
                args.veripb,
                lp63_formula,
                fresh_bogus_proof,
                fresh_bogus_log,
                args.max_verification_seconds,
            )

    accepted_twice = bool(
        first_replay
        and first_replay["accepted_unsat"]
        and fresh_replay
        and fresh_replay["accepted_unsat"]
    )
    fresh_bogus_rejected = bool(
        fresh_bogus and fresh_bogus["rejected_as_unsat"]
    )
    volume_gate = proof_bytes <= PROMOTION_PROOF_BYTES
    if accepted_twice and fresh_bogus_rejected and volume_gate:
        status = "gate-b-pass"
    elif accepted_twice and fresh_bogus_rejected:
        status = "proof-certified-unsat-volume-gate-fail"
    elif termination == "sat":
        status = "sat-needs-direct-witness-audit"
    else:
        status = "unknown"

    manifest = {
        "schema": "frontiermath-hadamard-lp333-native-pb-run-v1",
        "status": status,
        "family_id": family_id,
        "claim_boundary": (
            "Only gate-b-pass authorizes the identical static ID9 run; "
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
            "proof": {
                "exists": proof_exists,
                "bytes": proof_bytes,
                "sha256": proof_sha256,
            },
        },
        "proof_checks": {
            "first_bogus_lp63": first_bogus,
            "first_replay": first_replay,
            "fresh_replay_bindings": replay_bindings,
            "fresh_replay": fresh_replay,
            "fresh_bogus_lp63": fresh_bogus,
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
            "roundingsat": {
                "path": str(args.roundingsat),
                "source_repo": str(args.roundingsat_repo),
                "source_revision": git_revision(args.roundingsat_repo),
                "sha256": sha256_file(args.roundingsat),
                "version": command_version(
                    [str(args.roundingsat), "--help"]
                ),
            },
            "veripb": {
                "path": str(args.veripb),
                "source_repo": str(args.veripb_repo),
                "source_revision": git_revision(args.veripb_repo),
                "sha256": sha256_file(args.veripb),
                "version": command_version([str(args.veripb), "--version"]),
            },
        },
        "inputs": {
            "encoding_metadata": str(args.encoding_metadata),
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "formula_sha256": sha256_file(formula),
            "lp63_formula_sha256": sha256_file(lp63_formula),
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
