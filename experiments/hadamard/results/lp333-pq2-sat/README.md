# Unrestricted LP333 prescribed pq2-compression SAT slice

This formula encodes the full length-333 Legendre-pair equations with no
nontrivial multiplier assumption. Its only structural restriction is the
prescribed \(11^2\)-compression

`A = [1,11,-11]`, `B = [1,-11,11]`.

That fixes six exact cardinalities over the three residue classes modulo 3.
The formula also quotients all 216 symmetries that preserve this ordered
compression: unit decimation alone for units congruent to one modulo 3, and
unit decimation followed by sequence swap for units congruent to two.

Formula:

- 4,494,772 clauses;
- 725,383 variables;
- SHA-256
  `7a893f92b28a7eed54ccefe5bbb89d28d04132672905abc3635d01a6e3991735`.

The independent auditor reconstructs all 848,886 symmetry clauses and all
111,444 serialized cardinality-channel clauses, validates the functional
lex-leader and counter truth tables, and rejects a one-literal mutation. The
large CNF and solver payloads are ignored; tracked metadata and manifests bind
their hashes.
