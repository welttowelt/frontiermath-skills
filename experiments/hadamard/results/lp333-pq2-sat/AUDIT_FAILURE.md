# Arithmetic audit failure

Status: `audit-failed`; all target processes were terminated immediately on
discovery.

The formula in this directory used the false factorization

\[
333=3\cdot11^2.
\]

Since \(3\cdot11^2=363\), the paper's \(pq^2\) specialization was invalid.
There is also a solver-free contradiction internal to the proposed
length-three compression:

- each proposed compressed row `[1,11,-11]` or `[1,-11,11]` has squared
  norm \(1+121+121=243\);
- the combined compressed energy is therefore \(486\), not 728.

For a length-three compression of two LP(333) rows, the compression factor
would be 111, so the required combined energy is

\[
2(333)-2(111)+2=446.
\]

Equivalently, the proposed compressed rows have combined nonzero periodic
autocorrelation \(-242\), while summing 111 full LP shifts requires
\(-222\). Either identity rejects the slice.

The correct factorization in the source regime is

\[
333=37\cdot3^2.
\]

Its length-37 rows `[1,3 chi_37]` and `[1,-3 chi_37]` have combined energy
650 and combined nonzero PAF \(-18\), exactly matching compression factor
9. No model, UNSAT claim, or mathematical candidate was produced by the
invalid runs.
