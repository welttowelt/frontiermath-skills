# FrontierMath Skills

Two reusable agent skills for research on
[Epoch AI FrontierMath Open Problems](https://epoch.ai/frontiermath/open-problems):

- [`run-frontiermath-campaign`](skills/run-frontiermath-campaign/) keeps a
  versioned, file-backed research lane from public prompt through warmup,
  distinct search directions, negative results, and an auditable candidate
  packet.
- [`verify-frontiermath-candidate`](skills/verify-frontiermath-candidate/)
  checks supported serialized candidates against hashed public-prompt
  contracts and reports exactly what the local checker did and did not test.

The repository currently ships exact shadow verifiers for:

- Hadamard matrices;
- Ramsey Book graph adjacency strings;
- Arithmetic Kakeya six-line certificates under the intended equal-suffix
  graph semantics.

These are public-contract shadow verifiers. They are not Epoch's bespoke
verifier, do not imply access to it, and do not turn a local pass into an Epoch
acceptance or a novelty claim.

## Quick start

Clone the repository and run the adversarial test suite:

```bash
git clone https://github.com/welttowelt/frontiermath-skills.git
cd frontiermath-skills
python3 -m pip install pytest
python3 -m pytest -q -p no:cacheprovider
```

Check the included small fixtures:

```bash
python3 skills/verify-frontiermath-candidate/scripts/verify_hadamard.py \
  skills/verify-frontiermath-candidate/tests/fixtures/hadamard-order-4.csv \
  --contract \
  skills/verify-frontiermath-candidate/tests/fixtures/hadamard-order-4-contract.json

python3 skills/verify-frontiermath-candidate/scripts/verify_ramsey_book.py \
  --adjacency-file \
  skills/verify-frontiermath-candidate/tests/fixtures/ramsey-book-n-2.txt \
  --contract \
  skills/verify-frontiermath-candidate/tests/fixtures/ramsey-book-n-2-contract.json

python3 skills/verify-frontiermath-candidate/scripts/verify_arithmetic_kakeya.py \
  skills/verify-frontiermath-candidate/tests/fixtures/arithmetic-kakeya-katz-tao-7-over-4.txt \
  --contract \
  skills/verify-frontiermath-candidate/contracts/arithmetic-kakeya-warmup-2026-06-27.json
```

To use the campaign skill, point `FRONTIERMATH_WORLD` at a durable directory
for problem notes, state, failed directions, and candidate packets:

```bash
export FRONTIERMATH_WORLD="/absolute/path/to/frontiermath-world"
```

Then invoke the skill in an agent environment that supports `SKILL.md`
packages.

## Verification design

Every checker invocation requires an exact JSON contract whose SHA-256 and
content match the bundled `contracts/manifest.json`. The registered entry
binds:

- checker and problem ID;
- prompt type;
- source URL and retrieval date;
- source artifact and exact prompt hashes;
- target parameter.

Unregistered contracts are rejected, including contracts that reuse a shipped
prompt hash but mutate only the target. Result packets include a privacy-safe
contract ID; candidate, contract, manifest, checker, fixture, and environment
hashes; checked and unchecked predicates; runtime; and an explicit
`epoch_verifier_equivalence: false` field.

Read [the public-contract boundary](skills/verify-frontiermath-candidate/references/public-contract-boundary.md)
before extending a checker.

## Quality status

The current verifier suite has 42 adversarial tests, including contract
mutation attacks, privacy-safe packet checks, and exhaustive
agreement with an independent naive oracle over all 32,768 labeled graphs in
the included \(n=2\) Ramsey Book contract. Arithmetic Kakeya adds a reproduced
\(7/4\) warmup, an independent integer-identity check, a second cycle-map
implementation checked against dense closure, an exact Katz--Tao recurrence
gate, and a separately labeled prefix-only diagnostic that the canonical
same-tail checker rejects.

Both original skills and the Arithmetic Kakeya revision pass a clean-context
rerun from public `main`. The revision's dedicated RCI audit is closed at the
`forward-tested` lifecycle state. None of this is evidence of improved
FrontierMath solve rate. See
[the public RCI record](docs/RCI_AUDIT.md) and
[the open Arithmetic Kakeya RCI record](docs/RCI_AUDIT_ARITHMETIC_KAKEYA.md),
plus
[forward-test cases](docs/FORWARD_TESTS.md).

The repository is distributed clone-first as agent skill folders and scripts;
it is not a Python library package.

## Research basis

The campaign loop is informed by
[Iteris: Agentic Research Loops for Computational Mathematics](https://arxiv.org/abs/2606.02484).
The verification question is informed by
[Machine-Checked Computational Mathematics](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.CALCO.2023.5).
The hashed-contract architecture is a local implementation choice.

See [RESEARCH_BASIS.md](docs/RESEARCH_BASIS.md) for the claim boundary.

## Contributing

New problem families and structural checker changes must arrive with their
public prompt contract, exact source hashes, adversarial fixtures, an
independent cross-check, and an RCI record. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).

This community repository is not affiliated with or endorsed by Epoch AI.
