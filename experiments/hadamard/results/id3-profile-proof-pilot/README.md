# ID3 profile proof pilot

Gate A passed on two controls:

- cell 0 is UNSAT and its DRAT proof replays successfully;
- cell 73 is SAT, its full CNF model satisfies every clause, and the decoded
  witness passes the independent margin and PAF checker;
- an empty bogus proof is rejected on the SAT control.

The generated CNF, proof, solver logs, and model are intentionally local and
ignored. The tracked manifest, verification reports, encoding metadata, and
decoded witness bind those payloads by hash.

Pilot manifest SHA-256:

`6c5e1d37743477671dadbf318e5bb14b75e72cf9e3e8258aa06c43ad2fbb3cd9`

The batch directory contains the corresponding 52-cell proof-certified
negative partition.
