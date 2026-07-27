# LP333 family ID5 elite path relinking

This arm searched both deterministic greedy paths between the independently
audited objective-4,512 full-neighborhood-tabu elite and objective-4,704
double-orbit-anneal elite. At every step it evaluated every equal-size orbit
exchange that strictly approached the opposite endpoint.

## Terminal result

- directed paths: 2;
- steps per direction: 60;
- candidate exchanges evaluated: 35,972 and 35,752;
- best squared residual: 4,512;
- best L1 residual: 600;
- maximum absolute residual: 12;
- independent full replay: pass;
- candidate: no;
- result SHA-256:
  `c6404f92d1a8bff1cc0513358efea4646aafb80fcb54e655e64b13b69ef7621e`;
- audit SHA-256:
  `fea2752d3dbaa28be619438cf2a5d479e69437a04394d1595085c1338827b9de`.

Every stored move was legal and target-reducing, every stored objective
matched a fresh complete PAF recomputation, and both paths reached their
pinned opposite endpoint. No intermediate beat the 4,512 source record, so
this elite pair is parked for deterministic path relinking.
