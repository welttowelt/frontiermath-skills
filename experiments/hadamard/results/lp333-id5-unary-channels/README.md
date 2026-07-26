# LP333 ID5: unary cardinality propagation channels

This formula preserves the full ID5 translation-gauged parent and adds exactly
three redundant sequential unary counters:

- 55 negative size-three A orbits;
- 55 negative size-three B orbits;
- 110 active coefficient-three XOR edges in the shift-111 equation.

The first two counts follow from the fixed singleton gauge and row sums. The
third follows from the shift-111 target `334`, fixed singleton contribution
`4`, and coefficient `3`. The channel block adds 107,797 serialized clauses
and is reconstructed exactly by an auditor that does not import the generator.
It also checks 864 source XOR clauses and rejects a one-literal mutation.

The large CNF and proof payloads are ignored; tracked metadata and manifests
bind their hashes.
