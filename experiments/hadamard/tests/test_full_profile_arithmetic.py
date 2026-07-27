from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest


HADAMARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HADAMARD))

from id3_full_profile_arithmetic import (  # noqa: E402
    LENGTH,
    MULTIPLIER_GENERATOR,
    crt_grid_orbits,
    crt_pair_to_index,
    cyclic_subgroup,
    multiplication_orbits,
    orbit_signature,
    orbit_values_to_sequence,
    periodic_autocorrelations_bitset,
    periodic_autocorrelations_naive,
    sequence_to_sign_table,
    sign_table_to_sequence,
    validate_crt_grid_against_orbits,
    validate_orbit_partition,
)


def test_id3_orbit_signature_and_crt_grid_agree() -> None:
    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    assert subgroup == (1, 10, 100)
    orbits = multiplication_orbits(subgroup, LENGTH)
    assert len(orbits) == 117
    assert orbit_signature(orbits) == {1: 9, 3: 108}
    assert len(crt_grid_orbits()) == 117
    validate_crt_grid_against_orbits(orbits)


def test_all_crt_pairs_round_trip() -> None:
    indices = {
        crt_pair_to_index(residue9, residue37)
        for residue9 in range(9)
        for residue37 in range(37)
    }
    assert indices == set(range(LENGTH))
    for index in indices:
        assert crt_pair_to_index(index % 9, index % 37) == index


def test_sign_table_sequence_round_trip() -> None:
    rng = random.Random(20260726)
    table = [
        [-1 if rng.getrandbits(1) else 1 for _ in range(13)]
        for _ in range(9)
    ]
    sequence = sign_table_to_sequence(table)
    assert sequence_to_sign_table(sequence) == table


def test_bitset_paf_matches_naive() -> None:
    rng = random.Random(7301)
    for _ in range(5):
        sequence = [
            -1 if rng.getrandbits(1) else 1 for _ in range(LENGTH)
        ]
        assert (
            periodic_autocorrelations_bitset(sequence)
            == periodic_autocorrelations_naive(sequence)
        )


def test_corrupted_orbit_partition_is_rejected() -> None:
    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    candidates = [index for index, orbit in enumerate(orbits) if len(orbit) == 3]
    first, second = candidates[:2]
    orbits[first][0], orbits[second][0] = (
        orbits[second][0],
        orbits[first][0],
    )
    with pytest.raises(ValueError, match="not the subgroup orbit"):
        validate_orbit_partition(orbits, subgroup, LENGTH)


def test_orbit_values_and_crt_table_describe_same_sequence() -> None:
    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    rng = random.Random(117)
    values = [-1 if rng.getrandbits(1) else 1 for _ in orbits]
    sequence = orbit_values_to_sequence(orbits, values)
    assert sign_table_to_sequence(sequence_to_sign_table(sequence)) == sequence

