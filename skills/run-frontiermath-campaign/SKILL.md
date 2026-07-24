---
name: run-frontiermath-campaign
description: Run a durable research campaign on Epoch AI FrontierMath Open Problems. Use when triaging a public FrontierMath problem, reproducing a warmup, mapping literature into candidate levers, planning a computational search, recording failed directions, or assembling an independently auditable candidate packet. This skill keeps public-prompt work, paid-verifier access, and contributor submissions in separate authority lanes.
---

# Run FrontierMath Campaign

Advance one precise problem lane at a time while preserving prompt versions,
negative results, executable evidence, and the boundary between public shadow
checks and Epoch's bespoke verifier.

## Start here

1. Choose a durable research-world directory and expose it to the session:

```bash
export FRONTIERMATH_WORLD="/absolute/path/to/frontiermath-world"
```

2. Read the selected problem note and the exact prompt in the pinned public
   dataset.
3. Read `references/campaign-contract.md`.
4. Inspect `$FRONTIERMATH_WORLD/Campaign State` before choosing a direction.
   Use a file-backed state helper when one is installed. Do not rely on chat
   memory as campaign state.
5. If the source snapshot changed, run:

```bash
python3 scripts/inspect_snapshot.py \
  "/path/to/extracted/public/dataset" \
  --zip "/path/to/open_problems_data.zip"
```

Do not silently substitute a current web prompt for the pinned prompt. Record
the delta and decide whether the lane migrates.

When regenerating problem notes, pass provenance explicitly:

```bash
python3 scripts/build_problem_notes.py \
  --survey "/path/to/open_problems_survey.csv" \
  --prompts "/path/to/open_problems_prompts.csv" \
  --output-dir "/path/to/problem-notes" \
  --snapshot-date YYYY-MM-DD \
  --retrieved-date YYYY-MM-DD \
  --source-sha256 64-lowercase-hex-digits
```

## Lane protocol

### 1. Freeze the contract

Record:

- problem ID, prompt type, source URL, retrieval date, and snapshot hash;
- exact input and output grammar;
- time, memory, hardware, and software assumptions;
- every redaction, ambiguity, and paid-verifier dependency;
- acceptance predicates that can be inferred from the public prompt;
- predicates that cannot be inferred.

If a target is redacted, the lane may study the warmup or reusable method, but
it cannot claim to be attacking the hidden full target.

### 2. Reproduce the warmup

Reproduce the warmup before the full problem unless no warmup is published.
Keep:

- construction or algorithm;
- deterministic command;
- environment fingerprint;
- output hash;
- independent check;
- defects or mismatches.

A warmup is a calibration gate, not evidence that the full problem is solved.

### 3. Build the verification shadow

Use `$verify-frontiermath-candidate`.

The shadow verifier must:

- consume a serialized candidate rather than trusting explanatory prose;
- derive checks from the public contract;
- include positive, negative, malformed, and boundary fixtures;
- emit a precise pass or failure witness;
- disclose every unimplemented predicate;
- never call itself equivalent to Epoch's verifier.

The research lane cannot audit its own final candidate.

### 4. Build the research ledger

Use semantic search before a generated report. For each paper, create:

- claim supported by the paper;
- source location and identifier;
- transfer verdict: `direct`, `adapt`, `analogy`, or `do-not-adopt`;
- implementation shadow;
- cheapest falsifier;
- assumptions that differ from this prompt.

Use `$paper-to-levers` for literature digestion when it is installed. If it is
unavailable, fill the ledger fields above directly and require a second reader
to check source fidelity. Do not treat an abstract, search snippet, or
generated report as primary evidence.

### 5. Probe routes before the official plan

Write a scratch exploration advisory before selecting the next direction. It
must:

- inspect recent failures and signs of parameter-only tuning;
- compare a few structurally different routes;
- name the cheapest falsifier for each route;
- recommend one task shape with risks and non-goals;
- leave the frozen contract unchanged.

The advisory informs the official plan but cannot promote a claim or direction.
When a proof fails at a named missing control, test whether a construction can
maximize that exact failure and produce an obstruction.

### 6. Generate distinct directions

Maintain at least three directions that differ structurally, not just by
parameters. Typical families are:

- explicit algebraic or geometric construction;
- SAT, SMT, exact cover, MIP, or constraint search;
- local search, evolutionary search, or switching;
- theorem reduction or composition of known gadgets;
- exhaustive census over a justified quotient space.

Before running a direction, log its rationale and what structural change
separates it from earlier attempts.

### 7. Run critique, fix, verify

At the end of every research tick:

1. state the strongest concrete defect in the current candidate or direction;
2. apply the smallest complete repair;
3. rerun the affected checks;
4. record the result, including negative evidence;
5. end with the next objective-advancing action.

Do not use a polished explanation as a substitute for a new check.

### 8. Assemble a candidate packet

A candidate packet contains:

- frozen contract and source hash;
- candidate artifact and hash;
- generator source and dependency lock where applicable;
- deterministic reproduction command;
- runtime and hardware record;
- shadow-verifier source, tests, output, and limitations;
- proof or mathematical rationale;
- literature and prior-art ledger;
- failed-direction ledger;
- independent audit;
- claim status from the world truth vocabulary.

The packet remains `unresolved` until the independent audit closes.

## Participation authority

Treat these as separate lanes:

- **Public solver lane:** research against public prompts and local shadow
  checks. Authorized by a request to work on the problems.
- **Paid-verifier lane:** purchase, contract, or access to Epoch's verifier.
  Requires separate user authorization. Never imply access.
- **Contributor lane:** proposing a new problem, signing a contributor
  contract, or sending a package. Requires separate user authorization.

Never send email, submit a form, purchase access, or publish a result without
an explicit instruction covering that action.

A bundled request such as "solve it and submit today" does not by itself open
the contributor lane. Before external submission, the user must confirm the
destination, exact artifact, account or contract terms, and the submission
action. Urgency does not fill in any missing authority field.

## State discipline

Use a file-backed state ledger for findings, directions, progress, and
heartbeat records. When a state helper is installed, use its commands and do
not edit its JSON state by hand. Without a helper, append structured Markdown
or JSONL records with timestamps and immutable evidence paths; never rewrite a
failed direction into success.

The primary metric is the number of lanes with both:

1. a reproduced warmup; and
2. an adversarially tested shadow verifier.

Candidate count, token count, and plausible ideas are not progress metrics.

## Handoffs

- Route exact checks to the included `$verify-frontiermath-candidate` skill.
- When installed, route proof construction to `$construct-math-proof`, proof
  review to `$audit-math-proof`, and bounded falsification to
  `$find-math-counterexample`.
- If those optional skills are unavailable, preserve the same separation of
  authoring, independent audit, and faithful bounded search. Do not skip the
  corresponding control.
- Run an RCI audit on every skill added or structurally changed. If no RCI
  skill is installed, keep a file-backed critique → fix → verify record with
  open fatal and major findings blocking promotion.

## Research basis

Chen et al., *Iteris: Agentic Research Loops for Computational Mathematics*
supports the file-backed explore-plan-execute split and documents why
independent human repair remains necessary:
<https://arxiv.org/abs/2606.02484>.

This paper supplies architectural hypotheses, not a FrontierMath performance
estimate.
