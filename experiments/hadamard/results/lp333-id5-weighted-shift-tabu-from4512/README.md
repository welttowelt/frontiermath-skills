# LP333 ID5 exact weighted-shift tabu continuation

This arm exploited the exact ID5 PAF quotient: the 166 independent shifts
form one weight-1 and 55 weight-3 classes under the multiplier subgroup and
reflection. It retained every one of the 6,054 legal orbit moves and the
reference tabu schedule while scoring 56 exact representatives.

## Terminal result

The frozen one-hour continuation set a new campaign record:

- full-neighborhood sweeps: 103,132;
- applied moves: 103,132;
- uphill moves: 51,228;
- perturbation restarts: 19;
- best squared residual: 4,128;
- best L1 residual: 672;
- maximum absolute residual: 12;
- independent weighted and full-PAF audit: pass;
- candidate: no;
- result SHA-256:
  `2c2e9f2471682b25a6967cafbaff5ef1d0a71dd86dd11cb7007a68431c25c3e6`;
- mechanism SHA-256:
  `93088b04105363b2dbea195d3fbaf95812e409a1a49818818d0697fbd6b2f7f3`;
- audit SHA-256:
  `e1715965ae4d97002260fa463f03b62bb5cc755539bb09fc46845b5dd32a18c9`.

The audit independently reconstructed the exact 56-class partition, proved
the weighted objective equals the complete 166-shift objective, and verified
both full rows, subgroup invariance, forced margins, stored PAFs, pins, and a
legal mutation control. The endpoint is a valid stronger phase seed, not a
Legendre pair.
