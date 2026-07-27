# ID10 native pseudo-Boolean calibration

The exact native OPB formula passed the preregistered semantic gate:

- 3,540 variables and 13,752 constraints;
- 1,000 direct semantic assignments;
- 58,000 direct representative-PAF comparisons;
- the published LP(63) positive fixture.

RoundingSat did not reach a terminal result. Its incomplete proof crossed the
1 GiB ceiling after 144.154 seconds at 1,075,661,152 bytes. This attempt is
strictly `UNKNOWN` and falsifies the proof-volume hypothesis for this static
PB implementation.

The generated OPB, partial proof, and logs are intentionally ignored. Tracked
metadata bind their measured hashes and sizes.
