# LP333 family ID5 orbit anneal

This search fixes both rows under subgroup `{1,211,232}` and preserves the
forced row-sum profile on every move: one negative singleton and 55 negative
size-three orbits in each row.

Only an independently checked exact zero is a Legendre-pair candidate.
Nonzero scores do not close ID5.

## Terminal result

The frozen one-hour run completed with no exact pair:

- proposals: 194,969,600;
- accepted proposals: 381,855;
- restarts: 97;
- best squared residual: 5,280;
- best L1 residual: 696;
- maximum absolute residual: 16;
- independent audit: pass;
- candidate: no;
- result SHA-256:
  `cd017adf83134dffaa3055601a166d5dcbb6d69b8bf0f805f7990ca768707019`;
- audit SHA-256:
  `618dedbd97b9b7b62a0299bd2f70755c006af0fc28a42fe152aeeff4cacee781`.

The audit reconstructed the subgroup, forced orbit margins, both full PAF
vectors, stored scores, source and binary pins, and a legal mutation control.
The endpoint is a valid phase seed, not a Legendre pair.
