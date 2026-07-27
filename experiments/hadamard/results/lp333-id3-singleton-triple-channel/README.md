# LP333 ID3: singleton-to-triple unary row channel

This unrestricted fixed-ID3 formula retains the exact full-PAF static-symmetry
parent and its factor-81 singleton-translation quotient. Its only new
mechanism is a uniquely extended unary prefix counter over the 108
size-three-orbit bits in each sequence.

Exact enumeration of the 30 lex-canonical singleton patterns finds 19
row-feasible cases and 11 impossible cases. The feasible cases force the
singleton/triple negative-count pair to be one of
`(1,55)`, `(2,55)`, `(4,54)`, or `(5,54)`. The channel appends 35,834 clauses
and 9,016 auxiliary variables, without changing any PAF equation, row equation,
primary variable, or prior symmetry clause.

The independent audit:

- rederives all singleton translation orbits and row cases;
- reconstructs both counters and all 35,834 channel clauses;
- matches serialized block SHA-256
  `c4e845b92977fc29190071328be566e69d9ca31e9c150f69eb7340b2ef9bead2`;
- binds parent formula SHA-256
  `0ea4f87736db6d1076214d8378e4f66e1fe499291d5f4d0d406209a7779172b8`;
- rejects a one-literal mutation.

Formula SHA-256:
`8662a1054eedc5a7aedddc1a3346fdcd79181d3347045bae2b8fd8ccf248ad03`.
The large CNF and proof payloads are ignored; tracked metadata and manifests
bind their hashes.
