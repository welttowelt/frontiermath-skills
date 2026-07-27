# ID3 prescribed-profile proof batch

This directory contains the durable records for the proof-certified negative
partition of the refined 95-cell ID3 compression ledger.

Result:

- `52/52` formerly CP-SAT-negative cells have replayed DRAT proofs;
- `batch-manifest.json` SHA-256:
  `614f4f333ebb00d3aa8b637744d18f25e8a5a44cad36ae1ae3875bc866734748`;
- `full-replay-audit.json` SHA-256:
  `bf81b54991f2e88c026a3745ade7fda4e4f404d92b41887d751d8406d6632e76`;
- the full local proof payload is about `1.2 GB`.

The generated CNFs, proofs, logs, and solver model files are intentionally
ignored by Git to prevent accidental staging of the large payload. They remain
in this local directory and are bound by SHA-256 in the manifests. Encoding
metadata and audit records remain trackable.

## Tool pins

- CaDiCaL repository: <https://github.com/arminbiere/cadical>
- tag: `rel-3.0.1`
- commit: `c60730422e758ef1cebe7aeddf2dda31c996bf04`
- independent checker source SHA-256:
  `d834b649f437e091597f5347f259b9f681087f89ca0844d0cee250a1a1a0c2ee`

The checker source and binary used here are under the pinned LP333 artifact:

`hadamard-668-multiplier-obstructions/lp333/proof_phase2/tools/drat-trim/`.

## Reproduce the batch

From the `frontiermath-skills` repository:

```text
.venv/bin/python experiments/hadamard/run_id3_profile_proof_batch.py \
  --ledger experiments/hadamard/results/id3-prescribed-profile-ledger-refined.json \
  --gate-a-manifest experiments/hadamard/results/id3-profile-proof-pilot/pilot-manifest.json \
  --output-dir experiments/hadamard/results/id3-profile-proof-batch \
  --cadical /path/to/cadical-3.0.1/build/cadical \
  --drat-trim /path/to/hadamard-668-multiplier-obstructions/lp333/proof_phase2/tools/drat-trim/drat-trim \
  --solver-timeout 300 \
  --replay-timeout 300
```

## Fresh independent replay

```text
.venv/bin/python experiments/hadamard/verify_id3_profile_proof_batch.py \
  --manifest experiments/hadamard/results/id3-profile-proof-batch/batch-manifest.json \
  --ledger experiments/hadamard/results/id3-prescribed-profile-ledger-refined.json \
  --drat-trim /path/to/hadamard-668-multiplier-obstructions/lp333/proof_phase2/tools/drat-trim/drat-trim \
  --output experiments/hadamard/results/id3-profile-proof-batch/full-replay-audit.json \
  --full
```

This evidence concerns named compressed profile cells only. It does not close
ID3, unrestricted LP(333), or H(668).
