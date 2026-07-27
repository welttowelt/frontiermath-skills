# Correct p37q3 full-neighborhood tabu search

This frozen intervention enumerates all 1,336 legal opposite-sign swaps that
preserve the 74 exact size-nine compression margins, chooses the best
non-tabu neighbor with global-best aspiration, and permits uphill moves.

Only an independently audited exact zero is a candidate.  Any nonzero
endpoint is workload evidence.

## Terminal result

The frozen one-hour run completed with no exact pair:

- full-neighborhood sweeps and applied moves: 1,529,184;
- uphill moves: 776,162;
- restarts: 74;
- best squared residual: 6,368;
- best L1 residual: 784;
- maximum absolute residual: 20;
- independent audit: pass;
- candidate: no;
- result SHA-256:
  `832c3043902f63d2b488dab5a69b61087de943ed94a6fd5450e4c9508eefc28f`;
- mechanism SHA-256:
  `3603ba419caf9acd2a1653da1f78d3cccb7c0953215434dcdb363abbb3857067`;
- audit SHA-256:
  `71e6f6dd8134f04e3c56ccb99b164e8321a12da971704f0d59acfcb87894794c`.

The mechanism telemetry and every compression and PAF check passed. This
endpoint is a phase seed for a semantics-preserving exact SAT follow-through;
it is not itself a Legendre pair.
