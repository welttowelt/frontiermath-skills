# FrontierMath campaign contract

## Claim ladder

Use the weakest accurate claim.

| Claim | Minimum evidence |
|---|---|
| `prompt-pinned` | Exact public prompt, retrieval date, and source hash |
| `warmup-reproduced` | Artifact, deterministic command, independent check |
| `shadow-verifier-pass` | Candidate passes the named local checker and its fixtures |
| `candidate-audited` | Separate audit closes mathematical and operational defects |
| `epoch-verifier-pass` | Direct evidence from the named Epoch verifier version |
| `solved` | Acceptance basis is explicit, prior art is checked, and publication claim is supportable |

Never infer a higher rung from a lower one.

## Required per-direction record

```json
{
  "name": "structural direction name",
  "hypothesis": "why this family could satisfy the contract",
  "novelty": "how it differs from tried directions",
  "cheapest_falsifier": "first decisive experiment",
  "budget": "time and compute ceiling",
  "result": "positive, negative, or inconclusive",
  "evidence": ["paths, hashes, commands"],
  "next_action": "one objective-advancing action"
}
```

## Candidate packet layout

```text
candidate-packet/
  CONTRACT.md
  CANDIDATE.*
  GENERATOR.*
  RATIONALE.md
  PRIOR_ART.md
  FAILED_DIRECTIONS.md
  environment.json
  hashes.sha256
  verifier/
  tests/
  audit/
```

## Stop and pivot conditions

Pivot when any of these holds:

- two successive iterations fail to improve the primary metric;
- the candidate exploits a parser quirk rather than the mathematical
  contract;
- a required full target is redacted;
- current tools cannot check the decisive predicate;
- the direction duplicates known prior art without a new lever;
- the verifier accepts a seeded invalid fixture;
- the proposed computation exceeds the declared budget without a new
  asymptotic or structural reduction.

Record the stopped direction. Do not erase it.

## Independence rule

The authoring channel may build a candidate and a checker, but final audit
requires a separate context or reviewer. Independence is not satisfied by
rerunning the same code or asking the same agent to restate its reasoning.

## Forward-test verdict polarity

When a clean-context evaluator returns a contract verdict:

- `PASS` means the operator response obeyed every tested invariant;
- `FAIL` means the operator response violated at least one tested invariant.

A correctly blocked external action is a `PASS` when the authority boundary
requires the block. Do not label a compliant refusal `FAIL` merely because the
requested submission, purchase, or publication did not occur.
