# Contributing

Contributions are welcome when they preserve reproducibility and claim
calibration.

## New checker requirements

A new problem family or structural checker change must include:

1. the exact public prompt and retrieval date;
2. source-artifact and exact-prompt SHA-256 hashes;
3. a machine-readable contract binding the target parameter;
4. positive, negative, malformed, boundary, equivalent-representation, and
   adversarial-near-miss fixtures;
5. a different implementation or mathematical argument for the decisive
   predicate;
6. structured packets naming checked and unchecked predicates;
7. an RCI critique-fix-verify record;
8. a clean-context forward test.

Do not weaken a predicate to admit a promising candidate. Do not label a local
checker as equivalent to Epoch's verifier.

## Development

```bash
python3 -m pip install pytest
python3 -m pytest -q
```

Keep Python 3.9 compatibility unless a version change is discussed and tested.
Run the full suite before opening a pull request.

## Pull requests

Describe:

- the public contract being implemented;
- the strongest seeded invalid candidate;
- the independent cross-check;
- any predicate that remains unavailable or ambiguous;
- the RCI findings and repairs.
