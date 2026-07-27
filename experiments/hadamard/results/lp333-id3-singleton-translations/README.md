# LP333 ID3: singleton translation canonicalization

This unrestricted fixed-ID3 formula appends 452 eight-literal clauses to its
full static-symmetry parent. The clauses retain one lexicographically least
normalized singleton pattern under the nine translations by multiples of 37,
independently in both sequences.

Exact enumeration gives:

- 256 normalized nine-bit singleton patterns;
- 30 translation orbits, with size histogram `1:1, 3:1, 9:28`;
- 171 row-feasible patterns;
- 19 row-feasible orbits, all of size nine;
- exact independent pair symmetry factor `81`.

The independent audit reconstructs all 452 clauses, checks 23,904 direct PAF
automorphism identities, binds the unrestricted parent, and rejects a
one-literal mutation. The large CNF and proof payloads are ignored; tracked
metadata and manifests bind their hashes.
