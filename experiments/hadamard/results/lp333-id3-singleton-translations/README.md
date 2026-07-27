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

The preregistered 300-second CaDiCaL run remained strict `UNKNOWN`. It reached
2,659,000 conflicts and 2,053,017,228 propagations, with a peak observed RSS of
914,620,416 bytes. The incomplete proof payload is 1,064,658,979 bytes
(`a21e95d0d2b016c6e34914ff01741f7d6c288508c75bd851b9a999a89d87280e`);
it is retained only as a hash-bound resource-ceiling artifact and is not a
certificate. Per the preregistration, this selects a structural propagation
channel rather than a larger cap.
