# ID3 profile-73 propagation benchmark

This directory records the preregistered Gate B comparison for one fixed
profile-73 ID3 slice. It is a formulation benchmark, not a SAT or UNSAT result.

## Matched variants

| Variant | Termination | Candidates | Nodes | Principal result |
|---|---:|---:|---:|---|
| margins | 100,000-candidate ceiling in `18.712409 s` | `100,000` | `100,000` | no margin prunes on this traversal |
| forced | 60-second ceiling in `60.023543 s` | `99,013` | `99,013` | `231,086` forced lines |
| exact PAF bounds | 60-second ceiling in `60.020791 s` | `66,897` | `11,381` | `55,499` PAF prunes and `11,380` survivors |

The PAF variant also recorded `18` margin prunes and `71,012` exact
boundary-equality events. Its PAF prune fraction among margin-feasible
children is `0.8298419534`, and the measured structural reduction is
`5.8768892794x`. Both preregistered promotion floors passed.

## Independent audit

`audit.json` reconstructs:

- all `55,499` PAF-prune events;
- all `71,012` equality-boundary events;
- all `18` margin-prune events;
- the event count and file digest.

It reports zero errors and rejects a one-unit mutation of a stored exact
bound. The audit input manifest SHA-256 is
`1424e6a207382145cbdc1fc0562ebea1e36e1d97a894ad4917dbe0e1e9cb155f`.

## Local payload

`events.jsonl` is intentionally ignored by Git:

- records: `126,529`
- bytes: `48,728,282`
- SHA-256:
  `8c93fcc8c2c4f55010dcbec0b271e932e7b1151934215ebb08919fe1e4dbd9d1`

The tracked `benchmark.json`, `audit.json`, and this README preserve its
identity and the exact claim boundary.
