# LP333 Direct PAF Obstructions

The source release classified fixed multiplier families ID2 and ID7 as
`OPEN`. A campaign-wide direct-bound screen found that both are already
infeasible at shifts `111` and `222`.

For either family, multiplier invariance makes `222` of the `333` shifted
products diagonal in each sequence, leaving an off-diagonal coefficient sum
of only `111`. Requiring combined PAF `-2` is equivalent to a weighted XOR sum
of `334`, while both sequences together can contribute at most `222`. The
shortfall is `112`.

The certificates check all `332` nonzero shifts. The auditors independently
reconstruct the group action, orbit signature, diagonal counts, and bound, and
reject a one-unit mutation of the shortfall.

Artifacts:

- `lp333-id2-direct-paf-obstruction.json`;
- `lp333-id2-direct-paf-obstruction-audit.json`;
- `lp333-id2-direct-paf-obstruction-bindings.json`;
- `lp333-id2-direct-paf-obstruction-binding-audit.json`;
- `lp333-id7-direct-paf-obstruction.json`;
- `lp333-id7-direct-paf-obstruction-audit.json`;
- `lp333-id7-direct-paf-obstruction-bindings.json`;
- `lp333-id7-direct-paf-obstruction-binding-audit.json`.

These records close only fixed IDs 2 and 7 and, through the separate
affine-normalization theorem, their coherent translated versions. They do not
decide unrestricted LP333 or H668.
