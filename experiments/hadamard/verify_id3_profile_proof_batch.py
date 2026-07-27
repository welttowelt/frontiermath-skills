#!/usr/bin/env python3
"""Independently audit and optionally replay an id3 proof-cell batch."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path


EXPECTED_LEDGER_SHA256 = (
    "1760d0337f518fe7b6bc79bbd619d3ea07ba093c810f81cc9fe5bf8bd44f0532"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_file(
    record: object,
    label: str,
    errors: list[str],
) -> Path | None:
    if not isinstance(record, dict):
        errors.append(f"{label}: file record is not an object")
        return None
    raw_path = record.get("path")
    if not isinstance(raw_path, str):
        errors.append(f"{label}: missing path")
        return None
    path = Path(raw_path)
    if not path.is_file():
        errors.append(f"{label}: missing file {path}")
        return None
    actual_hash = sha256_file(path)
    if actual_hash != record.get("sha256"):
        errors.append(f"{label}: SHA-256 mismatch")
    if path.stat().st_size != record.get("bytes"):
        errors.append(f"{label}: byte-size mismatch")
    return path


def replay(
    checker: Path,
    cnf: Path,
    proof: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    command = ["/usr/bin/time", "-l", str(checker), str(cnf), str(proof), "-I"]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        timed_out = False
        returncode = completed.returncode
        output = completed.stdout + "\n" + completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        returncode = None
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        output = stdout + "\n" + stderr
    elapsed = time.perf_counter() - started
    resident_match = re.search(
        r"^\s*(\d+)\s+maximum resident set size\s*$",
        output,
        flags=re.MULTILINE,
    )
    return {
        "returncode": returncode,
        "timed_out": timed_out,
        "verified_marker": "s VERIFIED" in output,
        "accepted": (
            not timed_out
            and returncode == 0
            and "s VERIFIED" in output
        ),
        "wall_seconds": elapsed,
        "maximum_resident_set_size_bytes": (
            int(resident_match.group(1)) if resident_match else None
        ),
        "output_sha256": hashlib.sha256(
            output.encode("utf-8")
        ).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--drat-trim", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--timeout-per-proof", type=int, default=7200)
    args = parser.parse_args()

    started = time.perf_counter()
    errors: list[str] = []
    manifest_hash = sha256_file(args.manifest)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    ledger_hash = sha256_file(args.ledger)
    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))

    if manifest.get("status") != "complete-proof-certified":
        errors.append("batch manifest is not complete-proof-certified")
    if ledger_hash != EXPECTED_LEDGER_SHA256:
        errors.append("refined ledger hash mismatch")
    if manifest.get("refined_ledger_sha256") != ledger_hash:
        errors.append("manifest is not bound to the supplied ledger")

    ledger_records = ledger.get("records")
    if not isinstance(ledger_records, list):
        errors.append("ledger has no records list")
        ledger_records = []
    expected_ids = {
        int(record["id"])
        for record in ledger_records
        if isinstance(record, dict)
        and record.get("status") == "INFEASIBLE"
        and record.get("feasible") is False
    }
    if len(expected_ids) != 52:
        errors.append(f"ledger has {len(expected_ids)} negative cells, not 52")

    records = manifest.get("records")
    if not isinstance(records, list):
        errors.append("manifest has no records list")
        records = []
    actual_ids = {
        int(record["cell_id"])
        for record in records
        if isinstance(record, dict) and "cell_id" in record
    }
    if actual_ids != expected_ids or len(records) != 52:
        errors.append("manifest cells do not equal the 52 ledger negatives")

    tool_record = manifest.get("tools")
    if not isinstance(tool_record, dict):
        errors.append("manifest has no tool records")
        tool_record = {}
    drat_record = tool_record.get("drat_trim")
    if not isinstance(drat_record, dict):
        errors.append("manifest has no drat-trim record")
        drat_record = {}
    if not args.drat_trim.is_file():
        errors.append("supplied drat-trim binary is missing")
    elif sha256_file(args.drat_trim) != drat_record.get("binary_sha256"):
        errors.append("supplied drat-trim binary hash mismatch")
    checker_source = args.drat_trim.parent / "drat-trim.c"
    if not checker_source.is_file():
        errors.append("drat-trim source is missing")
    elif sha256_file(checker_source) != drat_record.get("source_sha256"):
        errors.append("drat-trim source hash mismatch")

    gate_a_path = checked_file(
        manifest.get("gate_a_manifest"), "gate A manifest", errors
    )
    bogus_cnf = None
    bogus_proof = None
    if gate_a_path is not None:
        gate_a = json.loads(gate_a_path.read_text(encoding="utf-8"))
        if gate_a.get("status") != "pass":
            errors.append("gate A status is not pass")
        cell_73 = gate_a.get("cell_73")
        if isinstance(cell_73, dict):
            encoding = cell_73.get("encoding")
            if isinstance(encoding, dict):
                raw_cnf = encoding.get("cnf")
                if isinstance(raw_cnf, str):
                    bogus_cnf = Path(raw_cnf)
            # Older manifests keep the CNF path only in encoding metadata.
            metadata_record = cell_73.get("encoding_metadata")
            metadata_path = checked_file(
                metadata_record, "gate A cell 73 metadata", errors
            )
            if metadata_path is not None:
                metadata = json.loads(
                    metadata_path.read_text(encoding="utf-8")
                )
                bogus_cnf = Path(metadata["cnf"])
            checked_file(cell_73.get("model"), "gate A cell 73 model", errors)
            direct_path = checked_file(
                cell_73.get("direct_model_verification"),
                "gate A direct verification",
                errors,
            )
            arithmetic_path = checked_file(
                cell_73.get("arithmetic_verification"),
                "gate A arithmetic verification",
                errors,
            )
            for label, path in (
                ("direct", direct_path),
                ("arithmetic", arithmetic_path),
            ):
                if path is not None:
                    document = json.loads(path.read_text(encoding="utf-8"))
                    if document.get("status") != "pass":
                        errors.append(f"gate A {label} verification did not pass")
        bogus_record = gate_a.get("bogus_proof_control")
        if isinstance(bogus_record, dict):
            bogus_proof = checked_file(
                bogus_record.get("proof"), "gate A bogus proof", errors
            )
            if bogus_record.get("rejected") is not True:
                errors.append("gate A did not reject the bogus proof")

    replay_results = []
    total_proof_bytes = 0
    for record in records:
        if not isinstance(record, dict):
            errors.append("batch record is not an object")
            continue
        cell_id = int(record["cell_id"])
        if record.get("status") != "PROOF_CERTIFIED_INFEASIBLE":
            errors.append(f"cell {cell_id}: status is not proof certified")
        metadata_path = checked_file(
            record.get("encoding_metadata"),
            f"cell {cell_id} metadata",
            errors,
        )
        proof_path = checked_file(
            record.get("proof"), f"cell {cell_id} proof", errors
        )
        encoding = record.get("encoding")
        if not isinstance(encoding, dict):
            errors.append(f"cell {cell_id}: missing encoding")
            continue
        raw_metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path is not None
            else {}
        )
        raw_cnf = raw_metadata.get("cnf")
        if not isinstance(raw_cnf, str):
            errors.append(f"cell {cell_id}: metadata has no CNF path")
            continue
        cnf_path = Path(raw_cnf)
        if not cnf_path.is_file():
            errors.append(f"cell {cell_id}: CNF is missing")
            continue
        cnf_hash = sha256_file(cnf_path)
        if (
            cnf_hash != encoding.get("cnf_sha256")
            or cnf_hash != raw_metadata.get("cnf_sha256")
        ):
            errors.append(f"cell {cell_id}: CNF hash mismatch")
        if cnf_path.stat().st_size != encoding.get("cnf_bytes"):
            errors.append(f"cell {cell_id}: CNF byte-size mismatch")
        if raw_metadata.get("cell_id") != cell_id:
            errors.append(f"cell {cell_id}: metadata cell mismatch")
        if raw_metadata.get("refined_ledger_sha256") != ledger_hash:
            errors.append(f"cell {cell_id}: metadata ledger binding mismatch")

        if proof_path is not None:
            total_proof_bytes += proof_path.stat().st_size
        prior_replay = record.get("independent_replay")
        if (
            not isinstance(prior_replay, dict)
            or prior_replay.get("accepted") is not True
            or prior_replay.get("verified_marker") is not True
        ):
            errors.append(f"cell {cell_id}: saved replay status is not accepted")

        if args.full and proof_path is not None and args.drat_trim.is_file():
            replay_result = replay(
                args.drat_trim,
                cnf_path,
                proof_path,
                args.timeout_per_proof,
            )
            replay_result["cell_id"] = cell_id
            replay_results.append(replay_result)
            if not replay_result["accepted"]:
                errors.append(f"cell {cell_id}: fresh proof replay failed")
            print(
                f"cell {cell_id:02d}: "
                f"{'VERIFIED' if replay_result['accepted'] else 'FAILED'} "
                f"{replay_result['wall_seconds']:.3f}s",
                flush=True,
            )

    bogus_replay = None
    if (
        args.full
        and bogus_cnf is not None
        and bogus_proof is not None
        and args.drat_trim.is_file()
    ):
        bogus_replay = replay(
            args.drat_trim,
            bogus_cnf,
            bogus_proof,
            min(args.timeout_per_proof, 300),
        )
        bogus_replay["rejected"] = not bogus_replay["accepted"]
        if not bogus_replay["rejected"]:
            errors.append("fresh bogus-proof control was accepted")

    result = {
        "schema": "frontiermath-hadamard-id3-profile-proof-batch-audit-v1",
        "status": "pass" if not errors else "fail",
        "mode": "full-replay" if args.full else "hash-and-manifest",
        "manifest_sha256": manifest_hash,
        "refined_ledger_sha256": ledger_hash,
        "checker_binary_sha256": (
            sha256_file(args.drat_trim)
            if args.drat_trim.is_file()
            else None
        ),
        "checker_source_sha256": (
            sha256_file(checker_source)
            if checker_source.is_file()
            else None
        ),
        "cells_expected": 52,
        "cells_checked": len(records),
        "total_proof_bytes": total_proof_bytes,
        "fresh_replay_count": len(replay_results),
        "fresh_replays": replay_results,
        "fresh_bogus_proof_control": bogus_replay,
        "errors": errors,
        "runtime_seconds": time.perf_counter() - started,
        "auditor_sha256": sha256_file(Path(__file__).resolve()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "mode": result["mode"],
                "cells_checked": result["cells_checked"],
                "fresh_replay_count": result["fresh_replay_count"],
                "fresh_bogus_proof_control": result[
                    "fresh_bogus_proof_control"
                ],
                "errors": result["errors"],
                "runtime_seconds": result["runtime_seconds"],
                "output": str(args.output),
                "output_sha256": sha256_file(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
