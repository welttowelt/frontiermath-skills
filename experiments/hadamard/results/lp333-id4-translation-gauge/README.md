# LP333 ID4: independent normalized-translation gauge

This formula retains the original 112 PAF PB encodings and 143
decimation/swap lex leaders, then fixes the independent normalized-translation
gauge of both sequences.

For ID4 the translations preserving the fixed H-invariant space are exactly
`0`, `111`, and `222`. Row-sum arithmetic excludes singleton pattern `000`;
the other normalized patterns `001`, `010`, and `011` form one translation
orbit. Fixing `001` independently in A and B therefore removes an exact
factor-nine symmetry.

The independent audit recomputes the modular annihilator and row cases, checks
15,936 direct PAF automorphism identities, and verifies all eight serialized
unit-gadget clauses. The CNF and proof payloads are ignored; tracked metadata
and manifests bind their hashes.
