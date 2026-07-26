# LP333 ID5: inverse-PAF-quotiented static-symmetry formula

This experiment removes identity-duplicate periodic-autocorrelation equations
before constructing the PB layer. For every sequence,
`PAF(s) = PAF(-s)` by an index substitution. An independent auditor directly
recomputed all ordered position-pair coefficients and partitioned the 112
original ID5 shift representatives into 56 exact size-two classes.

The quotient reduces the formula from 1,258,456 to 752,244 clauses and from
190,897 to 118,109 variables while retaining the same 143 static lex leaders.
`encoding.json` and `inverse-paf-audit.json` bind the exact transformation.

The CNF and proof-run payloads are intentionally ignored; tracked manifests
bind their SHA-256 hashes.
