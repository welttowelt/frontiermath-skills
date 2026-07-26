#!/usr/bin/env python3
"""Proof-certify the refined ledger's CP-SAT-negative id3 cells."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from generate_id3_profile_cell_cnf import EXPECTED_LEDGER_SHA256, generate
from run_id3_profile_proof_pilot import (
    file_record,
    run_python,
    run_timed,
    sha256_file,
)


CLAUSE_CEILING = 2_000_000
PROOF_BYTE_CEILING = 5 * 1024**3
REPLAY_SECONDS_CEILING = 7200
MEMORY_BYTE_CEILING = 12 * 1024**3


def write_manifest(path: Path, document: dict[str, object]) -> None:
    records = document["records"]
    assert isinstance(records, list)
    counts = Counter(record["status"] for record in records)
    document["processed_cells"] = len(records)
    document["status_counts"] = dict(sorted(counts.items()))
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--gate-a-manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cadical", required=True, type=Path)
    parser.add_argument("--drat-trim", required=True, type=Path)
    parser.add_argument("--solver-timeout", type=int, default=300)
    parser.add_argument("--replay-timeout", type=int, default=300)
    parser.add_argument("--max-cells", type=int)
    args = parser.parse_args()

    if not args.cadical.is_file():
        raise SystemExit(f"missing CaDiCaL binary: {args.cadical}")
    if not args.drat_trim.is_file():
        raise SystemExit(f"missing drat-trim binary: {args.drat_trim}")
    if sha256_file(args.ledger) != EXPECTED_LEDGER_SHA256:
        raise SystemExit("refined ledger hash mismatch")

    gate_a = json.loads(args.gate_a_manifest.read_text(encoding="utf-8"))
    if gate_a.get("status") != "pass":
        raise SystemExit("Gate A manifest is not passing")
    bogus = gate_a.get("bogus_proof_control")
    if not isinstance(bogus, dict) or bogus.get("rejected") is not True:
        raise SystemExit("Gate A bogus-proof rejection is absent")

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    raw_records = ledger.get("records")
    if not isinstance(raw_records, list):
        raise SystemExit("refined ledger has no records")
    negative_records = [
        record
        for record in raw_records
        if isinstance(record, dict)
        and record.get("status") == "INFEASIBLE"
        and record.get("feasible") is False
    ]
    if len(negative_records) != 52:
        raise SystemExit(
            f"expected 52 solver-negative cells, found {len(negative_records)}"
        )
    negative_records.sort(
        key=lambda record: (
            float(record.get("wall_seconds", float("inf"))),
            int(record.get("branches", 1 << 60)),
            int(record["id"]),
        )
    )
    if args.max_cells is not None:
        negative_records = negative_records[: args.max_cells]

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "batch-manifest.json"
    script_dir = Path(__file__).resolve().parent
    direct_checker = script_dir / "verify_id3_profile_cell_model.py"
    started = time.perf_counter()
    manifest: dict[str, object] = {
        "schema": "frontiermath-hadamard-id3-profile-proof-batch-v1",
        "status": "running",
        "claim_boundary": (
            "individual compressed profile cells only; this does not close "
            "id3, unrestricted LP(333), or H(668)"
        ),
        "refined_ledger_sha256": EXPECTED_LEDGER_SHA256,
        "gate_a_manifest": file_record(args.gate_a_manifest),
        "ordered_negative_cell_ids": [
            int(record["id"]) for record in negative_records
        ],
        "negative_cells_in_refined_ledger": 52,
        "budget": {
            "clause_ceiling_per_cell": CLAUSE_CEILING,
            "proof_byte_ceiling": PROOF_BYTE_CEILING,
            "replay_wall_seconds_ceiling": REPLAY_SECONDS_CEILING,
            "memory_byte_ceiling": MEMORY_BYTE_CEILING,
            "bounded_solver_timeout_seconds": args.solver_timeout,
            "bounded_replay_timeout_seconds": args.replay_timeout,
            "stop_after_resource_exceedances": 2,
        },
        "tools": {
            "cadical": {
                "path": str(args.cadical),
                "version": subprocess.run(
                    [str(args.cadical), "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip(),
                "binary_sha256": sha256_file(args.cadical),
                "source_repository": "https://github.com/arminbiere/cadical",
                "source_tag": "rel-3.0.1",
                "source_commit": (
                    "c60730422e758ef1cebe7aeddf2dda31c996bf04"
                ),
            },
            "drat_trim": {
                "path": str(args.drat_trim),
                "binary_sha256": sha256_file(args.drat_trim),
                "source_sha256": sha256_file(
                    args.drat_trim.parent / "drat-trim.c"
                ),
            },
        },
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "records": [],
    }
    write_manifest(manifest_path, manifest)

    resource_exceedances = 0
    for ledger_record in negative_records:
        cell_id = int(ledger_record["id"])
        stem = f"id3-profile-cell-{cell_id:02d}"
        cnf_path = output_dir / f"{stem}.cnf"
        metadata_path = output_dir / f"{stem}-encoding.json"
        proof_path = output_dir / f"{stem}.drat"
        model_path = output_dir / f"{stem}.model"
        solver_log = output_dir / f"{stem}-cadical.log"
        proof_path.unlink(missing_ok=True)
        model_path.unlink(missing_ok=True)

        encoding = generate(
            args.ledger, cell_id, cnf_path, metadata_path
        )
        record: dict[str, object] = {
            "cell_id": cell_id,
            "prior_solver_status": ledger_record["status"],
            "prior_solver_wall_seconds": ledger_record.get("wall_seconds"),
            "encoding": {
                key: encoding[key]
                for key in (
                    "cnf_sha256",
                    "cnf_bytes",
                    "variables",
                    "clauses",
                    "square_counts",
                )
            },
            "encoding_metadata": file_record(metadata_path),
        }
        if int(encoding["clauses"]) >= CLAUSE_CEILING:
            record["status"] = "ENCODING_BUDGET_EXCEEDED"
            resource_exceedances += 1
            manifest["records"].append(record)
            write_manifest(manifest_path, manifest)
            if resource_exceedances >= 2:
                break
            continue

        solver = run_timed(
            [
                str(args.cadical),
                "--binary=false",
                "--factor=false",
                "--checkproof=1",
                "--checkwitness=true",
                "-q",
                "-w",
                str(model_path),
                str(cnf_path),
                str(proof_path),
            ],
            solver_log,
            args.solver_timeout,
            {10, 20},
        )
        record["solver"] = solver

        if solver["timed_out"]:
            record["status"] = "UNKNOWN_SOLVER_TIMEOUT"
            resource_exceedances += 1
        elif solver["returncode"] == 20 and proof_path.is_file():
            replay_log = output_dir / f"{stem}-drat-trim.log"
            replay = run_timed(
                [
                    str(args.drat_trim),
                    str(cnf_path),
                    str(proof_path),
                    "-I",
                ],
                replay_log,
                args.replay_timeout,
                {0},
            )
            replay_text = replay_log.read_text(encoding="utf-8")
            replay["verified_marker"] = "s VERIFIED" in replay_text
            replay["accepted"] = bool(
                replay["accepted"] and replay["verified_marker"]
            )
            record["proof"] = file_record(proof_path)
            record["independent_replay"] = replay
            over_budget = (
                proof_path.stat().st_size >= PROOF_BYTE_CEILING
                or replay["wall_seconds"] >= REPLAY_SECONDS_CEILING
                or (
                    replay["maximum_resident_set_size_bytes"] is not None
                    and replay["maximum_resident_set_size_bytes"]
                    >= MEMORY_BYTE_CEILING
                )
            )
            if replay["accepted"] and not over_budget:
                record["status"] = "PROOF_CERTIFIED_INFEASIBLE"
            elif replay["accepted"]:
                record["status"] = "PROOF_CERTIFIED_BUDGET_EXCEEDED"
                resource_exceedances += 1
            else:
                record["status"] = "PROOF_REPLAY_FAILED"
                resource_exceedances += 1
        elif solver["returncode"] == 10 and model_path.is_file():
            verification_path = output_dir / (
                f"{stem}-model-verification.json"
            )
            witness_path = output_dir / f"{stem}-witness.json"
            verification_log = output_dir / (
                f"{stem}-model-verification.log"
            )
            verification = run_python(
                [
                    sys.executable,
                    str(direct_checker),
                    "--metadata",
                    str(metadata_path),
                    "--cnf",
                    str(cnf_path),
                    "--model",
                    str(model_path),
                    "--output",
                    str(verification_path),
                    "--witness-output",
                    str(witness_path),
                ],
                verification_log,
            )
            record["model"] = file_record(model_path)
            record["model_verification_run"] = verification
            record["model_verification"] = (
                file_record(verification_path)
                if verification_path.is_file()
                else None
            )
            record["witness"] = (
                file_record(witness_path) if witness_path.is_file() else None
            )
            record["status"] = (
                "SAT_MODEL_VERIFIED"
                if verification["accepted"]
                else "SAT_MODEL_REJECTED"
            )
            resource_exceedances += 1
        else:
            record["status"] = "SOLVER_ERROR"
            resource_exceedances += 1

        manifest["records"].append(record)
        manifest["resource_exceedances"] = resource_exceedances
        manifest["runtime_seconds"] = time.perf_counter() - started
        write_manifest(manifest_path, manifest)
        print(
            f"cell {cell_id:02d}: {record['status']} "
            f"({solver['wall_seconds']:.3f}s solver)",
            flush=True,
        )
        if resource_exceedances >= 2:
            break

    records = manifest["records"]
    assert isinstance(records, list)
    certified = [
        record
        for record in records
        if record["status"] == "PROOF_CERTIFIED_INFEASIBLE"
    ]
    all_requested_processed = len(records) == len(negative_records)
    all_processed_certified = len(certified) == len(records)
    manifest["status"] = (
        "complete-proof-certified"
        if all_requested_processed and all_processed_certified
        else "bounded-partial"
    )
    manifest["proof_certified_cell_ids"] = [
        record["cell_id"] for record in certified
    ]
    manifest["all_requested_processed"] = all_requested_processed
    manifest["resource_exceedances"] = resource_exceedances
    manifest["runtime_seconds"] = time.perf_counter() - started
    write_manifest(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "processed_cells": manifest["processed_cells"],
                "status_counts": manifest["status_counts"],
                "resource_exceedances": resource_exceedances,
                "manifest": str(manifest_path),
                "manifest_sha256": sha256_file(manifest_path),
                "runtime_seconds": manifest["runtime_seconds"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
