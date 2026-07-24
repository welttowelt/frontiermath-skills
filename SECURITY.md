# Security policy

## Supported surface

Security reports are accepted for the current `main` branch.

## Reporting

Open a GitHub security advisory for vulnerabilities that could execute
untrusted input, escape the documented parser boundary, falsify a verification
packet, or expose local files. Avoid publishing exploit details in a public
issue before a fix is available.

## Untrusted candidates

The included verifiers parse data artifacts. They do not execute candidate
Python, downloaded generators, shell fragments, or prompt-provided commands.
Do not add such execution without a separate security review and an explicit
sandbox contract.

Candidate and contract byte ceilings are checked before parsing, and registered
target ceilings bound the mathematical loops. The scripts do not provide a
hard wall-clock deadline or defend against hostile local filesystem behavior.
Run them with ordinary process and filesystem isolation when denial-of-service
resistance is required.

## Claim boundary

A local `shadow-verifier-pass` covers only the predicates named in its result
packet. It is not an Epoch verifier result and is not a proof of novelty.
