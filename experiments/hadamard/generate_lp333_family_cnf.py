#!/usr/bin/env python3
"""Generate a deterministic proof-producing CNF for one LP333 family."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_encoder(source_repo: Path):
    proof_dir = source_repo.resolve() / "lp333" / "proof_phase2"
    encoder_path = proof_dir / "lp333_cnf.py"
    sys.path.insert(0, str(proof_dir))
    module = importlib.import_module("lp333_cnf")
    return module, encoder_path


def load_source_family(
    source_repo: Path, family_id: int
) -> tuple[dict[str, Any], Path, Path]:
    classification_path = (
        source_repo / "lp333" / "results" / "subgroup_classification.json"
    )
    status_path = source_repo / "lp333" / "results" / "master_status.json"
    classification = json.loads(
        classification_path.read_text(encoding="utf-8")
    )
    statuses = json.loads(status_path.read_text(encoding="utf-8"))
    subgroup = next(
        record
        for record in classification["subgroups"]
        if record["id"] == family_id
    )
    status = next(
        record
        for record in statuses["families"]
        if record["id"] == family_id
    )
    if status["status"] != "OPEN":
        raise ValueError(f"family {family_id} is not source-OPEN")
    if subgroup["elements"] != status.get(
        "elements", subgroup["elements"]
    ):
        raise ValueError("source family records disagree")
    return (
        {
            "classification": subgroup,
            "status": status,
        },
        classification_path,
        status_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family-id", required=True, type=int)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--random-equivalence-samples", type=int, default=100)
    args = parser.parse_args()
    if args.family_id not in (9, 10):
        raise ValueError("this preregistered twin generator accepts ID9 or ID10")
    if args.random_equivalence_samples <= 0:
        raise ValueError("random-equivalence sample count must be positive")

    source_family, classification_path, status_path = load_source_family(
        args.source_repo, args.family_id
    )
    encoder, encoder_path = load_encoder(args.source_repo)
    model, encoder_record = encoder.build_lp333_model(args.family_id)
    if encoder_record["elements"] != source_family["classification"]["elements"]:
        raise ValueError("proof encoder selected a different subgroup")
    if model.direct_pb_obstructions:
        raise ValueError(
            f"family has direct PB shortfalls: {model.direct_pb_obstructions}"
        )

    transformation_audit = encoder.transformation_truth_table_audit()
    small_model = encoder.build_singleton_model(7)
    small_exhaustive = encoder.exhaustive_small_audit(small_model)
    random_equivalence = encoder.random_equivalence_audit(
        model,
        args.random_equivalence_samples,
        20260726 + args.family_id,
    )
    if not all(
        audit["result"] == "PASS"
        for audit in (
            transformation_audit,
            small_exhaustive,
            random_equivalence,
        )
    ):
        raise ValueError("proof-encoder semantic controls did not pass")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cnf_path = args.output_dir / f"id{args.family_id}.cnf"
    metadata_path = args.output_dir / "encoding.json"
    for path in (cnf_path, metadata_path):
        if path.exists():
            raise ValueError(f"refusing to overwrite {path}")
    serialization = encoder.write_dimacs(
        model.builder, cnf_path, split_unit_clauses=True
    )
    deterministic_hash = encoder.dimacs_sha256(
        model.builder, split_unit_clauses=True
    )
    cnf_hash = sha256_file(cnf_path)
    if cnf_hash != deterministic_hash:
        raise ValueError("written and in-memory DIMACS hashes differ")

    metadata = {
        "schema": "frontiermath-hadamard-lp333-family-cnf-v1",
        "status": "generated",
        "family_id": args.family_id,
        "claim_boundary": (
            "SAT requires direct verification of both length-333 sequences; "
            "UNSAT requires replay of the exact proof; every ceiling stays "
            "UNKNOWN"
        ),
        "subgroup": {
            "order": len(encoder_record["elements"]),
            "elements": encoder_record["elements"],
            "generators": source_family["classification"]["generators"],
            "orbit_count": model.spec["r"],
            "orbit_signature": source_family["classification"][
                "orbit_signature"
            ],
            "orbits": model.spec["orbits"],
            "shift_representatives": model.spec["reps"],
        },
        "circuit": {
            "builder_variables": model.builder.num_vars,
            "builder_clauses": len(model.builder.clauses),
            "used_pairs_per_sequence": model.pair_count,
            "representative_paf_equations": len(model.paf_bits),
            "direct_pb_obstructions": model.direct_pb_obstructions,
        },
        "primary_variables": {
            "meaning": "z=0 is orbit sign +1; z=1 is orbit sign -1",
            "za": model.za,
            "zb": model.zb,
        },
        "cnf": {
            "path": str(cnf_path),
            "variables": serialization["num_variables"],
            "clauses": serialization["num_clauses"],
            "bytes": cnf_path.stat().st_size,
            "sha256": cnf_hash,
            "unit_split_count": serialization["unit_split_count"],
        },
        "controls": {
            "transformation_truth_tables": transformation_audit,
            "small_exhaustive": small_exhaustive,
            "random_semantic_cnf_equivalence": random_equivalence,
        },
        "inputs": {
            "proof_encoder": str(encoder_path),
            "proof_encoder_sha256": sha256_file(encoder_path),
            "subgroup_classification": str(classification_path),
            "subgroup_classification_sha256": sha256_file(
                classification_path
            ),
            "master_status": str(status_path),
            "master_status_sha256": sha256_file(status_path),
        },
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "family_id": args.family_id,
                "cnf": metadata["cnf"],
                "circuit": metadata["circuit"],
                "metadata_sha256": sha256_file(metadata_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
