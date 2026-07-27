from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest


HADAMARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HADAMARD))

from audit_lp333_family_cnf import (  # noqa: E402
    LENGTH,
    multiplication_orbits,
    orbit_signature,
    paf_bitset,
    sequence_from_orbits,
    validate_orbits,
)


ID9 = (1, 73, 85, 211, 232, 286)
ID10 = (1, 73, 121, 175, 196, 322)


def test_id9_and_id10_have_the_preregistered_orbit_signature() -> None:
    expected = [[1, 3], [3, 2], [6, 54]]
    for group in (ID9, ID10):
        orbits = multiplication_orbits(group, LENGTH)
        validate_orbits(orbits, group)
        assert len(orbits) == 59
        assert orbit_signature(orbits) == expected


def test_bitset_paf_matches_direct_sum_for_random_orbit_sequence() -> None:
    orbits = multiplication_orbits(ID9, LENGTH)
    rng = random.Random(20260726)
    values = [-1 if rng.getrandbits(1) else 1 for _ in orbits]
    sequence = sequence_from_orbits(orbits, values)
    fast = paf_bitset(sequence)
    direct = [
        sum(
            sequence[index] * sequence[(index + shift) % LENGTH]
            for index in range(LENGTH)
        )
        for shift in range(LENGTH)
    ]
    assert fast == direct


def test_cross_orbit_coordinate_swap_is_rejected() -> None:
    orbits = multiplication_orbits(ID10, LENGTH)
    same_size = [
        index for index, orbit in enumerate(orbits) if len(orbit) == 6
    ]
    first, second = same_size[:2]
    orbits[first][0], orbits[second][0] = (
        orbits[second][0],
        orbits[first][0],
    )
    with pytest.raises(ValueError, match="not a subgroup orbit"):
        validate_orbits(orbits, ID10)
