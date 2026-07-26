# LP333 fixed multiplier family ID5: static-symmetry calibration

This directory records a proof-producing CaDiCaL calibration of the ID5 fixed
multiplier family after adding the complete verified 144-action
decimation/swap lex-leader set.

The run is strictly **UNKNOWN**. It reached the preregistered 1 GiB proof
ceiling after 249.66 seconds with an incomplete DRAT stream. The ceiling is not
evidence for satisfiability or unsatisfiability.

Tracked evidence:

- `encoding.json`: exact formula, source, generator, symmetry, and semantic-test
  bindings.
- `calibration/run-manifest.json`: tool hashes, resource limits, negative proof
  control, observed resources, and strict outcome.

The large CNF, partial proof, model stub, and solver logs are intentionally
ignored because their hashes are bound in the tracked metadata and manifest.
