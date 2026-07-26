# ID9 proof certificate with complete static symmetry

Previously unresolved fixed family ID9 is proof-certified infeasible.

The unchanged ID10-winning mechanism adds complete lex-leaders for the same
72-element decimation-by-sequence-swap group. Pinned CaDiCaL returned UNSAT in
20.320 seconds and emitted a 205,229,334-byte DRAT proof. Pinned `drat-trim`
accepted it twice in 7.537 and 7.472 seconds; fresh bogus-proof rejection also
passed.

The independent checker reconstructed all 72 actions, matched every one of
the 47,958 serialized symmetry clauses, checked 7,993 auxiliaries, and passed
an exhaustive lex-prefix truth table.

This closes fixed family ID9 and, through the separately checked affine
normalization theorem, its coherent translated versions. It does not decide
the other seven fixed families, unrestricted LP(333), or H(668).

The CNF, proof, model, and logs are intentionally ignored. `encoding.json`
and `calibration/run-manifest.json` bind the local payload.
