# LP333 unrestricted correct p37q3 anneal

This lane uses the source-correct factorization \(333=37\cdot3^2\) and the
prescribed length-37 rows \([1,3\chi_{37}]\),
\([1,-3\chi_{37}]\). Each compressed coordinate is the sum of nine binary
entries.

The search preserves all 74 exact column cardinalities and scores every
independent full-length combined PAF residual in integer arithmetic.
Promotion requires exact zero plus the independent bit-rotation audit.

## Terminal result

The frozen two-hour run completed with no exact pair:

- proposals: 4,324,392,960;
- accepted proposals: 46,727,532;
- restarts: 2,162;
- best squared residual: 6,656;
- best L1 residual: 800;
- maximum absolute residual: 20;
- independent audit: pass;
- candidate: no;
- result SHA-256:
  `60e24e0e44c955a62577a432e8b013af0937ebc4d6d37ed7a0581949b0a6c2bd`;
- audit SHA-256:
  `a6a7c3a0d1200f2e06ee376a26334dbcc2ef12c687a56463ec510048f5983b8e`.

The endpoint is nonterminal search evidence and does not beat the audited
full-neighborhood-tabu score of 6,368.
