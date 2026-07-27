# LP333 family ID5 full-neighborhood tabu

This arm enumerated every one of the 6,054 legal equal-size
opposite-sign orbit swaps at each state, with short orbit-level tabu memory
and deterministic perturbations from the global best.

## Terminal result

The frozen one-hour run set a new campaign record but found no exact pair:

- full-neighborhood sweeps: 29,446;
- applied moves: 29,446;
- uphill moves: 14,589;
- perturbation restarts: 4;
- best squared residual: 4,512;
- best L1 residual: 600;
- maximum absolute residual: 12;
- independent audit: pass;
- candidate: no;
- result SHA-256:
  `ea5f0e1743f54d1c4d49dbd235a1fe263eed462719ba95e75a9da0dc5be7f089`;
- mechanism SHA-256:
  `931178675c2631517b13c731218eda12945b9eca050ce88c6ecc6eabf9720724`;
- audit SHA-256:
  `410707bc4fee81753665e6ffdd27ccff183578e5931985bcff5884c01fcedb61`.

The independent audit reconstructed the subgroup, forced orbit margins,
both full PAF vectors, stored scores, source and binary pins, and a legal
mutation control. The endpoint is a valid continuation and phase seed, not
a Legendre pair.
