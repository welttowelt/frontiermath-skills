#!/usr/bin/env python3
"""Independently check one complete-static-symmetry LP333 result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import verify_lp333_symmetry_results as checker


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--family-id", required=True, type=int)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    encoder = checker.load_encoder(args.source_repo)
    output = {
        "schema": "frontiermath-lp333-symmetry-family-check-v1",
        "status": "pass",
        "lex_leader_truth_table": checker.exhaustive_lex_truth_table(),
        "family": checker.verify_family(
            encoder,
            args.family_id,
            args.metadata,
            args.manifest,
        ),
        "inputs": {
            "metadata_sha256": sha256_file(args.metadata),
            "manifest_sha256": sha256_file(args.manifest),
        },
        "verifier_sha256": sha256_file(Path(__file__).resolve()),
        "shared_independent_kernel_sha256": sha256_file(
            Path(checker.__file__).resolve()
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
