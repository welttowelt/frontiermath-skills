# RCI audit record

Date: 2026-07-24

Status: closed

Scope: `run-frontiermath-campaign`, `verify-frontiermath-candidate`

## Highest findings

### Reopened fatal: unregistered contract mutation

A held-out public-package audit retained a shipped exact-prompt hash, changed
only the target parameter, and obtained a local pass for both supported
checkers. The emitted contract hash described attacker-supplied bytes but was
not checked against an approved prompt-target registry.

Repair: a bundled manifest now registers the exact contract hash and content.
Both mutations return `input-error`, and the second clean-context rerun passed.

### Fatal: free-form target provenance

The first verifier interface accepted a prompt label separately from target
parameters. A small valid candidate could therefore be relabeled as a larger
target.

Repair: each CLI now requires a hashed JSON contract binding the checker,
problem, prompt type, source, exact prompt hash, and target parameter. Target
values are derived from the contract.

### Major: incomplete decision packets

Early packets did not bind enough artifacts to reproduce rejection and
environment-sensitive decisions.

Repair: packets now include raw and normalized candidate hashes, contract
content and hash, checker version and hash, fixture inventory and hash,
environment record and hash, runtime, checked and unchecked predicates, and
`epoch_verifier_equivalence: false`.

### Major: parser and boundary ambiguity

Ramsey internal whitespace, smallest Hadamard order, near-miss candidates, and
Python 3.9 popcount behavior needed explicit tests.

Repair: internal whitespace is rejected; order 1 is supported; malformed,
wrong-shape, one-bit-near-miss, and cross-contract cases are tested; a Python
3.9 popcount fallback is included.

### Major: authority and evaluator calibration

Generic urgency could be misread as submission authority, and one evaluator
labeled a compliant refusal as failure.

Repair: contributor action requires destination, exact artifact, account or
contract terms, and action confirmation. The forward-test contract defines
PASS as invariant compliance, including a correctly blocked action.

## Verification evidence

- 19 adversarial unit tests pass on Python 3.9.
- All 32,768 labeled graphs in the included \(n=2\) Ramsey contract agree with
  an independent naive oracle.
- An order-4 Hadamard candidate is rejected under the order-668 contract.
- An \(n=2\) Ramsey candidate is rejected under the \(n=25\) contract.
- Contract, fixture, artifact, checker, and environment hashes independently
  reproduce.
- Every bundled public contract matches its manifest ID, content, source
  fields, target, and hash.
- Valid packets emit privacy-safe manifest IDs without absolute contract paths.
- Oversized contract and candidate files are rejected before parsing.
- Both skills pass official structural validation.
- Clean-context tool, world, authority, redaction, advisory, and
  verdict-polarity tests pass.
- A second clean-context public-package rerun passed the mutation, portability,
  dependency-fallback, generated-date, input-ceiling, and private-data checks.

## Residual boundary

- Only Hadamard and Ramsey Book candidate formats are implemented.
- The checkers are public-contract shadows, not Epoch's bespoke verifier.
- Local acceptance does not establish novelty, prior-art clearance, Epoch
  acceptance, or a publication claim.
- No paired baseline experiment has established solve-rate or research-speed
  lift.

Any new checker or structural contract change requires a new RCI entry before
promotion.
