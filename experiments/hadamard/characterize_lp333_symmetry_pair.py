#!/usr/bin/env python3
"""Characterize the matched LP333 ID4/ID5 static-symmetry calibration runs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "experiments" / "hadamard" / "results"
OUTPUT = RESULTS / "lp333-id4-id5-symmetry-workload.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(pattern: str, text: str, *, flags: int = 0) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    if match is None:
        raise ValueError(f"missing required log pattern: {pattern}")
    return match


def parse_family(family_id: int) -> dict[str, object]:
    result_dir = RESULTS / f"lp333-id{family_id}-symmetry"
    manifest_path = result_dir / "calibration" / "run-manifest.json"
    metadata_path = result_dir / "encoding.json"
    log_path = result_dir / "calibration" / f"id{family_id}-cadical.log"
    manifest = json.loads(manifest_path.read_text())
    metadata = json.loads(metadata_path.read_text())
    log = log_path.read_text(errors="strict")

    if manifest["status"] != "unknown":
        raise ValueError(f"ID{family_id}: expected strict UNKNOWN")
    if sha256(log_path) != manifest["solver"]["log_sha256"]:
        raise ValueError(f"ID{family_id}: solver log hash does not match manifest")
    if sha256(metadata_path) != manifest["inputs"]["encoding_metadata_sha256"]:
        raise ValueError(f"ID{family_id}: encoding metadata hash does not match manifest")

    def profile(name: str) -> tuple[float, float]:
        found = require(
            rf"^\s*c\s+([0-9.]+)\s+([0-9.]+)%\s+{re.escape(name)}\s*$",
            log,
            flags=re.MULTILINE,
        )
        return float(found.group(1)), float(found.group(2))

    def count(name: str) -> int:
        found = require(
            rf"^\s*c\s+{re.escape(name)}:\s+([0-9]+)\b",
            log,
            flags=re.MULTILINE,
        )
        return int(found.group(1))

    search_seconds, search_percent = profile("search")
    simplify_seconds, simplify_percent = profile("simplify")
    stable_seconds, stable_percent = profile("stable")
    unstable_seconds, unstable_percent = profile("unstable")
    conflicts = count("conflicts")
    decisions = count("decisions")
    learned = count("learned")
    learned_literals = count("learned_lits")
    propagations = count("propagations")
    restarts = count("restarts")
    proof_added = int(
        require(r"^c DRAT ([0-9]+) added clauses", log, flags=re.MULTILINE).group(1)
    )
    proof_deleted = int(
        require(r"^c DRAT ([0-9]+) deleted clauses", log, flags=re.MULTILINE).group(1)
    )

    proof_bytes = manifest["solver"]["proof"]["bytes"]
    wall_seconds = manifest["solver"]["wall_seconds"]
    return {
        "family_id": family_id,
        "bindings": {
            "cnf_sha256": metadata["cnf"]["sha256"],
            "encoding_metadata_sha256": sha256(metadata_path),
            "manifest_sha256": sha256(manifest_path),
            "solver_log_sha256": sha256(log_path),
            "solver_sha256": manifest["tools"]["cadical"]["sha256"],
        },
        "formula": {
            "bytes": metadata["cnf"]["bytes"],
            "clauses": metadata["cnf"]["clauses"],
            "variables": metadata["cnf"]["variables"],
        },
        "outcome": {
            "status": "unknown",
            "termination": manifest["solver"]["termination"],
            "wall_seconds": wall_seconds,
            "proof_bytes": proof_bytes,
            "maximum_observed_rss_bytes": manifest["solver"][
                "maximum_observed_rss_bytes"
            ],
        },
        "profile": {
            "search_seconds": search_seconds,
            "search_percent": search_percent,
            "simplify_seconds": simplify_seconds,
            "simplify_percent": simplify_percent,
            "stable_seconds": stable_seconds,
            "stable_percent": stable_percent,
            "unstable_seconds": unstable_seconds,
            "unstable_percent": unstable_percent,
        },
        "counts": {
            "conflicts": conflicts,
            "decisions": decisions,
            "learned_clauses": learned,
            "learned_literals": learned_literals,
            "propagations": propagations,
            "restarts": restarts,
            "proof_added_clauses": proof_added,
            "proof_deleted_clauses": proof_deleted,
        },
        "rates": {
            "proof_bytes_per_wall_second": proof_bytes / wall_seconds,
            "proof_bytes_per_conflict": proof_bytes / conflicts,
            "learned_literals_per_conflict": learned_literals / conflicts,
            "propagations_per_conflict": propagations / conflicts,
            "conflicts_per_wall_second": conflicts / wall_seconds,
        },
    }


def main() -> None:
    id4 = parse_family(4)
    id5 = parse_family(5)
    ratio = lambda key: id5["rates"][key] / id4["rates"][key]  # noqa: E731

    artifact = {
        "schema": "frontiermath-hadamard-workload-characterization-v1",
        "evidence_unit": "matched LP333 ID4/ID5 static-symmetry calibration",
        "claim_boundary": (
            "This artifact characterizes two strict-UNKNOWN runs. It neither "
            "proves nor disproves either fixed multiplier family."
        ),
        "runs": {"id4": id4, "id5": id5},
        "matched_comparison": {
            "id5_over_id4": {
                "proof_output_rate": ratio("proof_bytes_per_wall_second"),
                "proof_bytes_per_conflict": ratio("proof_bytes_per_conflict"),
                "learned_literals_per_conflict": ratio(
                    "learned_literals_per_conflict"
                ),
                "propagations_per_conflict": ratio("propagations_per_conflict"),
                "maximum_observed_rss": (
                    id5["outcome"]["maximum_observed_rss_bytes"]
                    / id4["outcome"]["maximum_observed_rss_bytes"]
                ),
            },
            "shared_observations": [
                "Search occupies more than 83% of solver process time in both runs.",
                "Both runs generate over two million conflicts and over one billion propagations.",
                "Proof deletion records slightly exceed proof addition records in both runs.",
                "Both runs stay well below the preregistered 4 GiB memory ceiling.",
            ],
            "classification": {
                "id4": "search-bound at the 300 second wall ceiling",
                "id5": "search plus proof-output bound at the 1 GiB proof ceiling",
                "pair": (
                    "structural search reduction is required; merely raising or "
                    "compressing the proof-volume allowance does not create a "
                    "terminal mathematical result"
                ),
            },
        },
        "ranked_next_levers": [
            {
                "rank": 1,
                "lever": (
                    "Add independently audited compression-derived necessary "
                    "constraints to the same fixed-family formulas."
                ),
                "reason": (
                    "This attacks the shared search volume before proof emission "
                    "and can remain a static, checkable CNF transformation."
                ),
                "promotion_gate": (
                    "Exact derivation, semantic controls, formula bindings, and "
                    "fresh proof or direct-model verification."
                ),
            },
            {
                "rank": 2,
                "lever": (
                    "Prototype exact PAF-bound conflict reasons in a "
                    "proof-producing programmatic solver."
                ),
                "reason": (
                    "A specialized propagator can learn shorter problem-level "
                    "reasons than the generic PB encoding, but proof logging and "
                    "independent reason validation are substantial new machinery."
                ),
                "promotion_gate": (
                    "Every learned reason must be independently validated and "
                    "bound into a checker-accepted terminal certificate."
                ),
            },
            {
                "rank": 3,
                "lever": "Use binary or compressed proof output only as plumbing.",
                "reason": (
                    "It may prevent ID5's storage ceiling but does not address "
                    "ID4's wall ceiling or reduce conflict search."
                ),
                "promotion_gate": "No promotion without complete independent replay.",
            },
        ],
        "do_not_promote": [
            "A resource ceiling as evidence for SAT or UNSAT.",
            "A different random seed as the next scientific lever.",
            "A smaller proof file without complete independent replay.",
            "Unlogged programmatic pruning.",
        ],
    }
    OUTPUT.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(OUTPUT)
    print(sha256(OUTPUT))


if __name__ == "__main__":
    main()
