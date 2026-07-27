# LP333 p37q3 six-coordinate escape anneal

This corrected lane preserves all 74 prescribed length-37 margins. Seven
proposals out of eight use one same-column swap; every eighth atomically
composes three swaps, allowing a six-coordinate barrier crossing without
accepting either intermediate state.

Exact zero plus independent full-length verification is the only promotion.

## Terminal result

The frozen one-hour run completed with no exact pair:

- proposals: 1,660,878,848;
- six-coordinate proposals: 207,609,856;
- accepted proposals: 15,871,349;
- restarts: 830;
- best squared residual: 6,688;
- best L1 residual: 792;
- maximum absolute residual: 16;
- independent audit: pass;
- candidate: no;
- result SHA-256:
  `0041959dbd38796e4ed67c1505815dec2e66fbc9aceb88aeecdf26798d3dc95c`;
- audit SHA-256:
  `225253c64c5ef57e3af0bd88e1f4f519ce2cfc8f37e12224df4ec2a949a8687d`.

The mechanism fired as preregistered and the audit reconstructed every
compression margin and full-length PAF. This endpoint is nonterminal search
evidence only.
