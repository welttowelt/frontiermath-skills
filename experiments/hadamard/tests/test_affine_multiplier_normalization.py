from __future__ import annotations

import sys
from pathlib import Path


HADAMARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HADAMARD))

from classify_affine_multiplier_normalization import (  # noqa: E402
    LENGTH,
    affine_orbits,
    all_subgroups,
    crt_9_37,
    enumerate_cocycles,
    generated_subgroup,
    minimal_generators,
    quotient_by_coboundaries,
    row_sum_one_feasible,
    units,
)


def test_crt_9_37_round_trip() -> None:
    reconstructed = {
        crt_9_37(residue_9, residue_37)
        for residue_9 in range(9)
        for residue_37 in range(37)
    }
    assert reconstructed == set(range(LENGTH))


def test_unit_subgroup_lattice_has_80_members() -> None:
    unit_group = units(LENGTH)
    assert len(unit_group) == 216
    subgroups = all_subgroups(unit_group, LENGTH)
    assert len(subgroups) == 80
    assert len(set(subgroups)) == 80


def test_id3_has_three_mod9_affine_classes_and_no_new_row_sum_class() -> None:
    group = generated_subgroup((10,), LENGTH)
    assert group == frozenset({1, 10, 100})
    generators = minimal_generators(group, LENGTH)
    cocycles_9 = enumerate_cocycles(group, generators, 9, LENGTH)
    classes_9, _ = quotient_by_coboundaries(group, cocycles_9, 9)
    cocycles_37 = enumerate_cocycles(group, generators, 37, LENGTH)
    classes_37, _ = quotient_by_coboundaries(
        group, cocycles_37, 37
    )
    assert len(classes_9) == 3
    assert len(classes_37) == 1

    for class_9 in classes_9:
        cocycle = tuple(
            crt_9_37(residue_9, residue_37)
            for residue_9, residue_37 in zip(
                class_9, classes_37[0], strict=True
            )
        )
        orbits = affine_orbits(group, cocycle)
        if any(cocycle):
            assert {len(orbit) for orbit in orbits} == {3}
            assert not row_sum_one_feasible(orbits)


def test_coboundary_affine_action_is_a_shifted_fixed_action() -> None:
    group = generated_subgroup((73, 85), LENGTH)
    shift = 41
    cocycle = tuple(
        (1 - element) * shift % LENGTH for element in sorted(group)
    )
    affine_sizes = sorted(map(len, affine_orbits(group, cocycle)))
    fixed_sizes = sorted(
        map(len, affine_orbits(group, (0,) * len(group)))
    )
    assert affine_sizes == fixed_sizes
