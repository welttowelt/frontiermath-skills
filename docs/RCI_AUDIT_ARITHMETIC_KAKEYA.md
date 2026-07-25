# RCI audit: Arithmetic Kakeya checker revision

Date: 2026-07-25

Status: open

Scope: Arithmetic Kakeya support added to `verify-frontiermath-candidate`

## Current findings and repairs

### Major: graph-suffix ambiguity

The verifiable forcing operation names the changing prefix but does not repeat
that later coordinates agree. The intuitive graph definition connects
corresponding vertices, and the published formula for `m(G)` counts one edge
per common suffix.

Repair: the checker implements equal suffixes, the documentation exposes the
derivation and private-verifier gap, and a fixture distinguishes three
same-suffix edges from nine cross-suffix pairs in shape `[2,3]`.

### Major: human header could be mistaken for trusted score data

The first output line is explicitly for humans.

Repair: the checker recomputes `m`, `|R|`, `n`, `|T|`, and the exact score. A
regression replaces the header by a false `1/1` claim and still obtains the
computed `7/4`.

### Major: unstated one-dimensional key normalization

An early parser accepted a bare integer as a one-dimensional dictionary key,
although the public product vertices are coordinate sequences.

Repair: dictionary keys must be tuple/list coordinate sequences of exact
arity. The bare-integer mutation is rejected.

### Major: row-span translation needed an independent check

The primary checker decides forcing through exact rational row reduction.

Repair: `check_katz_tao_7_over_4_identity.py` hard-codes seven integer
generator rows and four integer forcing identities. It does not call the row
reducer. All identities and the exact `7/4` score pass.

### Major: target provenance

The warmup and full thresholds must not be caller-relabelled.

Repair: exact prompt hashes and targets `7/4` and `67/40` are registered in the
bundled manifest. A target-only contract mutation is rejected as unregistered.

## Verification so far

- live warmup and full prompts are byte-equal to the pinned snapshot;
- 29 tests pass on Python 3.9 and Python 3.12;
- the independent integer-identity script passes;
- the public CLI emits `shadow-verifier-pass` for the Katz--Tao warmup;
- a neutral evolutionary run rediscovers a distinct exact `7/4` certificate;
- a complete bounded `2x2`, four-slope, `T=empty` census checks 408,329
  candidates, finds 48 forcing certificates, and finds no score below `7/4`.

## Open closure items

- run the official structural validator after all documentation edits;
- complete a clean-context forward test of the new CLI and contract mutation;
- rerun the world graph validator after the vault mirror and Canvas update;
- audit the 1,024-vertex and 8,192-generator operational ceilings;
- preserve the full-target search results and residual limitations.

Until these close, the revised skill remains `draft`.

