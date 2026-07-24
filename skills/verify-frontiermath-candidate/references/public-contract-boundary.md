# Public-contract shadow-verifier boundary

## Four predicate classes

Classify every acceptance predicate:

1. **Explicit public:** stated directly in the pinned public prompt.
2. **Logically derived:** necessary and sufficient reformulation with a written
   derivation.
3. **Operational assumption:** encoding, runtime, machine, parser, or numerical
   convention not fully specified publicly.
4. **Unavailable:** paid-verifier logic, hidden target, or unpublished test
   distribution.

A local pass covers only classes 1 and justified class 2 predicates.

## Checker design rules

- Reject malformed input before mathematics.
- Prefer certificates whose verification is cheaper than discovery.
- Use integers, rationals, finite fields, or intervals where possible.
- If numerical tolerance is unavoidable, state the norm, threshold, precision,
  conditioning assumptions, and adversarial stress tests.
- Emit the first concrete witness: row pair, edge pair, uncovered subset,
  violated relation, collision, or timeout.
- Keep generator and verifier implementations separate.
- Hash candidate, checker, fixtures, and environment record.
- Bind target parameters to a hashed contract artifact whose exact hash and
  content appear in the bundled manifest. Do not accept a caller-supplied
  provenance label or unregistered self-hash as proof that a candidate belongs
  to that target.
- Emit a manifest ID rather than a local absolute contract path.
- Enforce contract, candidate, and target ceilings before expensive parsing or
  mathematical checks.
- Do not weaken a predicate to make a promising candidate pass.

## Minimum fixture set

| Fixture | Purpose |
|---|---|
| known valid small instance | detects false rejection |
| one local mathematical defect | detects false acceptance |
| malformed serialization | tests parser strictness |
| boundary-size instance | tests off-by-one behavior |
| equivalent representation | tests allowed normalization |
| adversarial near miss | attacks the decisive predicate |

## Result packet

```json
{
  "status": "shadow-verifier-pass",
  "prompt_snapshot": {
    "contract_sha256": "...",
    "contract_id": "...",
    "contract_registry": {
      "status": "bundled-manifest-match",
      "manifest_sha256": "..."
    },
    "problem_id": "...",
    "prompt_type": "...",
    "source": {"artifact_sha256": "...", "prompt_sha256": "..."},
    "target": {}
  },
  "checker": "path and hash",
  "candidate_sha256": "...",
  "checked_predicates": [],
  "unchecked_predicates": [],
  "fixtures": [],
  "runtime_seconds": 0.0,
  "failure_witness": null,
  "epoch_verifier_equivalence": false
}
```
