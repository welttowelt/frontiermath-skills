# ID10 complete static-symmetry calibration

The 72-element group combines the 36 unit-decimation actions modulo the fixed
order-6 multiplier subgroup with sequence swap. Complete auxiliary-prefix
lex-leaders add 7,993 variables and 47,958 clauses.

Pinned CaDiCaL returned UNSAT in 23.375 seconds. The 215,700,841-byte DRAT
proof is 3.304x smaller than the 712,682,070-byte baseline and passed the
preregistered 237,560,690-byte promotion gate. Pinned `drat-trim` accepted it
twice in 12.133 and 12.235 seconds; fresh bogus-proof rejection also passed.

The independent checker reconstructed all 72 actions, matched every one of
the 47,958 serialized symmetry clauses, checked 7,993 auxiliaries, and passed
an exhaustive lex-prefix truth table.

The CNF, proof, model, and logs are intentionally ignored. `encoding.json`
and `calibration-v2/run-manifest.json` bind the local payload.
