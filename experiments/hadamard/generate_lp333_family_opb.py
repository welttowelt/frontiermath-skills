#!/usr/bin/env python3
"""Generate the native pseudo-Boolean LP333 family calibration formula."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib
import json
from pathlib import Path
import random
import sys
from typing import Any, Iterable, Sequence


Term = tuple[int, int]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_encoder(source_repo: Path):
    proof_dir = source_repo.resolve() / "lp333" / "proof_phase2"
    encoder_path = proof_dir / "lp333_cnf.py"
    sys.path.insert(0, str(proof_dir))
    module = importlib.import_module("lp333_cnf")
    return module, encoder_path


def load_source_family(
    source_repo: Path, family_id: int
) -> tuple[dict[str, Any], Path, Path]:
    classification_path = (
        source_repo / "lp333" / "results" / "subgroup_classification.json"
    )
    status_path = source_repo / "lp333" / "results" / "master_status.json"
    classification = json.loads(
        classification_path.read_text(encoding="utf-8")
    )
    statuses = json.loads(status_path.read_text(encoding="utf-8"))
    subgroup = next(
        record
        for record in classification["subgroups"]
        if record["id"] == family_id
    )
    status = next(
        record
        for record in statuses["families"]
        if record["id"] == family_id
    )
    if status["status"] != "OPEN":
        raise ValueError(f"family {family_id} is not source-OPEN")
    return (
        {"classification": subgroup, "status": status},
        classification_path,
        status_path,
    )


@dataclass(frozen=True)
class Constraint:
    terms: tuple[Term, ...]
    relation: str
    rhs: int
    label: str

    def holds(self, assignment: Sequence[int]) -> bool:
        lhs = sum(
            coefficient * assignment[variable]
            for coefficient, variable in self.terms
        )
        if self.relation == "=":
            return lhs == self.rhs
        if self.relation == ">=":
            return lhs >= self.rhs
        raise ValueError(f"unsupported relation: {self.relation}")


@dataclass
class NativePBModel:
    length: int
    orbit_model: Any
    za: list[int]
    zb: list[int]
    wa: dict[tuple[int, int], int]
    wb: dict[tuple[int, int], int]
    constraints: list[Constraint]
    names: dict[int, str]

    @property
    def num_variables(self) -> int:
        return len(self.names)

    @property
    def num_equalities(self) -> int:
        return sum(item.relation == "=" for item in self.constraints)

    def canonical_assignment(
        self, za_values: Sequence[int], zb_values: Sequence[int]
    ) -> list[int]:
        assignment = [0] * (self.num_variables + 1)
        for variable, value in zip(self.za, za_values):
            assignment[variable] = int(value)
        for variable, value in zip(self.zb, zb_values):
            assignment[variable] = int(value)
        for pair, variable in self.wa.items():
            assignment[variable] = za_values[pair[0]] ^ za_values[pair[1]]
        for pair, variable in self.wb.items():
            assignment[variable] = zb_values[pair[0]] ^ zb_values[pair[1]]
        return assignment

    def holds(self, assignment: Sequence[int]) -> bool:
        return all(item.holds(assignment) for item in self.constraints)


def build_native_pb_model(orbit_model: Any) -> NativePBModel:
    names: dict[int, str] = {}

    def variable(name: str) -> int:
        identifier = len(names) + 1
        names[identifier] = name
        return identifier

    r = orbit_model.spec["r"]
    za = [variable(f"za_{index}") for index in range(r)]
    zb = [variable(f"zb_{index}") for index in range(r)]
    used_pairs = sorted(orbit_model.wa)
    wa = {
        pair: variable(f"wa_{pair[0]}_{pair[1]}") for pair in used_pairs
    }
    wb = {
        pair: variable(f"wb_{pair[0]}_{pair[1]}") for pair in used_pairs
    }
    constraints: list[Constraint] = [
        Constraint(((-1, za[0]),), ">=", 0, "normalize_a0"),
        Constraint(((-1, zb[0]),), ">=", 0, "normalize_b0"),
    ]

    def add_xor(
        output: int, left: int, right: int, label: str
    ) -> None:
        constraints.extend(
            (
                Constraint(
                    ((1, output), (-1, left), (1, right)),
                    ">=",
                    0,
                    f"{label}_lower_left",
                ),
                Constraint(
                    ((1, output), (1, left), (-1, right)),
                    ">=",
                    0,
                    f"{label}_lower_right",
                ),
                Constraint(
                    ((-1, output), (1, left), (1, right)),
                    ">=",
                    0,
                    f"{label}_upper_sum",
                ),
                Constraint(
                    ((-1, output), (-1, left), (-1, right)),
                    ">=",
                    -2,
                    f"{label}_upper_complement",
                ),
            )
        )

    for pair in used_pairs:
        add_xor(wa[pair], za[pair[0]], za[pair[1]], f"wa_{pair}")
        add_xor(wb[pair], zb[pair[0]], zb[pair[1]], f"wb_{pair}")

    for matrix_index, matrix in enumerate(orbit_model.spec["W"]):
        terms: list[Term] = []
        coefficient_sum = 0
        for pair in used_pairs:
            coefficient = matrix[pair[0]][pair[1]]
            if coefficient:
                terms.append((coefficient, wa[pair]))
                terms.append((coefficient, wb[pair]))
                coefficient_sum += coefficient
        target = (
            orbit_model.spec["const"][matrix_index]
            + coefficient_sum
            + 1
        )
        if target != orbit_model.paf_targets[matrix_index]:
            raise ValueError("native and source PAF targets disagree")
        constraints.append(
            Constraint(
                tuple(terms),
                "=",
                target,
                f"paf_shift_{orbit_model.spec['reps'][matrix_index]}",
            )
        )

    low = (orbit_model.length - 1) // 2
    high = (orbit_model.length + 1) // 2
    for label, variables in (("a", za), ("b", zb)):
        weighted = tuple(zip(orbit_model.spec["sizes"], variables))
        constraints.append(
            Constraint(weighted, ">=", low, f"row_{label}_lower")
        )
        constraints.append(
            Constraint(
                tuple((-coefficient, var) for coefficient, var in weighted),
                ">=",
                -high,
                f"row_{label}_upper",
            )
        )

    return NativePBModel(
        length=orbit_model.length,
        orbit_model=orbit_model,
        za=za,
        zb=zb,
        wa=wa,
        wb=wb,
        constraints=constraints,
        names=names,
    )


def render_constraint(constraint: Constraint) -> str:
    lhs = " ".join(
        f"{coefficient:+d} x{variable}"
        for coefficient, variable in constraint.terms
    )
    return f"{lhs} {constraint.relation} {constraint.rhs};"


def write_opb(model: NativePBModel, path: Path) -> None:
    lines = [
        (
            f"* #variable= {model.num_variables} "
            f"#constraint= {len(model.constraints)} "
            f"#equal= {model.num_equalities} intsize= 64"
        ),
        "* Exact orbit-sign LP predicate; z=1 denotes sign -1.",
    ]
    for constraint in model.constraints:
        lines.append(f"* {constraint.label}")
        lines.append(render_constraint(constraint))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def random_semantic_audit(
    model: NativePBModel, samples: int, seed: int
) -> dict[str, Any]:
    rng = random.Random(seed)
    semantic_true = 0
    native_true = 0
    primitive_checks = 0
    for _ in range(samples):
        za = [0] + [
            rng.randrange(2)
            for _ in range(model.orbit_model.spec["r"] - 1)
        ]
        zb = [0] + [
            rng.randrange(2)
            for _ in range(model.orbit_model.spec["r"] - 1)
        ]
        assignment = model.canonical_assignment(za, zb)
        native = model.holds(assignment)
        semantic = model.orbit_model.semantic_value(za, zb)
        if native != semantic:
            raise ValueError("native OPB and direct semantics disagree")
        semantic_true += int(semantic)
        native_true += int(native)
        primitive_checks += len(model.constraints)
    return {
        "result": "PASS",
        "samples": samples,
        "seed": seed,
        "semantic_true_count": semantic_true,
        "native_opb_true_count": native_true,
        "primitive_constraints_checked": primitive_checks,
    }


def normalize_fixture(sequence: Sequence[int]) -> list[int]:
    multiplier = sequence[0]
    return [multiplier * value for value in sequence]


def lp63_positive_control(
    encoder: Any, fixture_path: Path, output_path: Path
) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    a = normalize_fixture(fixture["a_sequence"])
    b = normalize_fixture(fixture["b_sequence"])
    source_model = encoder.build_singleton_model(63)
    native_model = build_native_pb_model(source_model)
    za = [(1 - value) // 2 for value in a]
    zb = [(1 - value) // 2 for value in b]
    assignment = native_model.canonical_assignment(za, zb)
    direct = source_model.semantic_value(za, zb)
    encoded = native_model.holds(assignment)
    if not direct or not encoded:
        raise ValueError("published LP63 fixture failed native OPB control")
    write_opb(native_model, output_path)
    return {
        "result": "PASS",
        "fixture_path": str(fixture_path),
        "fixture_sha256": sha256_file(fixture_path),
        "opb_path": str(output_path),
        "opb_sha256": sha256_file(output_path),
        "variables": native_model.num_variables,
        "constraints": len(native_model.constraints),
        "normalized_a0": a[0],
        "normalized_b0": b[0],
        "direct_semantics": direct,
        "native_opb_semantics": encoded,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family-id", required=True, type=int)
    parser.add_argument("--source-repo", required=True, type=Path)
    parser.add_argument("--lp63-fixture", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--random-equivalence-samples", type=int, default=1000)
    args = parser.parse_args()
    if args.family_id not in (9, 10):
        raise ValueError("the preregistered native PB route accepts ID9 or ID10")
    if args.random_equivalence_samples < 1000:
        raise ValueError("the native PB gate requires at least 1,000 samples")

    source_family, classification_path, status_path = load_source_family(
        args.source_repo, args.family_id
    )
    encoder, encoder_path = load_encoder(args.source_repo)
    orbit_model, encoder_record = encoder.build_lp333_model(args.family_id)
    if encoder_record["elements"] != source_family["classification"]["elements"]:
        raise ValueError("proof encoder selected a different subgroup")
    native_model = build_native_pb_model(orbit_model)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    opb_path = args.output_dir / f"id{args.family_id}.opb"
    lp63_opb_path = args.output_dir / "lp63-positive.opb"
    metadata_path = args.output_dir / "encoding.json"
    write_opb(native_model, opb_path)
    random_control = random_semantic_audit(
        native_model,
        args.random_equivalence_samples,
        20260726 + args.family_id,
    )
    direct_paf_control = encoder.orbit_spec_audit(
        args.family_id,
        args.random_equivalence_samples,
        30360726 + args.family_id,
    )
    lp63_control = lp63_positive_control(
        encoder, args.lp63_fixture, lp63_opb_path
    )

    metadata = {
        "schema": "frontiermath-hadamard-lp333-family-native-opb-v1",
        "status": "gate-a-pass",
        "family_id": args.family_id,
        "claim_boundary": (
            "This is an exact formulation calibration. Only a complete "
            "VeriPB-accepted proof can certify UNSAT."
        ),
        "subgroup": {
            "order": len(encoder_record["elements"]),
            "elements": encoder_record["elements"],
            "generators": source_family["classification"]["generators"],
            "orbit_count": orbit_model.spec["r"],
            "orbit_signature": source_family["classification"][
                "orbit_signature"
            ],
            "shift_representatives": orbit_model.spec["reps"],
        },
        "native_model": {
            "variables": native_model.num_variables,
            "constraints": len(native_model.constraints),
            "equalities": native_model.num_equalities,
            "primary_orbit_variables": len(native_model.za)
            + len(native_model.zb),
            "xor_variables": len(native_model.wa) + len(native_model.wb),
            "pair_xors_per_sequence": len(native_model.wa),
            "representative_paf_equations": len(orbit_model.paf_targets),
            "row_encoding": "weighted negative-count interval [166,167]",
            "xor_encoding": "four exact linear inequalities",
        },
        "opb": {
            "path": str(opb_path),
            "bytes": opb_path.stat().st_size,
            "sha256": sha256_file(opb_path),
        },
        "controls": {
            "random_direct_semantic_equivalence": random_control,
            "random_direct_paf_equivalence": direct_paf_control,
            "lp63_positive_fixture": lp63_control,
        },
        "inputs": {
            "proof_encoder": str(encoder_path),
            "proof_encoder_sha256": sha256_file(encoder_path),
            "subgroup_classification": str(classification_path),
            "subgroup_classification_sha256": sha256_file(
                classification_path
            ),
            "master_status": str(status_path),
            "master_status_sha256": sha256_file(status_path),
        },
        "generator_sha256": sha256_file(Path(__file__).resolve()),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": metadata["status"],
                "family_id": args.family_id,
                "native_model": metadata["native_model"],
                "opb": metadata["opb"],
                "controls": metadata["controls"],
                "metadata_sha256": sha256_file(metadata_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
