# Research basis and transfer boundary

## Campaign loop

Chen et al.,
[Iteris: Agentic Research Loops for Computational Mathematics](https://arxiv.org/abs/2606.02484),
reports a file-backed explore, plan, execute, and review workflow across two
open computational-mathematics case studies.

This repository transfers three architectural hypotheses:

- keep durable state outside the conversation;
- probe structurally distinct routes before committing the official plan;
- retain failed attempts as inputs to later search.

It does not transfer a solve-rate estimate to FrontierMath. The reported cases,
tools, budgets, and review process differ from this repository.

## Verification question

Mahboubi's
[Machine-Checked Computational Mathematics](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.CALCO.2023.5)
is a one-page invited-talk abstract about applying formal-methods techniques to
programs used to produce mathematics.

It supports the verification question: what evidence should accompany a
computational mathematical result so that another channel can check it?

The required hashed contracts, result-packet schema, fixture inventory, and
shadow-verifier architecture in this repository are local implementation
choices. They are not claims from the abstract.

## Adoption status

Both skills have passed structural validation, adversarial tests, and
clean-context forward tests. No paired baseline study has established faster
research or a higher FrontierMath solve rate.
