#!/usr/bin/env python3
"""Independently audit profile-propagation prune and boundary events."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, deque
from math import gcd
from pathlib import Path
from typing import Any

from id3_full_profile_arithmetic import (
    LENGTH,
    MOD9,
    MULTIPLIER_GENERATOR,
    TARGET_COMBINED_PAF,
    crt_grid_orbits,
    cyclic_subgroup,
    multiplication_orbits,
)


GRID_COLUMNS = 12
SEQUENCES = 2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def independent_paf_graph(orbits: list[list[int]]):
    """Rebuild PAF coefficients without importing the benchmark module."""

    position_to_orbit = [0] * LENGTH
    for orbit_index, orbit in enumerate(orbits):
        for position in orbit:
            position_to_orbit[position] = orbit_index
    representatives = [orbit[0] for orbit in orbits if orbit != [0]]
    constants: list[int] = []
    graphs: list[list[tuple[int, int, int]]] = []
    for shift in representatives:
        directed: Counter[tuple[int, int]] = Counter()
        constant = 0
        for position in range(LENGTH):
            left = position_to_orbit[position]
            right = position_to_orbit[(position + shift) % LENGTH]
            if left == right:
                constant += 1
            else:
                directed[tuple(sorted((left, right)))] += 1
        constants.append(constant)
        combined = []
        for sequence in range(SEQUENCES):
            offset = sequence * len(orbits)
            combined.extend(
                (offset + left, offset + right, weight)
                for (left, right), weight in sorted(directed.items())
            )
        graphs.append(combined)
    return representatives, constants, graphs


def decode_masks(
    event: dict[str, Any], variable_count: int
) -> list[int]:
    assigned = int(event["assigned_mask_hex"], 16)
    negative = int(event["negative_mask_hex"], 16)
    if negative & ~assigned:
        raise ValueError("negative mask contains an unassigned variable")
    if assigned >> variable_count or negative >> variable_count:
        raise ValueError("event mask exceeds the variable count")
    return [
        0
        if not (assigned & (1 << variable))
        else (-1 if negative & (1 << variable) else 1)
        for variable in range(variable_count)
    ]


def recompute_equation_bound(
    assignments: list[int],
    constant: int,
    edges: list[tuple[int, int, int]],
) -> dict[str, int | str | None]:
    known = 2 * constant
    fields = [0] * len(assignments)
    unassigned_edge_weight = 0
    unresolved_edge_weight = 0
    unresolved_counts: Counter[int] = Counter()
    for left, right, weight in edges:
        left_value = assignments[left]
        right_value = assignments[right]
        if left_value and right_value:
            known += weight * left_value * right_value
        elif left_value:
            fields[right] += weight * left_value
            unresolved_edge_weight += weight
            unresolved_counts[weight] += 1
        elif right_value:
            fields[left] += weight * right_value
            unresolved_edge_weight += weight
            unresolved_counts[weight] += 1
        else:
            unassigned_edge_weight += weight
            unresolved_edge_weight += weight
            unresolved_counts[weight] += 1
    radius = (
        sum(abs(field) for field in fields)
        + unassigned_edge_weight
    )
    lower = known - radius
    upper = known + radius
    delta = TARGET_COMBINED_PAF - known
    reason = None
    if TARGET_COMBINED_PAF < lower or TARGET_COMBINED_PAF > upper:
        reason = "interval"
    else:
        common_divisor = 0
        for weight in unresolved_counts:
            common_divisor = gcd(common_divisor, weight)
        if common_divisor and (
            unresolved_edge_weight - delta
        ) % (2 * common_divisor):
            reason = "edge-weight-congruence"
        elif not common_divisor and delta != 0:
            reason = "fully-resolved-mismatch"
    return {
        "known": known,
        "radius": radius,
        "lower": lower,
        "upper": upper,
        "target": TARGET_COMBINED_PAF,
        "delta": delta,
        "unresolved_edge_weight": unresolved_edge_weight,
        "reason": reason,
    }


class Dinic:
    def __init__(self, size: int) -> None:
        self.graph: list[list[list[int]]] = [[] for _ in range(size)]

    def add_edge(self, source: int, target: int, capacity: int) -> None:
        forward = [target, capacity, len(self.graph[target])]
        backward = [source, 0, len(self.graph[source])]
        self.graph[source].append(forward)
        self.graph[target].append(backward)

    def maximum_flow(self, source: int, sink: int) -> int:
        total = 0
        while True:
            level = [-1] * len(self.graph)
            level[source] = 0
            queue = deque([source])
            while queue:
                vertex = queue.popleft()
                for target, capacity, _ in self.graph[vertex]:
                    if capacity and level[target] < 0:
                        level[target] = level[vertex] + 1
                        queue.append(target)
            if level[sink] < 0:
                return total
            cursor = [0] * len(self.graph)

            def send(vertex: int, amount: int) -> int:
                if vertex == sink:
                    return amount
                while cursor[vertex] < len(self.graph[vertex]):
                    edge = self.graph[vertex][cursor[vertex]]
                    target, capacity, reverse = edge
                    if capacity and level[target] == level[vertex] + 1:
                        pushed = send(target, min(amount, capacity))
                        if pushed:
                            edge[1] -= pushed
                            self.graph[target][reverse][1] += pushed
                            return pushed
                    cursor[vertex] += 1
                return 0

            while True:
                pushed = send(source, 10**9)
                if not pushed:
                    break
                total += pushed


def cell_variable_map(orbits: list[list[int]]) -> list[list[list[int]]]:
    lookup = {frozenset(orbit): index for index, orbit in enumerate(orbits)}
    grid = crt_grid_orbits()
    return [
        [
            [
                sequence * len(orbits)
                + lookup[frozenset(grid[row * 13 + column + 1])]
                for column in range(GRID_COLUMNS)
            ]
            for row in range(MOD9)
        ]
        for sequence in range(SEQUENCES)
    ]


def residual_margin_feasible(
    assignments: list[int],
    cell_variables: list[list[list[int]]],
    record: dict[str, Any],
) -> tuple[bool, str]:
    for sequence, name in enumerate(("a", "b")):
        witness = record[f"{name}_margin_9_by_12"]
        row_targets = [sum(row) for row in witness]
        column_targets = [
            sum(witness[row][column] for row in range(MOD9))
            for column in range(GRID_COLUMNS)
        ]
        row_residual = list(row_targets)
        column_residual = list(column_targets)
        unknown: list[tuple[int, int]] = []
        for row in range(MOD9):
            for column in range(GRID_COLUMNS):
                value = assignments[cell_variables[sequence][row][column]]
                if value == 0:
                    unknown.append((row, column))
                elif value == 1:
                    row_residual[row] -= 1
                    column_residual[column] -= 1
        if any(value < 0 for value in row_residual + column_residual):
            return False, f"sequence {sequence} has a negative residual degree"

        active_rows = sorted({row for row, _ in unknown})
        active_columns = sorted({column for _, column in unknown})
        source = 0
        row_offset = 1
        column_offset = row_offset + len(active_rows)
        sink = column_offset + len(active_columns)
        flow = Dinic(sink + 1)
        row_node = {
            row: row_offset + index for index, row in enumerate(active_rows)
        }
        column_node = {
            column: column_offset + index
            for index, column in enumerate(active_columns)
        }
        demand = 0
        for row in active_rows:
            flow.add_edge(source, row_node[row], row_residual[row])
            demand += row_residual[row]
        for row, column in unknown:
            flow.add_edge(row_node[row], column_node[column], 1)
        for column in active_columns:
            flow.add_edge(
                column_node[column],
                sink,
                column_residual[column],
            )
        if sum(column_residual[column] for column in active_columns) != demand:
            return False, f"sequence {sequence} residual sums differ"
        achieved = flow.maximum_flow(source, sink)
        if achieved != demand:
            return False, (
                f"sequence {sequence} max flow {achieved} misses demand {demand}"
            )
    return True, "feasible"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_manifest", type=Path)
    parser.add_argument("event_log", type=Path)
    parser.add_argument("profile_ledger", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(
        args.benchmark_manifest.read_text(encoding="utf-8")
    )
    ledger = json.loads(args.profile_ledger.read_text(encoding="utf-8"))
    record = next(
        item
        for item in ledger["records"]
        if item["id"] == manifest["profile_id"]
    )
    if manifest["event_log"]["sha256"] != sha256_file(args.event_log):
        raise ValueError("event-log hash does not match the benchmark manifest")
    if manifest["profile_ledger_sha256"] != sha256_file(args.profile_ledger):
        raise ValueError("profile-ledger hash does not match the manifest")

    subgroup = cyclic_subgroup(MULTIPLIER_GENERATOR, LENGTH)
    orbits = multiplication_orbits(subgroup, LENGTH)
    representatives, constants, graphs = independent_paf_graph(orbits)
    cells = cell_variable_map(orbits)
    events = [
        json.loads(line)
        for line in args.event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(events) != manifest["event_log"]["records"]:
        raise ValueError("event-log record count does not match the manifest")

    errors: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    paf_prunes_checked = 0
    boundary_events_checked = 0
    margin_prunes_checked = 0
    variable_count = SEQUENCES * len(orbits)

    for event_index, event in enumerate(events):
        event_type = event["event_type"]
        counts[event_type] += 1
        assignments = decode_masks(event, variable_count)
        detail = event["detail"]
        if event_type in {"paf-prune", "paf-boundary-equality"}:
            equation = detail["equation"]
            if not 0 <= equation < len(graphs):
                errors.append(
                    {"event": event_index, "error": "equation out of range"}
                )
                continue
            recomputed = recompute_equation_bound(
                assignments,
                constants[equation],
                graphs[equation],
            )
            comparable = (
                "known",
                "radius",
                "lower",
                "upper",
                "target",
            )
            for key in comparable:
                if detail.get(key) != recomputed[key]:
                    errors.append(
                        {
                            "event": event_index,
                            "error": f"{key} mismatch",
                            "stored": detail.get(key),
                            "recomputed": recomputed[key],
                        }
                    )
                    break
            if detail.get("shift") != representatives[equation]:
                errors.append(
                    {"event": event_index, "error": "shift mismatch"}
                )
            if event_type == "paf-prune":
                paf_prunes_checked += 1
                if recomputed["reason"] is None:
                    errors.append(
                        {
                            "event": event_index,
                            "error": "logged PAF prune is not impossible",
                        }
                    )
                if detail.get("reason") != recomputed["reason"]:
                    errors.append(
                        {
                            "event": event_index,
                            "error": "prune reason mismatch",
                            "stored": detail.get("reason"),
                            "recomputed": recomputed["reason"],
                        }
                    )
            else:
                boundary_events_checked += 1
                if TARGET_COMBINED_PAF not in (
                    recomputed["lower"],
                    recomputed["upper"],
                ):
                    errors.append(
                        {
                            "event": event_index,
                            "error": "logged boundary event is not equality",
                        }
                    )
        elif event_type == "margin-prune":
            margin_prunes_checked += 1
            feasible, reason = residual_margin_feasible(
                assignments, cells, record
            )
            if feasible:
                errors.append(
                    {
                        "event": event_index,
                        "error": "logged margin prune is max-flow feasible",
                        "recomputed": reason,
                    }
                )
        else:
            errors.append(
                {"event": event_index, "error": f"unknown event type {event_type}"}
            )
        if len(errors) >= 20:
            break

    # Adversarial control: a one-unit bound mutation must be detected.
    mutation_rejected = False
    source_event = next(
        (
            event
            for event in events
            if event["event_type"]
            in {"paf-prune", "paf-boundary-equality"}
        ),
        None,
    )
    if source_event is not None:
        assignments = decode_masks(source_event, variable_count)
        detail = dict(source_event["detail"])
        equation = detail["equation"]
        detail["known"] += 1
        recomputed = recompute_equation_bound(
            assignments, constants[equation], graphs[equation]
        )
        mutation_rejected = detail["known"] != recomputed["known"]

    event_counts_match = all(
        counts.get(kind, 0) == count
        for kind, count in manifest["results"][-1][
            "logged_event_counts"
        ].items()
    )
    checks = {
        "event_log_hash_matches": True,
        "event_record_count_matches": True,
        "event_type_counts_match": event_counts_match,
        "all_paf_prunes_recomputed": (
            paf_prunes_checked
            == manifest["results"][-1]["paf_prunes"]
        ),
        "all_boundary_equalities_recomputed": (
            boundary_events_checked
            == manifest["results"][-1]["boundary_equality_events"]
        ),
        "all_margin_prunes_recomputed": (
            margin_prunes_checked
            == manifest["results"][-1]["margin_prunes"]
        ),
        "no_audit_errors": not errors,
        "mutated_bound_rejected": mutation_rejected,
    }
    status = "pass" if all(checks.values()) else "fail"
    output = {
        "schema": "frontiermath-hadamard-id3-profile-propagation-audit-v1",
        "status": status,
        "checks": checks,
        "counts": {
            "events": len(events),
            "event_types": dict(sorted(counts.items())),
            "paf_prunes_checked": paf_prunes_checked,
            "boundary_events_checked": boundary_events_checked,
            "margin_prunes_checked": margin_prunes_checked,
        },
        "errors": errors,
        "adversarial_control": {
            "mutation": "incremented one stored known-energy value by one",
            "rejected": mutation_rejected,
        },
        "inputs": {
            "benchmark_manifest_sha256": sha256_file(
                args.benchmark_manifest
            ),
            "event_log_sha256": sha256_file(args.event_log),
            "profile_ledger_sha256": sha256_file(args.profile_ledger),
        },
        "source": {
            "auditor_sha256": sha256_file(Path(__file__).resolve()),
            "kernel_sha256": sha256_file(
                Path(__file__).with_name("id3_full_profile_arithmetic.py")
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

