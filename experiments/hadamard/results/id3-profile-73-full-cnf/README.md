# ID3 profile-73 full CNF

This directory records the preregistered Gate C attempt for one exact
full-PAF profile-73 slice. The terminal status is
`unknown-resource-ceiling`: it is neither SAT nor UNSAT evidence.

## Exact formula

- variables: `161,536`
- clauses: `1,135,539`
- DIMACS bytes: `70,063,698`
- DIMACS SHA-256:
  `813e645a075234fe432ac8c89e320981560fc1ced75598891e31ef1c20e88d60`
- full ID3 PAF equations: `116`
- profile-specific learned prune clauses: `55,517`
- learned-clause length: minimum `174`, median `191`, mean `191.1078`,
  maximum `216`
- canonical learned-clause SHA-256:
  `0411d6df3f8ab3e0e7d3394022e453c006b514e8a4773252b7a8b95806bf07d7`

The base PAF circuit comes from the pinned, independently audited artifact
encoder. The profile layer fixes both exact compression axes. The learned
clauses are reconstructed from the independently audited margin/PAF-prune
event log.

## Solver outcome

CaDiCaL `rel-3.0.1` ran under these fixed ceilings:

- wall: `28,800 s`
- memory: `12,884,901,888` bytes
- proof: `5,368,709,120` bytes
- replay: `7,200 s`

The process was terminated at the proof-size ceiling:

- solver wall time: `3,532.748419 s`
- proof bytes at observation/termination: `5,401,765,598`
- proof SHA-256:
  `9c7f01599e2a601b26dd61e38dad58cdc65738309bec460e1be21be9be58af9f`
- maximum observed RSS: `1,690,419,200` bytes
- solver return code: `-15`
- status: `unknown-resource-ceiling`

The proof was incomplete, so it was not replayed and cannot support an UNSAT
claim. The ten-byte model file is likewise not a SAT witness. A deliberately
empty proof against the known SAT control was rejected before the run.

`run-manifest.json` SHA-256:
`b68575dc21795c425b19032af6de2ef17f7ce69aa89195987bb85c98e2153266`.

## Independent CNF audit

`cnf-audit.json`:

- rebuilt the formula deterministically and reproduced the DIMACS hash;
- parsed all `1,135,539` clauses and all `161,536` variables;
- checked the transformation truth tables and an exhaustive small positive
  fixture;
- compared the direct predicate and canonical CNF on 100
  margin-preserving profile assignments with zero disagreements;
- rejected the ledger's stored margin witness under both the direct full-PAF
  predicate and the canonical CNF;
- reproduced the learned-clause semantic hash.

Audit SHA-256:
`149fe2ea2f673a3cf4bcd726735eabeeb0ee507c18bec0c6012eb765659a52ca`.

## Local payload

The CNF, partial DRAT trace, solver/model files, and logs are intentionally
ignored by Git. The tracked encoding metadata, run manifest, audit, and this
README bind those local files by size and SHA-256 without placing multi-gigabyte
payloads in version control.
