#!/usr/bin/env python3
"""Generate the unrestricted LP333 CNF with prescribed pq^2 compression."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
from typing import Any

import generate_lp333_symmetry_cnf as common


LENGTH = 333
FAMILY_ID = 0
COMPRESSED_LENGTH = 37
COMPRESSION_FACTOR = 9
PQ2_SOURCE = (
    "https://www.sciencedirect.com/science/article/pii/S0747717126000544"
)


def legendre_symbol_37(value: int) -> int:
    residue = value % COMPRESSED_LENGTH
    if residue == 0:
        return 0
    symbol = pow(residue, (COMPRESSED_LENGTH - 1) // 2, COMPRESSED_LENGTH)
    if symbol == 1:
        return 1
    if symbol == COMPRESSED_LENGTH - 1:
        return -1
    raise ValueError("Euler criterion returned a non-Legendre value")


COMPRESSED_ROWS = (
    tuple(
        1 if residue == 0 else 3 * legendre_symbol_37(residue)
        for residue in range(COMPRESSED_LENGTH)
    ),
    tuple(
        1 if residue == 0 else -3 * legendre_symbol_37(residue)
        for residue in range(COMPRESSED_LENGTH)
    ),
)
NEGATIVE_TARGETS = tuple(
    tuple((COMPRESSION_FACTOR - value) // 2 for value in row)
    for row in COMPRESSED_ROWS
)


def compressed_seed_control() -> dict[str, Any]:
    paf_rows = []
    for row in COMPRESSED_ROWS:
        paf_rows.append(
            [
                sum(
                    row[index]
                    * row[(index + shift) % COMPRESSED_LENGTH]
                    for index in range(COMPRESSED_LENGTH)
                )
                for shift in range(COMPRESSED_LENGTH)
            ]
        )
    combined = [
        paf_rows[0][shift] + paf_rows[1][shift]
        for shift in range(COMPRESSED_LENGTH)
    ]
    expected_nonzero = -2 * COMPRESSION_FACTOR
    checks = {
        "factorization": LENGTH
        == COMPRESSED_LENGTH * COMPRESSION_FACTOR,
        "compression_factor_is_q_squared": COMPRESSION_FACTOR == 3**2,
        "compressed_row_sums": [
            sum(row) for row in COMPRESSED_ROWS
        ]
        == [1, 1],
        "compressed_energy": combined[0]
        == 2 * LENGTH - 2 * COMPRESSION_FACTOR + 2,
        "all_nonzero_combined_paf": all(
            value == expected_nonzero for value in combined[1:]
        ),
        "negative_counts": all(
            sum(targets) == 166 for targets in NEGATIVE_TARGETS
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"compressed pq2 seed identity failed: {checks}")
    return {
        "result": "PASS",
        "factorization": "333 = 37 * 3^2",
        "compressed_length": COMPRESSED_LENGTH,
        "compression_factor": COMPRESSION_FACTOR,
        "compressed_rows": [list(row) for row in COMPRESSED_ROWS],
        "negative_targets": [
            list(targets) for targets in NEGATIVE_TARGETS
        ],
        "combined_paf": combined,
        "required_nonzero_combined_paf": expected_nonzero,
        "combined_energy": combined[0],
        "required_combined_energy": (
            2 * LENGTH - 2 * COMPRESSION_FACTOR + 2
        ),
        "checks": checks,
    }


def add_pq2_channels(model: Any) -> dict[str, Any]:
    if len(model.za) != LENGTH or len(model.zb) != LENGTH:
        raise ValueError("pq2 channels require the unrestricted singleton model")
    block_start_variable = model.builder.num_vars + 1
    block_start_clause = len(model.builder.clauses) + 1
    channels = []
    for row, (label, primary) in enumerate(
        (("a", model.za), ("b", model.zb))
    ):
        for residue in range(COMPRESSED_LENGTH):
            inputs = list(primary[residue::COMPRESSED_LENGTH])
            if len(inputs) != COMPRESSION_FACTOR:
                raise ValueError("pq2 residue class size changed")
            channels.append(
                common.add_sequential_exact_cardinality(
                    model.builder,
                    inputs,
                    NEGATIVE_TARGETS[row][residue],
                    f"pq2_{label}_residue_{residue}",
                )
            )
    return {
        "enabled": True,
        "kind": (
            "seventy-four redundant uniquely-extended sequential exact-"
            "cardinality counters fixing the prescribed q-squared compression"
        ),
        "compressed_length": COMPRESSED_LENGTH,
        "compression_factor": COMPRESSION_FACTOR,
        "compressed_rows": [list(row) for row in COMPRESSED_ROWS],
        "negative_targets": [
            list(targets) for targets in NEGATIVE_TARGETS
        ],
        "block_start_variable": block_start_variable,
        "block_auxiliary_variables": model.builder.num_vars
        - block_start_variable
        + 1,
        "block_source_clause_start": block_start_clause,
        "block_source_clause_end": len(model.builder.clauses),
        "block_source_clauses": len(model.builder.clauses)
        - block_start_clause
        + 1,
        "channels": channels,
        "paper_to_levers": {
            "source": PQ2_SOURCE,
            "doi": "10.1016/j.jsc.2026.102606",
            "adopted": (
                "prescribed q-squared compression seed specialized at "
                "333 = 37 times 3 squared"
            ),
            "not_adopted": [
                "a proof of the uncompression conjecture",
                "runtime ratios from smaller instances",
                "common multiplier symmetry",
            ],
        },
    }


def pq2_symmetry_actions(
    za: list[int],
    zb: list[int],
    decimations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    actions = []
    for decimation in decimations:
        unit = decimation["unit"]
        permutation = decimation["permutation"]
        swap = legendre_symbol_37(unit) == -1
        if swap:
            mapping = tuple(
                [zb[permutation[index]] for index in range(LENGTH)]
                + [za[permutation[index]] for index in range(LENGTH)]
            )
        else:
            mapping = tuple(
                [za[permutation[index]] for index in range(LENGTH)]
                + [zb[permutation[index]] for index in range(LENGTH)]
            )
        actions.append(
            {
                "unit": unit,
                "swap_sequences": swap,
                "mapping": mapping,
            }
        )
    return actions


def pq2_action_control(
    full_spec: dict[str, Any],
    actions: list[dict[str, Any]],
    samples: int,
    seed: int,
) -> dict[str, Any]:
    if len(actions) != 216:
        raise ValueError("expected one pq2-preserving action per unit")
    expected_a = NEGATIVE_TARGETS[0]
    expected_b = NEGATIVE_TARGETS[1]
    margin_checks = 0
    for action in actions:
        unit = action["unit"]
        if action["swap_sequences"] != (
            legendre_symbol_37(unit) == -1
        ):
            raise ValueError("pq2 action swap parity changed")
        source = expected_b if action["swap_sequences"] else expected_a
        transformed = [
            source[(unit * residue) % COMPRESSED_LENGTH]
            for residue in range(COMPRESSED_LENGTH)
        ]
        if tuple(transformed) != expected_a:
            raise ValueError("pq2 action does not preserve A margins")
        source = expected_a if action["swap_sequences"] else expected_b
        transformed = [
            source[(unit * residue) % COMPRESSED_LENGTH]
            for residue in range(COMPRESSED_LENGTH)
        ]
        if tuple(transformed) != expected_b:
            raise ValueError("pq2 action does not preserve B margins")
        margin_checks += 2 * COMPRESSED_LENGTH

    rng = random.Random(seed)
    direct_paf_equalities = 0
    for _ in range(samples):
        rows = []
        for row in range(2):
            sequence = [1] * LENGTH
            for residue in range(COMPRESSED_LENGTH):
                positions = list(
                    range(residue, LENGTH, COMPRESSED_LENGTH)
                )
                for position in rng.sample(
                    positions, NEGATIVE_TARGETS[row][residue]
                ):
                    sequence[position] = -1
            rows.append(sequence)
        base = [
            [
                sum(
                    sequence[index]
                    * sequence[(index + shift) % LENGTH]
                    for index in range(LENGTH)
                )
                for shift in range(1, LENGTH)
            ]
            for sequence in rows
        ]
        for action in actions:
            unit = action["unit"]
            source_rows = (
                (rows[1], rows[0])
                if action["swap_sequences"]
                else (rows[0], rows[1])
            )
            transformed_rows = [
                [
                    source[(unit * index) % LENGTH]
                    for index in range(LENGTH)
                ]
                for source in source_rows
            ]
            for transformed, expected in zip(
                transformed_rows,
                (
                    base[1] if action["swap_sequences"] else base[0],
                    base[0] if action["swap_sequences"] else base[1],
                ),
            ):
                actual = [
                    sum(
                        transformed[index]
                        * transformed[(index + shift) % LENGTH]
                        for index in range(LENGTH)
                    )
                    for shift in range(1, LENGTH)
                ]
                if sorted(actual) != sorted(expected):
                    raise ValueError("pq2 action changed the PAF multiset")
                direct_paf_equalities += LENGTH - 1
    return {
        "result": "PASS",
        "actions": len(actions),
        "unit_legendre_symbol_modulo_37_histogram": dict(
            sorted(
                Counter(
                    legendre_symbol_37(item["unit"])
                    for item in actions
                ).items()
            )
        ),
        "plain_decimations": sum(
            not item["swap_sequences"] for item in actions
        ),
        "decimation_plus_swaps": sum(
            item["swap_sequences"] for item in actions
        ),
        "exact_margin_checks": margin_checks,
        "random_exact_margin_pairs": samples,
        "direct_paf_multiset_equalities": direct_paf_equalities,
        "seed": seed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--lp63-fixture", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--random-equivalence-samples", type=int, default=100
    )
    args = parser.parse_args()
    if args.random_equivalence_samples <= 0:
        raise ValueError("random-equivalence sample count must be positive")

    source_family, classification_path, status_path = (
        common.load_source_family(args.source_repo, FAMILY_ID)
    )
    encoder, encoder_path = common.load_encoder(args.source_repo)
    subgroup_elements, subgroup = encoder.subgroup_by_id(FAMILY_ID)
    full_spec = encoder.spec_from_orbits(
        LENGTH, encoder.orbits_on_ZL(subgroup_elements, LENGTH)
    )
    if (
        set(subgroup_elements) != {1}
        or full_spec["r"] != LENGTH
        or any(size != 1 for size in full_spec["sizes"])
    ):
        raise ValueError("identity-family orbit model changed")
    model = encoder.build_orbit_model(LENGTH, full_spec)
    if model.direct_pb_obstructions:
        raise ValueError("identity family has a direct PB obstruction")
    random_equivalence = encoder.random_equivalence_audit(
        model,
        args.random_equivalence_samples,
        20260727,
    )
    direct_equivalence = common.direct_random_equivalence(
        model,
        full_spec,
        args.random_equivalence_samples,
        20260728,
    )
    decimations = common.unit_permutations(full_spec)
    group_control = common.validate_decimation_group(
        full_spec, decimations, len(subgroup_elements)
    )
    actions = pq2_symmetry_actions(model.za, model.zb, decimations)
    action_control = pq2_action_control(
        full_spec, actions, samples=2, seed=20260729
    )
    seed_control = compressed_seed_control()
    variables = tuple(model.za + model.zb)
    identity = tuple(variables)
    nonidentity = [
        action for action in actions if action["mapping"] != identity
    ]
    if len(actions) != 216 or len(nonidentity) != 215:
        raise ValueError("pq2 symmetry action order changed")
    breakers = []
    for action_index, action in enumerate(nonidentity):
        record = common.add_lex_leader(
            model.builder,
            variables,
            action["mapping"],
            f"pq2_sym_{action_index:03d}",
        )
        breakers.append(
            {
                "unit": action["unit"],
                "swap_sequences": action["swap_sequences"],
                **record,
            }
        )

    common.sequential_cardinality_truth_table.builder_class = (
        encoder.CNFBuilder
    )
    truth_table = common.sequential_cardinality_truth_table()
    channels = add_pq2_channels(model)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    cnf_path = args.output_dir / "lp333-pq2.cnf"
    metadata_path = args.output_dir / "encoding.json"
    serialization = encoder.write_dimacs(
        model.builder, cnf_path, split_unit_clauses=True
    )
    common.bind_serialized_channel_block(
        model.builder, serialization, channels
    )
    cnf_hash = common.sha256_file(cnf_path)
    if cnf_hash != encoder.dimacs_sha256(
        model.builder, split_unit_clauses=True
    ):
        raise ValueError("written pq2 CNF hash mismatch")
    positive = common.lp63_control(encoder, args.lp63_fixture)
    metadata = {
        "schema": "frontiermath-hadamard-lp333-pq2-cnf-v1",
        "status": "generated",
        "family_id": FAMILY_ID,
        "scope": (
            "unrestricted LP333 slice with only the prescribed length-37 "
            "q-squared compression; no nontrivial multiplier assumption"
        ),
        "claim_boundary": (
            "SAT requires independent direct verification of both length-333 "
            "rows and all 332 nonzero PAF equations. UNSAT requires an "
            "independently accepted complete proof."
        ),
        "subgroup": {
            "elements": subgroup["elements"],
            "order": len(subgroup["elements"]),
            "orbit_count": full_spec["r"],
            "orbits": full_spec["orbits"],
            "orbit_signature": {"1": LENGTH},
        },
        "symmetry": {
            "kind": (
                "all unit decimations, with sequence swap exactly for units "
                "that are quadratic nonresidues modulo 37"
            ),
            "full_group_order": len(actions),
            "nonidentity_lex_leaders": len(nonidentity),
            "encoding": (
                "complete lex-leaders with fresh prefix-equality auxiliaries"
            ),
            "added_auxiliaries": sum(
                record["auxiliaries"] for record in breakers
            ),
            "added_clauses": sum(record["clauses"] for record in breakers),
            "support_min": min(record["support"] for record in breakers),
            "support_max": max(record["support"] for record in breakers),
            "breakers": breakers,
        },
        "primary_variables": {
            "meaning": "z=0 is sign +1; z=1 is sign -1",
            "za": model.za,
            "zb": model.zb,
        },
        "pq2_compression_channels": channels,
        "cnf": {
            "path": str(cnf_path),
            "variables": serialization["num_variables"],
            "clauses": serialization["num_clauses"],
            "bytes": cnf_path.stat().st_size,
            "sha256": cnf_hash,
            "unit_split_count": serialization["unit_split_count"],
        },
        "controls": {
            "random_semantic_cnf_equivalence": random_equivalence,
            "direct_full_length_semantic_equivalence": direct_equivalence,
            "exact_decimation_group": group_control,
            "compressed_seed_identity": seed_control,
            "pq2_symmetry_action": action_control,
            "sequential_cardinality_truth_table": truth_table,
            "lp63_positive_canonicalization": positive,
        },
        "paper_to_levers": channels["paper_to_levers"],
        "inputs": {
            "proof_encoder": str(encoder_path),
            "proof_encoder_sha256": common.sha256_file(encoder_path),
            "lp63_fixture": str(args.lp63_fixture),
            "lp63_fixture_sha256": common.sha256_file(args.lp63_fixture),
            "subgroup_classification": str(classification_path),
            "subgroup_classification_sha256": common.sha256_file(
                classification_path
            ),
            "master_status": str(status_path),
            "master_status_sha256": common.sha256_file(status_path),
            "source_family": source_family,
        },
        "generator_sha256": common.sha256_file(Path(__file__).resolve()),
        "common_generator_sha256": common.sha256_file(
            Path(common.__file__).resolve()
        ),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )
    print(
        json.dumps(
            {
                "status": "generated",
                "family_id": FAMILY_ID,
                "scope": metadata["scope"],
                "symmetry": {
                    key: value
                    for key, value in metadata["symmetry"].items()
                    if key != "breakers"
                },
                "channels": {
                    "auxiliary_variables": channels[
                        "block_auxiliary_variables"
                    ],
                    "source_clauses": channels["block_source_clauses"],
                },
                "cnf": metadata["cnf"],
                "metadata_sha256": common.sha256_file(metadata_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
