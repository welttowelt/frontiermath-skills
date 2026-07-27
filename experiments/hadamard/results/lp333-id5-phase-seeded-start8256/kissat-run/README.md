# LP333 ID5 phase-seeded Kissat pilot

The pinned 1,200-second pilot completed without a SAT model. Its status is
`unknown`; it closes no family.

- phase source: independently checked ID5 objective-8,256 heuristic state;
- positive control: pass;
- conflicts: 1,390,760;
- decisions: 3,943,466;
- propagations: 4,683,648,842;
- maximum observed RSS: 281,231,360 bytes;
- transformed-formula SHA-256:
  `1095fafc923ebe7dd1f7de3beb6a3b7d3fd85eaac2860ead6d6f23395f228bdd`;
- solver-log SHA-256:
  `65e9725a6e577744ab3e71a06345058d9d0cd78cb842c77447f03a649c0aadc6`;
- run-manifest SHA-256:
  `b06a1b9f6a68e00894ef6e050dc0f27ddcff60499a0e07d05772ffdbdf855d84`.

The semantics-preserving literal renaming and phase mapping passed their
independent audits. Reaching the time ceiling without a model is workload
evidence only. The next arm uses the stronger independently audited
objective-5,280 endpoint.
