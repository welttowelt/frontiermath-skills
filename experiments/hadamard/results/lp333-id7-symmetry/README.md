# LP333 ID7 Static-Symmetry Pilot

This directory preserves the preregistered ID7 transfer attempt and the
unexpected direct obstruction it exposed.

The generated base model already contained two empty clauses, corresponding
to exact PAF weighted-sum shortfalls at shifts `111` and `222`. CaDiCaL
therefore returned UNSAT during parsing, with no learned clauses. `drat-trim`
printed `s VERIFIED` because the input was trivially inconsistent but returned
code `1`; the wrapper correctly did not promote the run and recorded status
`unknown`.

That solver path is not the promoted evidence. The mathematical result is
carried by:

- `../lp333-id7-direct-paf-obstruction.json`;
- `../lp333-id7-direct-paf-obstruction-audit.json`;
- `../lp333-id7-direct-paf-obstruction-bindings.json`;
- `../lp333-id7-direct-paf-obstruction-binding-audit.json`.

The certificate reconstructs the subgroup action from the pinned source and
checks all `332` nonzero shifts. A separate implementation uses union-find and
direct group-action membership without importing the proof encoder or
certificate generator.

The static-symmetry generator now fails closed on any direct PAF obstruction
instead of serializing an empty-clause CNF.
