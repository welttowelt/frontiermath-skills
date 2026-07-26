# LP333 family ID9 proof calibration

This directory contains the exact formula and matched proof-growth calibration
for fixed common-multiplier family ID9. The terminal status is
`unknown-resource-ceiling`, not UNSAT.

## Formula and audit

- subgroup order: `6`
- orbit signature: `3 x 1 + 2 x 3 + 54 x 6`
- orbit variables per sequence: `59`
- DIMACS variables: `66,552`
- DIMACS clauses: `451,186`
- DIMACS bytes: `10,606,358`
- DIMACS SHA-256:
  `efccbf497673cc8fe0b6eae8d9c3c475b20dbfc3347cfd02fea94bf0e63a7002`

The independent audit checked `1,000` random assignments, `116,000` direct
PAF comparisons, `666,000` sequence coordinates, `2,000` row sums, and 20
canonical CNF extensions. It rebuilt the exact DIMACS hash, parsed every
clause, passed the small positive fixture, and rejected a corrupted orbit map.

Encoding SHA-256:
`690c4f3e7a93001944de1cb57026cad087f6776a5bc0adccd8bc01cdacb58699`.

Audit SHA-256:
`fe53d76477daa657692b0c8d56e1a15917bfa1797f08cb9d1723fd0ab2b93385`.

## Matched calibration

The run used a `300 s` wall ceiling, `4 GiB` memory ceiling, and `1 GiB` proof
ceiling. It was terminated at the proof ceiling:

- wall seconds: `94.147064`
- partial proof bytes: `1,078,805,387`
- partial proof SHA-256:
  `055ce53e58e67f0c792938449867749dc1ff751973cb7f1982595f015f89a5b9`
- maximum observed RSS: `402,292,736` bytes
- status: `unknown-resource-ceiling`

The incomplete proof was not replayed and cannot support an infeasibility
claim. Run-manifest SHA-256:
`b2944a23bbe923e7ace8f03fbcd2f169927086827e5eb124918c77a456915268`.

The CNF, partial proof, model, and logs are intentionally ignored by Git.
