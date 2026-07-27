# Correct p37q3 unrestricted SAT slice

This directory contains the source-correct prescribed-compression formula for
the unrestricted identity family at

`333 = 37 * 3^2`.

The compressed rows are `[1, 3 chi_37]` and `[1, -3 chi_37]`.  The independent
formula audit reconstructs all 216 compression-preserving symmetry actions,
all 215 nonidentity lex leaders, and all 74 exact size-nine column counters.

Only a complete SAT assignment passing `verify_lp333_pq2_model.py` is a
candidate.  Solver telemetry, UNKNOWN, and proofless UNSAT decide nothing.
The large CNF and solver logs/models are reproducible local artifacts and are
ignored by Git.
