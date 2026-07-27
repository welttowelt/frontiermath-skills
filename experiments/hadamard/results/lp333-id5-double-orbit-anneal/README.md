# LP333 family ID5 double-orbit anneal

This variable-neighborhood arm mixed the ordinary six-coordinate ID5 orbit
exchange with atomic twelve-coordinate moves that exchange two negative and
two positive triple orbits.

## Terminal result

The frozen one-hour run completed with no exact pair:

- proposals: 153,747,456;
- double-triple proposals: 19,216,539;
- accepted proposals: 220,444;
- restarts: 76;
- best squared residual: 4,704;
- best L1 residual: 720;
- maximum absolute residual: 12;
- independent audit: pass;
- candidate: no;
- result SHA-256:
  `423a242e74a6f07f02aff4d51a9ff52b7e9a979e918b83bff637d4ecacb36fa2`;
- audit SHA-256:
  `0a71c11ad9135bc3310a6de1adade76a6eff83189462f629920c1a12b2fe1981`.

The arm beats the prior single-orbit anneal endpoint of 5,280 but not the
full-neighborhood campaign record of 4,512. Its nonzero endpoint is search
evidence only.
