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

Follow-up: the public forcing operation itself only constrains the first
coordinates and therefore literally permits the nine cross-suffix pairs. The
discovery program now supports this as an explicitly separate
`literal-cross-tail` mode. It records both the literal exact result and the
canonical same-tail shadow result; a literal-only survivor cannot be reported
as a new Arithmetic Kakeya bound.

The diagnostic found a six-line score-`14/9` example using only
`X={(0,0),(1,0),(0,1),(1,1)}`. Nine hard-coded integer identities verify it
under the prefix-only reading, while the same-tail checker gets stuck. Since
`14/9` is also below the lower bound quoted for this fixed slope set, the
example is preserved as evidence that the two readings are not equivalent,
not as a mathematical solution.

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
reducer. All identities and the exact `7/4` score pass. A second program,
`check_cycle_map_equivalence.py`, independently implements the augmented
labelled-cycle map and agrees with dense closure on the warmup and 200 seeded
random candidates.

### Major: evolutionary fitness rewarded isolated near misses

The first full-target searches repeatedly forced all but one vertex because an
entire vertex could be absent from every generator while the remaining
subgraph scored highly.

Repair: every evaluation records generator support, guided mutation can target
an unresolved vertex directly, and `--coverage-first` makes full support a
separate lexicographic gate. Regression tests prove the repair preserves the
score budget and fixed-cardinality known set, and that coverage-first reverses
the isolated-vertex preference. The search remains heuristic.

### Route gate: the published recurrence cannot cross the target

Exact rational arithmetic verifies
`F(b)-b=-(b^3-4b+2)/(b^2+3b-2)` and
`(67/40)^3-4(67/40)+2=-37/64000`. The route gate rules out only deeper
iteration of this recurrence; it does not rule out a different gadget.

### Major: target provenance

The warmup and full thresholds must not be caller-relabelled.

Repair: exact prompt hashes and targets `7/4` and `67/40` are registered in the
bundled manifest. A target-only contract mutation is rejected as unregistered.

## Verification so far

- live warmup and full prompts are byte-equal to the pinned snapshot;
- 39 tests pass on Python 3.9 and Python 3.12;
- the independent integer-identity script passes;
- the independent cycle-map implementation passes the warmup plus 200 seeded
  random equivalence trials;
- the neutral seed-7 calibration still rediscovers an exact `7/4` certificate
  after 2,349 evaluated candidates;
- the public CLI emits `shadow-verifier-pass` for the Katz--Tao warmup;
- a neutral evolutionary run rediscovers a distinct exact `7/4` certificate;
- a complete bounded `2x2`, four-slope, `T=empty` census checks 408,329
  candidates, finds 48 forcing certificates, and finds no score below `7/4`.
- a 13-shape, 700-by-500-generation full-target search evaluates more than
  2.2 million candidates with `T=empty`, finds no modular full-forcing
  survivor, and records its command and aggregate packet under
  `experiments/arithmetic-kakeya/results/`.
- the search now recomputes its exact numerator budget from `n-|T|` and evolves
  fixed-cardinality initial known sets; regression tests cover the denominator,
  mutation invariant, and zero-denominator rejection.
- the literal-operation diagnostic has an independent no-row-reducer identity
  script and a regression proving that the canonical same-tail checker rejects
  the same six-line serialization.

## Open closure items

- run the official structural validator after all documentation edits;
- complete a clean-context forward test of the new CLI and contract mutation;
- rerun the world graph validator after the vault mirror and Canvas update;
- audit the 1,024-vertex and 8,192-generator operational ceilings;
- preserve the full-target search results and residual limitations.

Until these close, the revised skill remains `draft`.
