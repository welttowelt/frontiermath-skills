from __future__ import annotations

import random
import sys
from pathlib import Path


HADAMARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HADAMARD))

from benchmark_id3_profile_propagation import (  # noqa: E402
    PafBoundState,
    build_paf_graph,
    gale_ryser,
)
from id3_full_profile_arithmetic import (  # noqa: E402
    LENGTH,
    MULTIPLIER_GENERATOR,
    cyclic_subgroup,
    multiplication_orbits,
    orbit_values_to_sequence,
    periodic_autocorrelations_bitset,
)


def test_gale_ryser_positive_and_negative_controls() -> None:
    assert gale_ryser([2, 1, 1], [2, 1, 1])[0] is True
    assert gale_ryser([3, 3, 0], [3, 2, 1])[0] is False
    assert gale_ryser([2, 2], [1, 1])[0] is False


def test_incremental_paf_state_matches_direct_complete_assignments() -> None:
    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    representatives, constants, edges = build_paf_graph(orbits)
    state = PafBoundState(len(orbits), constants, edges)
    rng = random.Random(20260726)
    values = [
        -1 if rng.getrandbits(1) else 1
        for _ in range(2 * len(orbits))
    ]
    for variable, value in enumerate(values):
        state.assign(variable, value)

    first = orbit_values_to_sequence(orbits, values[: len(orbits)])
    second = orbit_values_to_sequence(orbits, values[len(orbits) :])
    first_paf = periodic_autocorrelations_bitset(first)
    second_paf = periodic_autocorrelations_bitset(second)
    for equation, shift in enumerate(representatives):
        assert state.unassigned_edge_weight[equation] == 0
        assert state.absolute_field_sum[equation] == 0
        assert state.known[equation] == first_paf[shift] + second_paf[shift]


def test_incremental_paf_assignment_rollback_is_exact() -> None:
    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    _, constants, edges = build_paf_graph(orbits)
    state = PafBoundState(len(orbits), constants, edges)
    baseline = (
        list(state.known),
        list(state.unassigned_edge_weight),
        list(state.unresolved_edge_weight),
        list(state.absolute_field_sum),
        [list(row) for row in state.fields],
        [list(row) for row in state.unresolved_weight_counts],
    )
    checkpoint = state.checkpoint()
    for variable in range(0, state.variable_count, 7):
        state.assign(variable, -1 if variable % 2 else 1)
    state.rollback(checkpoint)
    assert state.assignments == [0] * state.variable_count
    assert state.assignment_stack == []
    assert state.assigned_mask == 0
    assert state.negative_mask == 0
    assert list(state.known) == baseline[0]
    assert list(state.unassigned_edge_weight) == baseline[1]
    assert list(state.unresolved_edge_weight) == baseline[2]
    assert list(state.absolute_field_sum) == baseline[3]
    assert state.fields == baseline[4]
    assert state.unresolved_weight_counts == baseline[5]


def test_partial_paf_interval_contains_random_completions() -> None:
    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    representatives, constants, edges = build_paf_graph(orbits)
    rng = random.Random(73)
    fixed = {
        variable: (-1 if rng.getrandbits(1) else 1)
        for variable in range(0, 2 * len(orbits), 11)
    }
    partial = PafBoundState(len(orbits), constants, edges)
    for variable, value in fixed.items():
        partial.assign(variable, value)
    lower = [
        partial.known[equation]
        - partial.absolute_field_sum[equation]
        - partial.unassigned_edge_weight[equation]
        for equation in range(len(representatives))
    ]
    upper = [
        partial.known[equation]
        + partial.absolute_field_sum[equation]
        + partial.unassigned_edge_weight[equation]
        for equation in range(len(representatives))
    ]

    for _ in range(5):
        values = [
            fixed.get(
                variable, -1 if rng.getrandbits(1) else 1
            )
            for variable in range(2 * len(orbits))
        ]
        first = orbit_values_to_sequence(orbits, values[: len(orbits)])
        second = orbit_values_to_sequence(orbits, values[len(orbits) :])
        first_paf = periodic_autocorrelations_bitset(first)
        second_paf = periodic_autocorrelations_bitset(second)
        for equation, shift in enumerate(representatives):
            actual = first_paf[shift] + second_paf[shift]
            assert lower[equation] <= actual <= upper[equation]

