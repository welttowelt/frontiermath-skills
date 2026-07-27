# Correct p37q3 unrestricted SAT slice

This directory contains the source-correct prescribed-compression formula for
the unrestricted identity family at

`333 = 37 * 3^2`.

The compressed rows are `[1, 3 chi_37]` and `[1, -3 chi_37]`.  The independent
formula audit reconstructs all 216 compression-preserving symmetry actions,
all 215 nonidentity lex leaders, and all 74 exact size-nine column counters.

Only a complete SAT assignment passing `verify_lp333_pq2_model.py` is a
candidate.  Solver telemetry, UNKNOWN, and proofless UNSAT decide nothing.
The large CNF and solver logs/models are reproducible local artifacts and are
ignored by Git.

## Terminal exact-search results

Both frozen two-hour SAT-discovery arms completed without a model:

- Kissat: `unknown`, 7,829,858 conflicts, 46,940,431 decisions,
  27,843,308,138 propagations, positive control pass;
- CryptoMiniSat: `unknown`, parity recovery fired with 326,016 recovered
  XORs and five used Gauss matrices, positive control pass;
- candidate: no.

The Kissat manifest SHA-256 is
`84255061df9c7259105cd2ecbce447e434d303779989472eca94db47f2b7cf3e`.
The CryptoMiniSat manifest SHA-256 is
`4204906dc7afa0fbbf612dd6a054545ebc2ec1e4569dea369c395547b5996540`.

These ceilings decide neither the prescribed-compression slice nor
unrestricted LP(333).
