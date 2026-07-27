#!/usr/bin/env python3
"""Freshly replay and audit a proof-certified LP333 family run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import time
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_checker(
    checker: Path,
    cnf: Path,
    proof: Path,
    log_path: Path,
    timeout: float,
) -> dict[str, Any]:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    with log_path.open("wb") as log:
        try:
            process = subprocess.run(
                [str(checker), str(cnf), str(proof), "-I"],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            returncode = process.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            returncode = None
            timed_out = True
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "accepted": returncode == 0 and "VERIFIED" in text,
        "returncode": returncode,
        "timed_out": timed_out,
        "verified_marker": "VERIFIED" in text,
        "wall_seconds": time.perf_counter() - started,
        "maximum_resident_set_size_bytes": max(
            0, int(after.ru_maxrss - before.ru_maxrss)
        ),
        "log_sha256": sha256_file(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("encoding_metadata", type=Path)
    parser.add_argument("cnf_audit", type=Path)
    parser.add_argument("run_manifest", type=Path)
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--checker", required=True, type=Path)
    parser.add_argument("--sat-control-cnf", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=7200.0)
    args = parser.parse_args()
    if args.max_seconds <= 0:
        raise ValueError("replay ceiling must be positive")
    if not args.checker.is_file() or not os.access(args.checker, os.X_OK):
        raise ValueError("proof checker is missing or not executable")

    metadata = json.loads(
        args.encoding_metadata.read_text(encoding="utf-8")
    )
    cnf_audit = json.loads(args.cnf_audit.read_text(encoding="utf-8"))
    manifest = json.loads(args.run_manifest.read_text(encoding="utf-8"))
    cnf = Path(metadata["cnf"]["path"])
    family_id = metadata["family_id"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    replay_log = args.output_dir / "fresh-drat-trim.log"
    bogus_proof = args.output_dir / "fresh-bogus-empty.drat"
    bogus_log = args.output_dir / "fresh-bogus-empty.log"
    for path in (replay_log, bogus_proof, bogus_log, args.output):
        if path.exists():
            raise ValueError(f"refusing to overwrite {path}")

    binding_checks = {
        "family_id": (
            manifest.get("family_id") == family_id
            and cnf_audit.get("family_id") == family_id
        ),
        "formula_audit_pass": (
            cnf_audit.get("status") == "pass"
            and all(cnf_audit.get("checks", {}).values())
        ),
        "metadata_hash": (
            manifest["inputs"]["encoding_metadata_sha256"]
            == sha256_file(args.encoding_metadata)
        ),
        "cnf_audit_hash": (
            manifest["inputs"]["cnf_audit_sha256"]
            == sha256_file(args.cnf_audit)
        ),
        "cnf_hash": (
            metadata["cnf"]["sha256"]
            == sha256_file(cnf)
            == manifest["inputs"]["cnf_sha256"]
        ),
        "proof_hash": (
            sha256_file(args.proof)
            == manifest["solver"]["proof"]["sha256"]
        ),
        "proof_size": (
            args.proof.stat().st_size
            == manifest["solver"]["proof"]["bytes"]
        ),
        "solver_unsat": (
            manifest["solver"]["returncode"] == 20
            and manifest["solver"]["termination"] == "unsat"
        ),
        "first_replay_accepted": (
            manifest.get("proof_replay", {}).get("accepted") is True
        ),
        "manifest_status": (
            manifest.get("status") == "proof-certified-unsat"
        ),
        "checker_hash": (
            manifest["tools"]["drat_trim"]["sha256"]
            == sha256_file(args.checker)
        ),
        "first_bogus_proof_rejected": (
            manifest.get("bogus_proof_control", {}).get("rejected") is True
        ),
    }
    if not all(binding_checks.values()):
        raise ValueError(f"run binding checks failed: {binding_checks}")

    fresh_replay = run_checker(
        args.checker,
        cnf,
        args.proof,
        replay_log,
        args.max_seconds,
    )
    bogus_proof.write_bytes(b"")
    fresh_bogus = run_checker(
        args.checker,
        args.sat_control_cnf,
        bogus_proof,
        bogus_log,
        min(args.max_seconds, 120.0),
    )
    fresh_bogus_rejected = not fresh_bogus["accepted"]
    checks = {
        **binding_checks,
        "fresh_replay_accepted": fresh_replay["accepted"],
        "fresh_bogus_proof_rejected": fresh_bogus_rejected,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-hadamard-lp333-family-run-audit-v1",
        "status": status,
        "family_id": family_id,
        "result": (
            f"family ID{family_id} is proof-certified infeasible"
            if status == "pass"
            else "audit failed; no family promotion"
        ),
        "claim_boundary": (
            "This closes only the named fixed family and, through the separate "
            "affine-normalization theorem, its coherent translated versions. "
            "It does not close another multiplier family, unrestricted "
            "LP(333), or H(668)."
        ),
        "checks": checks,
        "fresh_replay": fresh_replay,
        "fresh_bogus_control": {
            **fresh_bogus,
            "rejected": fresh_bogus_rejected,
            "empty_proof_sha256": sha256_file(bogus_proof),
        },
        "inputs": {
            "encoding_metadata_sha256": sha256_file(
                args.encoding_metadata
            ),
            "cnf_audit_sha256": sha256_file(args.cnf_audit),
            "run_manifest_sha256": sha256_file(args.run_manifest),
            "cnf_sha256": sha256_file(cnf),
            "proof_sha256": sha256_file(args.proof),
            "checker_sha256": sha256_file(args.checker),
            "sat_control_cnf_sha256": sha256_file(args.sat_control_cnf),
        },
        "auditor_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": status,
                "family_id": family_id,
                "checks": checks,
                "fresh_replay": fresh_replay,
                "fresh_bogus_control": output["fresh_bogus_control"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
