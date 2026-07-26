#!/usr/bin/env python3
"""Benchmark fixed-margin and exact partial-PAF propagation on profile 73.

The search branches on complete rows or columns of the two 9x12 non-singleton
sign matrices.  Every child receives a necessary-and-sufficient residual
fixed-margin test.  The second variant also removes forced all-zero/all-one
lines.  The third maintains exact integer bounds for all 116 independent full
PAF equations.

This is a bounded structural benchmark.  TIMEOUT or a candidate ceiling has
no negative mathematical force.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import platform
import time
from collections import Counter
from dataclasses import dataclass
from math import gcd
from pathlib import Path
from typing import Any, Iterable

from id3_full_profile_arithmetic import (
    LENGTH,
    MOD9,
    MULTIPLIER_GENERATOR,
    TARGET_COMBINED_PAF,
    crt_grid_orbits,
    cyclic_subgroup,
    multiplication_orbits,
    orbit_signature,
    orbit_values_to_sequence,
    periodic_autocorrelations_bitset,
)


GRID_COLUMNS = 12
SEQUENCES = 2
ARCHIVED_CPSAT_BRANCHES = 5_878_941
ARCHIVED_CPSAT_SECONDS = 300.187


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gale_ryser(
    row_degrees: Iterable[int], column_degrees: Iterable[int]
) -> tuple[bool, str]:
    """Necessary-and-sufficient feasibility for a binary matrix."""

    rows = sorted(row_degrees, reverse=True)
    columns = sorted(column_degrees, reverse=True)
    if any(degree < 0 or degree > len(columns) for degree in rows):
        return False, "row degree outside the residual column count"
    if any(degree < 0 or degree > len(rows) for degree in columns):
        return False, "column degree outside the residual row count"
    if sum(rows) != sum(columns):
        return False, "residual degree sums differ"
    prefix = 0
    for count, degree in enumerate(rows, 1):
        prefix += degree
        conjugate = sum(min(count, column) for column in columns)
        if prefix > conjugate:
            return False, f"Gale-Ryser inequality fails at prefix {count}"
    return True, "feasible"


@dataclass
class MatrixState:
    row_remaining: list[int]
    column_remaining: list[int]
    active_rows: int = (1 << MOD9) - 1
    active_columns: int = (1 << GRID_COLUMNS) - 1

    def snapshot(self) -> tuple[list[int], list[int], int, int]:
        return (
            list(self.row_remaining),
            list(self.column_remaining),
            self.active_rows,
            self.active_columns,
        )

    def restore(
        self, snapshot: tuple[list[int], list[int], int, int]
    ) -> None:
        rows, columns, active_rows, active_columns = snapshot
        self.row_remaining[:] = rows
        self.column_remaining[:] = columns
        self.active_rows = active_rows
        self.active_columns = active_columns

    def rows(self) -> list[int]:
        return [
            row for row in range(MOD9) if self.active_rows & (1 << row)
        ]

    def columns(self) -> list[int]:
        return [
            column
            for column in range(GRID_COLUMNS)
            if self.active_columns & (1 << column)
        ]

    def feasible(self) -> tuple[bool, str]:
        return gale_ryser(
            [self.row_remaining[row] for row in self.rows()],
            [
                self.column_remaining[column]
                for column in self.columns()
            ],
        )

    def complete(self) -> bool:
        return self.active_rows == 0 and self.active_columns == 0


def build_paf_graph(
    orbits: list[list[int]],
) -> tuple[list[int], list[int], list[list[tuple[int, int, int]]]]:
    index = [0] * LENGTH
    for orbit_index, orbit in enumerate(orbits):
        for position in orbit:
            index[position] = orbit_index
    representatives = [orbit[0] for orbit in orbits if orbit != [0]]
    constants: list[int] = []
    equation_edges: list[list[tuple[int, int, int]]] = []
    for shift in representatives:
        edges: Counter[tuple[int, int]] = Counter()
        constant = 0
        for position in range(LENGTH):
            left = index[position]
            right = index[(position + shift) % LENGTH]
            if left == right:
                constant += 1
            else:
                edges[tuple(sorted((left, right)))] += 1
        constants.append(constant)
        equation_edges.append(
            [
                (left, right, weight)
                for (left, right), weight in sorted(edges.items())
            ]
        )
    return representatives, constants, equation_edges


class PafBoundState:
    """Mutable exact interval state with reversible LIFO assignments."""

    def __init__(
        self,
        orbit_count: int,
        constants: list[int],
        equation_edges: list[list[tuple[int, int, int]]],
    ) -> None:
        self.orbit_count = orbit_count
        self.variable_count = SEQUENCES * orbit_count
        self.equation_count = len(equation_edges)
        self.assignments = [0] * self.variable_count
        self.assignment_stack: list[int] = []
        self.assigned_mask = 0
        self.negative_mask = 0

        self.edges: list[list[tuple[int, int, int]]] = []
        self.adjacency: list[list[tuple[int, int, int]]] = [
            [] for _ in range(self.variable_count)
        ]
        maximum_weight = 0
        for equation_index, base_edges in enumerate(equation_edges):
            combined: list[tuple[int, int, int]] = []
            for sequence_index in range(SEQUENCES):
                offset = sequence_index * orbit_count
                for left, right, weight in base_edges:
                    global_left = offset + left
                    global_right = offset + right
                    combined.append((global_left, global_right, weight))
                    self.adjacency[global_left].append(
                        (equation_index, global_right, weight)
                    )
                    self.adjacency[global_right].append(
                        (equation_index, global_left, weight)
                    )
                    maximum_weight = max(maximum_weight, weight)
            self.edges.append(combined)

        self.maximum_weight = maximum_weight
        self.known = [2 * constant for constant in constants]
        self.unassigned_edge_weight = [
            sum(weight for _, _, weight in edges) for edges in self.edges
        ]
        self.unresolved_edge_weight = list(self.unassigned_edge_weight)
        self.fields = [
            [0] * self.variable_count for _ in range(self.equation_count)
        ]
        self.absolute_field_sum = [0] * self.equation_count
        self.unresolved_weight_counts = [
            [0] * (maximum_weight + 1)
            for _ in range(self.equation_count)
        ]
        for equation_index, edges in enumerate(self.edges):
            for _, _, weight in edges:
                self.unresolved_weight_counts[equation_index][weight] += 1
        self.variable_equations = [
            sorted({equation for equation, _, _ in adjacent})
            for adjacent in self.adjacency
        ]

    def checkpoint(self) -> int:
        return len(self.assignment_stack)

    def assign(self, variable: int, sign: int) -> None:
        if sign not in (-1, 1):
            raise ValueError("assigned sign must be +/-1")
        if self.assignments[variable] != 0:
            raise ValueError(f"variable {variable} is already assigned")

        self.assignments[variable] = sign
        self.assignment_stack.append(variable)
        self.assigned_mask |= 1 << variable
        if sign == -1:
            self.negative_mask |= 1 << variable

        for equation in self.variable_equations[variable]:
            field = self.fields[equation][variable]
            self.known[equation] += field * sign
            self.absolute_field_sum[equation] -= abs(field)
            self.fields[equation][variable] = 0

        for equation, other, weight in self.adjacency[variable]:
            if self.assignments[other] == 0:
                self.unassigned_edge_weight[equation] -= weight
                old = self.fields[equation][other]
                new = old + weight * sign
                self.fields[equation][other] = new
                self.absolute_field_sum[equation] += abs(new) - abs(old)
            else:
                self.unresolved_edge_weight[equation] -= weight
                self.unresolved_weight_counts[equation][weight] -= 1

    def unassign_last(self) -> None:
        variable = self.assignment_stack.pop()
        sign = self.assignments[variable]
        reconstructed_fields: dict[int, int] = {
            equation: 0 for equation in self.variable_equations[variable]
        }

        for equation, other, weight in self.adjacency[variable]:
            if self.assignments[other] == 0:
                old = self.fields[equation][other]
                new = old - weight * sign
                self.fields[equation][other] = new
                self.absolute_field_sum[equation] += abs(new) - abs(old)
                self.unassigned_edge_weight[equation] += weight
            else:
                reconstructed_fields[equation] += (
                    weight * self.assignments[other]
                )
                self.unresolved_edge_weight[equation] += weight
                self.unresolved_weight_counts[equation][weight] += 1

        for equation, field in reconstructed_fields.items():
            self.known[equation] -= field * sign
            self.fields[equation][variable] = field
            self.absolute_field_sum[equation] += abs(field)

        self.assignments[variable] = 0
        self.assigned_mask &= ~(1 << variable)
        self.negative_mask &= ~(1 << variable)

    def rollback(self, checkpoint: int) -> None:
        while len(self.assignment_stack) > checkpoint:
            self.unassign_last()

    def bounds(
        self, target: int
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Return the first impossible equation and every equality boundary."""

        violation = None
        boundaries: list[dict[str, Any]] = []
        for equation in range(self.equation_count):
            radius = (
                self.absolute_field_sum[equation]
                + self.unassigned_edge_weight[equation]
            )
            lower = self.known[equation] - radius
            upper = self.known[equation] + radius
            delta = target - self.known[equation]
            reason = None
            if target < lower or target > upper:
                reason = "interval"
            else:
                common_divisor = 0
                for weight, count in enumerate(
                    self.unresolved_weight_counts[equation]
                ):
                    if weight and count:
                        common_divisor = gcd(common_divisor, weight)
                if common_divisor:
                    modulus = 2 * common_divisor
                    if (
                        self.unresolved_edge_weight[equation] - delta
                    ) % modulus:
                        reason = "edge-weight-congruence"
                elif delta != 0:
                    reason = "fully-resolved-mismatch"

            if target in (lower, upper):
                boundaries.append(
                    {
                        "equation": equation,
                        "known": self.known[equation],
                        "radius": radius,
                        "lower": lower,
                        "upper": upper,
                        "target": target,
                    }
                )
            if reason is not None and violation is None:
                violation = {
                    "equation": equation,
                    "known": self.known[equation],
                    "radius": radius,
                    "lower": lower,
                    "upper": upper,
                    "target": target,
                    "delta": delta,
                    "unresolved_edge_weight": self.unresolved_edge_weight[
                        equation
                    ],
                    "reason": reason,
                }
        return violation, boundaries


@dataclass(frozen=True)
class LineChoice:
    sequence: int
    axis: str
    index: int
    mandatory: tuple[int, ...]
    optional: tuple[int, ...]
    choose: int
    completion_count: int


class ProfileSearch:
    def __init__(
        self,
        record: dict[str, Any],
        representatives: list[int],
        orbits: list[list[int]],
        constants: list[int],
        equation_edges: list[list[tuple[int, int, int]]],
        *,
        variant: str,
        max_seconds: float,
        max_candidates: int,
        log_events: bool,
        max_event_records: int,
    ) -> None:
        if variant not in {"margins", "forced", "paf"}:
            raise ValueError(f"unknown variant: {variant}")
        self.record = record
        self.representatives = representatives
        self.orbits = orbits
        self.variant = variant
        self.use_forcing = variant in {"forced", "paf"}
        self.use_paf = variant == "paf"
        self.max_seconds = max_seconds
        self.max_candidates = max_candidates
        self.log_events = log_events
        self.max_event_records = max_event_records
        self.events: list[dict[str, Any]] = []
        self.event_overflow = False

        self.paf = PafBoundState(len(orbits), constants, equation_edges)
        grid_lookup = {
            frozenset(orbit): index for index, orbit in enumerate(orbits)
        }
        grid = crt_grid_orbits()
        self.cell_orbits = [
            [
                grid_lookup[frozenset(grid[row * 13 + column + 1])]
                for column in range(GRID_COLUMNS)
            ]
            for row in range(MOD9)
        ]
        self.singleton_orbits = [
            grid_lookup[frozenset(grid[row * 13])] for row in range(MOD9)
        ]
        self.cell_variables = [
            [
                [
                    sequence * len(orbits) + self.cell_orbits[row][column]
                    for column in range(GRID_COLUMNS)
                ]
                for row in range(MOD9)
            ]
            for sequence in range(SEQUENCES)
        ]

        self.matrices: list[MatrixState] = []
        for sequence, name in enumerate(("a", "b")):
            binary = record[f"{name}_margin_9_by_12"]
            row_degrees = [sum(row) for row in binary]
            column_degrees = [
                sum(binary[row][column] for row in range(MOD9))
                for column in range(GRID_COLUMNS)
            ]
            self.matrices.append(
                MatrixState(row_degrees, column_degrees)
            )
            compressed = record[f"{name}_tilde"]
            for row, value in enumerate(compressed):
                singleton_sign = 1 if value % 3 == 1 else -1
                variable = sequence * len(orbits) + self.singleton_orbits[row]
                self.paf.assign(variable, singleton_sign)
        self.base_checkpoint = self.paf.checkpoint()

        self.started = 0.0
        self.stop = False
        self.termination = "not-started"
        self.nodes = 0
        self.candidate_children = 0
        self.margin_feasible_children = 0
        self.margin_prunes = 0
        self.paf_prunes = 0
        self.paf_survivors = 0
        self.boundary_events = 0
        self.forced_lines = 0
        self.leaves = 0
        self.max_depth = 0
        self.solution: dict[str, Any] | None = None

    def snapshots(self):
        return [matrix.snapshot() for matrix in self.matrices]

    def restore(self, snapshots, checkpoint: int) -> None:
        for matrix, snapshot in zip(self.matrices, snapshots):
            matrix.restore(snapshot)
        self.paf.rollback(checkpoint)

    def log_event(
        self,
        event_type: str,
        depth: int,
        detail: dict[str, Any],
    ) -> None:
        if not self.log_events:
            return
        if len(self.events) >= self.max_event_records:
            self.event_overflow = True
            return
        self.events.append(
            {
                "event_type": event_type,
                "candidate_child": self.candidate_children,
                "depth": depth,
                "assigned_mask_hex": hex(self.paf.assigned_mask),
                "negative_mask_hex": hex(self.paf.negative_mask),
                "detail": detail,
            }
        )

    def check_limits(self) -> bool:
        if self.stop:
            return True
        if self.candidate_children >= self.max_candidates:
            self.stop = True
            self.termination = "candidate-ceiling"
            return True
        if time.perf_counter() - self.started >= self.max_seconds:
            self.stop = True
            self.termination = "time-ceiling"
            return True
        return False

    def line_choice(
        self, sequence: int, axis: str, index: int
    ) -> LineChoice | None:
        matrix = self.matrices[sequence]
        active_rows = matrix.rows()
        active_columns = matrix.columns()
        if axis == "row":
            degree = matrix.row_remaining[index]
            mandatory = tuple(
                column
                for column in active_columns
                if matrix.column_remaining[column] == len(active_rows)
            )
            optional = tuple(
                column
                for column in active_columns
                if 0 < matrix.column_remaining[column] < len(active_rows)
            )
        else:
            degree = matrix.column_remaining[index]
            mandatory = tuple(
                row
                for row in active_rows
                if matrix.row_remaining[row] == len(active_columns)
            )
            optional = tuple(
                row
                for row in active_rows
                if 0 < matrix.row_remaining[row] < len(active_columns)
            )
        choose = degree - len(mandatory)
        if choose < 0 or choose > len(optional):
            return None
        return LineChoice(
            sequence=sequence,
            axis=axis,
            index=index,
            mandatory=mandatory,
            optional=optional,
            choose=choose,
            completion_count=math.comb(len(optional), choose),
        )

    def choose_line(self) -> LineChoice:
        choices: list[LineChoice] = []
        for sequence, matrix in enumerate(self.matrices):
            for row in matrix.rows():
                choice = self.line_choice(sequence, "row", row)
                if choice is not None:
                    choices.append(choice)
            for column in matrix.columns():
                choice = self.line_choice(sequence, "column", column)
                if choice is not None:
                    choices.append(choice)
        if not choices:
            raise ValueError("incomplete margin state has no branchable line")
        return min(
            choices,
            key=lambda choice: (
                choice.completion_count,
                choice.sequence,
                0 if choice.axis == "row" else 1,
                choice.index,
            ),
        )

    def patterns(self, choice: LineChoice):
        for selected_optional in itertools.combinations(
            choice.optional, choice.choose
        ):
            yield frozenset(choice.mandatory + selected_optional)

    def apply_line(self, choice: LineChoice, selected: frozenset[int]) -> None:
        matrix = self.matrices[choice.sequence]
        if choice.axis == "row":
            row = choice.index
            columns = matrix.columns()
            if sum(column in selected for column in columns) != matrix.row_remaining[
                row
            ]:
                raise ValueError("row pattern has the wrong degree")
            for column in columns:
                bit = int(column in selected)
                variable = self.cell_variables[choice.sequence][row][column]
                self.paf.assign(variable, 1 if bit else -1)
                matrix.column_remaining[column] -= bit
            matrix.row_remaining[row] = 0
            matrix.active_rows &= ~(1 << row)
        else:
            column = choice.index
            rows = matrix.rows()
            if sum(row in selected for row in rows) != matrix.column_remaining[
                column
            ]:
                raise ValueError("column pattern has the wrong degree")
            for row in rows:
                bit = int(row in selected)
                variable = self.cell_variables[choice.sequence][row][column]
                self.paf.assign(variable, 1 if bit else -1)
                matrix.row_remaining[row] -= bit
            matrix.column_remaining[column] = 0
            matrix.active_columns &= ~(1 << column)

    def propagate_forced(self) -> tuple[bool, str]:
        while True:
            for matrix in self.matrices:
                feasible, reason = matrix.feasible()
                if not feasible:
                    return False, reason
            forced_choice = None
            forced_selected: frozenset[int] | None = None
            for sequence, matrix in enumerate(self.matrices):
                rows = matrix.rows()
                columns = matrix.columns()
                for row in rows:
                    degree = matrix.row_remaining[row]
                    if degree in (0, len(columns)):
                        forced_choice = self.line_choice(sequence, "row", row)
                        if forced_choice is None:
                            return False, "forced row has no completion"
                        forced_selected = frozenset(
                            columns if degree == len(columns) else ()
                        )
                        break
                if forced_choice is not None:
                    break
                for column in columns:
                    degree = matrix.column_remaining[column]
                    if degree in (0, len(rows)):
                        forced_choice = self.line_choice(
                            sequence, "column", column
                        )
                        if forced_choice is None:
                            return False, "forced column has no completion"
                        forced_selected = frozenset(
                            rows if degree == len(rows) else ()
                        )
                        break
                if forced_choice is not None:
                    break
            if forced_choice is None:
                return True, "fixed point"
            assert forced_selected is not None
            self.apply_line(forced_choice, forced_selected)
            self.forced_lines += 1

    def all_margins_feasible(self) -> tuple[bool, str]:
        for sequence, matrix in enumerate(self.matrices):
            feasible, reason = matrix.feasible()
            if not feasible:
                return False, f"sequence {sequence}: {reason}"
        return True, "feasible"

    def check_paf(
        self, depth: int
    ) -> dict[str, Any] | None:
        violation, boundaries = self.paf.bounds(TARGET_COMBINED_PAF)
        for boundary in boundaries:
            boundary["shift"] = self.representatives[boundary["equation"]]
            self.boundary_events += 1
            self.log_event("paf-boundary-equality", depth, boundary)
        if violation is not None:
            violation["shift"] = self.representatives[
                violation["equation"]
            ]
        return violation

    def materialize_solution(self) -> dict[str, Any]:
        if any(value == 0 for value in self.paf.assignments):
            raise ValueError("cannot materialize a partial solution")
        first_values = self.paf.assignments[: len(self.orbits)]
        second_values = self.paf.assignments[len(self.orbits) :]
        first = orbit_values_to_sequence(self.orbits, first_values)
        second = orbit_values_to_sequence(self.orbits, second_values)
        first_paf = periodic_autocorrelations_bitset(first)
        second_paf = periodic_autocorrelations_bitset(second)
        violations = [
            shift
            for shift in range(1, LENGTH)
            if first_paf[shift] + second_paf[shift] != TARGET_COMBINED_PAF
        ]
        return {
            "a_orbit_values": first_values,
            "b_orbit_values": second_values,
            "a_sequence": first,
            "b_sequence": second,
            "a_row_sum": sum(first),
            "b_row_sum": sum(second),
            "full_paf_violations": violations,
            "verified_legendre_pair": (
                sum(first) in (-1, 1)
                and sum(second) in (-1, 1)
                and not violations
            ),
        }

    def visit(self, depth: int) -> None:
        if self.check_limits():
            return
        self.nodes += 1
        self.max_depth = max(self.max_depth, depth)
        if all(matrix.complete() for matrix in self.matrices):
            self.leaves += 1
            if self.use_paf:
                solution = self.materialize_solution()
                if solution["verified_legendre_pair"]:
                    self.solution = solution
                    self.stop = True
                    self.termination = "verified-sat"
            return

        choice = self.choose_line()
        for selected in self.patterns(choice):
            if self.check_limits():
                return
            self.candidate_children += 1
            checkpoint = self.paf.checkpoint()
            snapshots = self.snapshots()
            self.apply_line(choice, selected)

            if self.use_forcing:
                feasible, reason = self.propagate_forced()
            else:
                feasible, reason = self.all_margins_feasible()
            if not feasible:
                self.margin_prunes += 1
                self.log_event(
                    "margin-prune",
                    depth + 1,
                    {
                        "reason": reason,
                        "sequence": choice.sequence,
                        "axis": choice.axis,
                        "line": choice.index,
                    },
                )
                self.restore(snapshots, checkpoint)
                continue

            self.margin_feasible_children += 1
            if self.use_paf:
                violation = self.check_paf(depth + 1)
                if violation is not None:
                    self.paf_prunes += 1
                    self.log_event("paf-prune", depth + 1, violation)
                    self.restore(snapshots, checkpoint)
                    continue
                self.paf_survivors += 1

            self.visit(depth + 1)
            self.restore(snapshots, checkpoint)
            if self.stop:
                return

    def run(self) -> dict[str, Any]:
        for matrix in self.matrices:
            feasible, reason = matrix.feasible()
            if not feasible:
                raise ValueError(f"root margins are infeasible: {reason}")
        root_violation = self.check_paf(0) if self.use_paf else None
        if root_violation is not None:
            raise ValueError(f"root PAF bounds are infeasible: {root_violation}")

        self.started = time.perf_counter()
        self.termination = "exhausted"
        self.visit(0)
        wall_seconds = time.perf_counter() - self.started
        if not self.stop and self.termination == "exhausted":
            status = "SAT" if self.solution is not None else "EXHAUSTED"
        elif self.solution is not None:
            status = "SAT"
        else:
            status = "UNKNOWN"

        event_counts = Counter(event["event_type"] for event in self.events)
        prune_denominator = self.margin_feasible_children
        paf_prune_fraction = (
            self.paf_prunes / prune_denominator if prune_denominator else 0.0
        )
        structural_reduction = (
            prune_denominator / self.paf_survivors
            if self.use_paf and self.paf_survivors
            else None
        )
        return {
            "variant": self.variant,
            "status": status,
            "termination": self.termination,
            "wall_seconds": wall_seconds,
            "max_seconds": self.max_seconds,
            "max_candidates": self.max_candidates,
            "nodes_entered": self.nodes,
            "candidate_children": self.candidate_children,
            "margin_feasible_children": self.margin_feasible_children,
            "margin_prunes": self.margin_prunes,
            "paf_prunes": self.paf_prunes,
            "paf_survivors": self.paf_survivors,
            "paf_prune_fraction_of_margin_feasible": paf_prune_fraction,
            "structural_reduction_margin_feasible_over_paf_survivors": (
                structural_reduction
            ),
            "forced_lines": self.forced_lines,
            "leaves": self.leaves,
            "maximum_branch_depth": self.max_depth,
            "nodes_per_second": self.nodes / wall_seconds if wall_seconds else 0,
            "candidate_children_per_second": (
                self.candidate_children / wall_seconds if wall_seconds else 0
            ),
            "boundary_equality_events": self.boundary_events,
            "logged_event_counts": dict(sorted(event_counts.items())),
            "event_records": len(self.events),
            "event_log_overflow": self.event_overflow,
            "solution": self.solution,
        }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return sha256_file(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_ledger", type=Path)
    parser.add_argument("--profile-id", type=int, default=73)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--event-log", required=True, type=Path)
    parser.add_argument("--max-seconds", type=float, default=60.0)
    parser.add_argument("--max-candidates", type=int, default=100_000)
    parser.add_argument("--max-event-records", type=int, default=500_000)
    args = parser.parse_args()
    if args.max_seconds <= 0 or args.max_candidates <= 0:
        raise ValueError("benchmark ceilings must be positive")

    ledger = json.loads(args.profile_ledger.read_text(encoding="utf-8"))
    record = next(
        item for item in ledger["records"] if item["id"] == args.profile_id
    )
    if record.get("feasible") is not True:
        raise ValueError("selected profile is not witness-carrying")

    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    representatives, constants, equation_edges = build_paf_graph(orbits)
    if (
        subgroup != (1, 10, 100)
        or orbit_signature(orbits) != {1: 9, 3: 108}
        or len(representatives) != 116
    ):
        raise ValueError("ID3 arithmetic signature changed")

    results: list[dict[str, Any]] = []
    paf_search: ProfileSearch | None = None
    for variant in ("margins", "forced", "paf"):
        search = ProfileSearch(
            record,
            representatives,
            orbits,
            constants,
            equation_edges,
            variant=variant,
            max_seconds=args.max_seconds,
            max_candidates=args.max_candidates,
            log_events=variant == "paf",
            max_event_records=args.max_event_records,
        )
        result = search.run()
        results.append(result)
        if variant == "paf":
            paf_search = search
        print(
            f"{variant}: {result['termination']}, "
            f"{result['candidate_children']} candidates, "
            f"{result['nodes_entered']} nodes, "
            f"{result['wall_seconds']:.3f}s"
        )

    assert paf_search is not None
    event_log_sha256 = write_jsonl(args.event_log, paf_search.events)
    paf_result = results[-1]
    promotion_checks = {
        "paf_prunes_at_least_half_of_margin_feasible_children": (
            paf_result["paf_prune_fraction_of_margin_feasible"] >= 0.5
        ),
        "structural_reduction_at_least_3x": (
            paf_result[
                "structural_reduction_margin_feasible_over_paf_survivors"
            ]
            is not None
            and paf_result[
                "structural_reduction_margin_feasible_over_paf_survivors"
            ]
            >= 3.0
        ),
        "complete_event_log": not paf_result["event_log_overflow"],
    }
    gate_status = (
        "benchmark-pass"
        if all(promotion_checks.values())
        else "benchmark-fail"
    )

    output = {
        "schema": "frontiermath-hadamard-id3-profile-propagation-benchmark-v1",
        "status": gate_status,
        "scope": (
            "three deterministic bounded variants over the exact profile-73 "
            "fixed margins; only the PAF variant contains the complete "
            "116-equation full-ID3 predicate"
        ),
        "claim_boundary": (
            "UNKNOWN and benchmark-pass are not SAT/UNSAT claims; only a "
            "directly verified full pair or a replayed proof can decide the "
            "profile"
        ),
        "profile_id": args.profile_id,
        "profile_ledger_sha256": sha256_file(args.profile_ledger),
        "configuration": {
            "max_seconds_per_variant": args.max_seconds,
            "max_candidate_children_per_variant": args.max_candidates,
            "branch_policy": (
                "minimum exact line-completion count, deterministic ties"
            ),
            "margin_feasibility": "Gale-Ryser on the residual complete core",
            "paf_bound": (
                "known energy +/- (sum absolute assigned-neighbor fields + "
                "unassigned-edge weight), plus exact edge-weight congruence"
            ),
            "archived_cpsat_profile73": {
                "branches": ARCHIVED_CPSAT_BRANCHES,
                "seconds": ARCHIVED_CPSAT_SECONDS,
            },
        },
        "results": results,
        "promotion_checks": promotion_checks,
        "event_log": {
            "path": str(args.event_log),
            "sha256": event_log_sha256,
            "bytes": args.event_log.stat().st_size,
            "records": len(paf_search.events),
        },
        "source": {
            "benchmark_sha256": sha256_file(Path(__file__).resolve()),
            "kernel_sha256": sha256_file(
                Path(__file__).with_name("id3_full_profile_arithmetic.py")
            ),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

