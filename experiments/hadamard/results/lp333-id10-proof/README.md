# LP333 family ID10 proof certificate

Fixed common-multiplier family ID10 is proof-certified infeasible.

## Formula and semantic audit

- subgroup order: `6`
- orbit signature: `3 x 1 + 2 x 3 + 54 x 6`
- orbit variables per sequence: `59`
- DIMACS variables: `66,552`
- DIMACS clauses: `451,186`
- DIMACS bytes: `10,606,358`
- DIMACS SHA-256:
  `f3e7b1d7e9f8825bdfcd3812f23f41c83be515373513c107cf10cc95b870fd61`

The independent audit checked `1,000` random assignments, `116,000` direct
PAF comparisons, `666,000` sequence coordinates, `2,000` row sums, and 20
canonical CNF extensions. It rebuilt the exact DIMACS hash, parsed every
clause, passed transformation and positive-fixture controls, and rejected a
corrupted orbit map.

Encoding SHA-256:
`9645a32584e1cb5c04a36db1f3cd5f4730bd0e06366d3445799474409e188350`.

Formula-audit SHA-256:
`0e2e9ceb72f2b46aabc5dd5f3ae77be7ed02be3b4a8021d7da701dbf251a9b97`.

## Solver and two proof replays

Pinned CaDiCaL returned UNSAT:

- solver wall seconds: `61.720578`
- proof bytes: `712,682,070`
- proof SHA-256:
  `98a3101b9540510ccea62022b6f923caa2b6ca34b29ee4949a55a4b96a0ce29a`
- maximum observed RSS: `652,378,112` bytes

Pinned `drat-trim` accepted the proof during the run in `24.709100 s`.
Run-manifest SHA-256:
`264f9cc6ec7e2ef736767122742c280d83fe2d02d6cb7d2451d410fe296c1a02`.

A separate audit checked every metadata, formula, proof, tool, and manifest
binding, then freshly replayed the proof in `24.649567 s`. Its fresh replay log
SHA-256 is
`b09684244f8b2769241839c4612326bde7a53b475277609c9d98ad2765605c1c`.
It also freshly rejected an empty proof against the SAT control.

Independent run-audit SHA-256:
`6e3697a91addf86fce330f47f6d6b34dd718974558a1747531d24e3e850c8209`.

## Claim boundary

This closes fixed family ID10. Together with the separately audited affine
normalization theorem, it also excludes coherent translated versions of ID10.
It does not decide ID9, the other seven open fixed families, unrestricted
LP(333), or H(668).

The CNF, proof, model, and logs are intentionally ignored by Git; tracked
metadata bind the local payload by size and hash.
