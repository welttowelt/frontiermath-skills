#!/usr/bin/env python3
"""Build Obsidian problem notes from a pinned FrontierMath CSV snapshot.

The generated notes quote the CC BY public prompts and add an explicitly local
triage layer. The utility has no network or code-execution capability.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path


STRATEGY = {
    "apery-irrationality": {
        "priority": "C-redacted",
        "checker": "recurrence integrality, denominator, and asymptotic-bound checker",
        "tools": "project-local SymPy only; rigorous asymptotic certification absent",
        "method": "recurrence mining, creative telescoping, and irrationality-measure analysis",
        "next": "reproduce the zeta(3) warmup and record exactly which checks remain analytic",
        "risk": "the public full target is redacted",
    },
    "arithmetic-kakeya": {
        "priority": "A1",
        "checker": "exact parser for the structured finite certificate and score",
        "tools": "standard-library Python can check a candidate; scalable search stack absent",
        "method": "finite geometry, integer programming, SAT, and structured local search",
        "next": "encode and independently check the warmup certificate grammar",
        "risk": "long public prompt; a faithful translation audit is essential",
    },
    "degree-sensitivity-boolean": {
        "priority": "A1",
        "checker": "safe expression parser plus exact Booleanity, degree, and sensitivity checks",
        "tools": "SymPy is available; scalable BDD or SAT tooling is absent",
        "method": "gadget composition, tensoring, symmetry reduction, and bounded synthesis",
        "next": "reproduce a known exponent above 1.63 and build adversarial parser fixtures",
        "risk": "naive enumeration cannot certify up to 100 variables",
    },
    "hadamard": {
        "priority": "A0",
        "checker": "exact bitset orthogonality checker",
        "tools": "ready with standard-library Python",
        "method": "structured constructions, equivalence-class search, switching, and SAT",
        "next": "reproduce order 428, then inventory order-668 construction families",
        "risk": "verification is easy while discovery remains combinatorially hard",
    },
    "inverse-galois": {
        "priority": "B-tool-gated",
        "checker": "irreducibility, discriminant, ramification, and Galois-group computation",
        "tools": "Magma, GAP, SageMath, and PARI/GP are absent",
        "method": "resolvents, specialization, subgroup exclusion, and database-guided search",
        "next": "freeze the exact M23 contract and design cross-CAS verification",
        "risk": "the public output is short but the decisive group computation is specialist",
    },
    "klt-del-pezzo-surface": {
        "priority": "B-tool-gated",
        "checker": "Macaulay2 verification of singularities and surface conditions",
        "tools": "Macaulay2 is absent",
        "method": "finite-field algebraic geometry, quotient constructions, and parameter search",
        "next": "turn the two published methods into explicit obligation checklists",
        "risk": "characteristic-three and singularity conventions can drift across systems",
    },
    "large-steiner-systems": {
        "priority": "A1",
        "checker": "exact block-size, uniqueness, and r-subset coverage checker",
        "tools": "small checks are ready; full exact-cover and isomorph tooling is absent",
        "method": "Kramer-Mesner reduction, exact cover, SAT, group actions, and trades",
        "next": "validate the sample and choose the smallest admissible r greater than five",
        "risk": "certificate volume and coverage enumeration can dominate runtime",
    },
    "prime-factorization": {
        "priority": "C-moonshot",
        "checker": "product, primality, balance, runtime, and hardware-controlled benchmark",
        "tools": "specialist factorization stack is absent",
        "method": "algorithmic number theory and implementation-level performance research",
        "next": "write a reproducible benchmark contract before comparing algorithms",
        "risk": "runtime claims are hardware-sensitive and the tier is breakthrough",
    },
    "q2-absolute-galois": {
        "priority": "B-specialist",
        "checker": "profinite-presentation relation and invariant checks",
        "tools": "specialist local-field and pro-p tooling is absent",
        "method": "local Galois theory, generator normalization, and presentation equivalence",
        "next": "reproduce the odd-prime warmup and enumerate convention-sensitive identities",
        "risk": "presentation equivalence can be mistaken for literal syntactic agreement",
    },
    "ramsey-book-graphs": {
        "priority": "A0-first-attack",
        "checker": "exact adjacency parser and graph/complement book-number checker",
        "tools": "ready with standard-library Python",
        "method": "circulant and Cayley graphs, strongly regular templates, SAT, and local switching",
        "next": "reproduce the n=25 warmup and search symbolic families before raw adjacency strings",
        "risk": "an isolated witness is insufficient; the full prompt requires an algorithm",
    },
    "ramsey-hypergraphs": {
        "priority": "regression",
        "checker": "reproduce the published solved-case acceptance contract",
        "tools": "problem-specific implementation still needed",
        "method": "use as a full campaign rehearsal and regression benchmark",
        "next": "reconstruct the solved lane without using hidden answer leakage",
        "risk": "benchmark contamination if the known solution enters evaluation context",
    },
    "small-diophantine": {
        "priority": "C-redacted",
        "checker": "exact substitution, distinctness, and magnitude checks",
        "tools": "basic exact arithmetic is ready; the target equation is absent",
        "method": "elliptic curves, descent, recurrence families, and computational Diophantine search",
        "next": "study the warmup only and preserve the hidden-target boundary",
        "risk": "the public full equation is redacted",
    },
    "stretched-lr-coefficients": {
        "priority": "A2-tool-gated",
        "checker": "exact Littlewood-Richardson values followed by polynomial interpolation",
        "tools": "SageMath, lrcalc, and polyhedral tooling are absent",
        "method": "bounded partition census, hive polytopes, Ehrhart computation, and symmetry",
        "next": "specify two independent coefficient engines before launching the bounded search",
        "risk": "a single buggy coefficient implementation could manufacture the negative term",
    },
    "symplectic-ball-packing": {
        "priority": "B-tool-gated",
        "checker": "differentiable symplectic, injectivity, containment, and volume checks",
        "tools": "PyTorch and validated ODE tooling are absent",
        "method": "Hamiltonian flows, neural parameterization, interval stress tests, and optimization",
        "next": "separate numerical acceptance predicates from genuine embedding guarantees",
        "risk": "finite sampling can miss collisions and boundary violations",
    },
    "unknotting-number": {
        "priority": "B-breakthrough",
        "checker": "diagram parser plus sound unknotting-number-one decision procedure",
        "tools": "Regina and SnapPy are absent",
        "method": "normal surfaces, branched covers, Floer obstructions, and certified search",
        "next": "reproduce unknot recognition with explicit diagram conventions",
        "risk": "a heuristic witness finder is not an exact decision algorithm",
    },
}

DOMAIN_LINKS = {
    "Number Theory": "Number Theory",
    "Combinatorics": "Discrete Mathematics and Combinatorics",
    "Algebraic Geometry": "Geometry and Topology",
    "Topology / Geometry": "Geometry and Topology",
}


def rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def exact_prompt_block(label: str, prompt: str) -> str:
    return (
        f"<details>\n<summary>Exact public {label} prompt</summary>\n\n"
        f"{prompt.strip()}\n\n</details>"
    )


def validate_iso_date(value: str, label: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date: {exc}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must use canonical YYYY-MM-DD form")
    return value


def validate_inputs(
    survey_rows: list[dict[str, str]],
    prompt_rows: list[dict[str, str]],
) -> None:
    if not survey_rows:
        raise ValueError("survey CSV is empty")
    if not prompt_rows:
        raise ValueError("prompts CSV is empty")
    required_survey = {
        "problem_id",
        "title",
        "field",
        "notability",
        "time_horizon",
        "solvability",
        "solved",
        "short_description",
    }
    required_prompt = {"problem_id", "prompt_type", "prompt"}
    for index, row in enumerate(survey_rows, start=2):
        missing = sorted(key for key in required_survey if not row.get(key))
        if missing:
            raise ValueError(f"survey row {index} lacks required values: {missing}")
    for index, row in enumerate(prompt_rows, start=2):
        missing = sorted(key for key in required_prompt if not row.get(key))
        if missing:
            raise ValueError(f"prompt row {index} lacks required values: {missing}")

    survey_ids = [row["problem_id"] for row in survey_rows]
    duplicate_survey_ids = sorted(
        problem_id
        for problem_id in set(survey_ids)
        if survey_ids.count(problem_id) > 1
    )
    if duplicate_survey_ids:
        raise ValueError(f"duplicate survey problem IDs: {duplicate_survey_ids}")

    prompt_keys = [
        (row["problem_id"], row["prompt_type"])
        for row in prompt_rows
    ]
    duplicate_prompt_keys = sorted(
        key for key in set(prompt_keys) if prompt_keys.count(key) > 1
    )
    if duplicate_prompt_keys:
        raise ValueError(f"duplicate prompt keys: {duplicate_prompt_keys}")

    survey_id_set = set(survey_ids)
    prompt_id_set = {row["problem_id"] for row in prompt_rows}
    missing_prompts = sorted(survey_id_set - prompt_id_set)
    unknown_prompts = sorted(prompt_id_set - survey_id_set)
    if missing_prompts:
        raise ValueError(f"survey problems without prompts: {missing_prompts}")
    if unknown_prompts:
        raise ValueError(f"prompt problems absent from survey: {unknown_prompts}")

    unsafe_titles = sorted(
        row["title"]
        for row in survey_rows
        if row["title"] in {".", ".."}
        or "/" in row["title"]
        or "\\" in row["title"]
    )
    if unsafe_titles:
        raise ValueError(f"unsafe note titles: {unsafe_titles}")


def build_note(
    survey: dict[str, str],
    prompts: list[dict[str, str]],
    source_note: str,
    source_sha256: str,
    snapshot_date: str,
    retrieved_date: str,
) -> str:
    problem_id = survey["problem_id"]
    strategy = STRATEGY[problem_id]
    solved = survey["solved"].strip().lower() == "true"
    redacted = any("___" in row["prompt"] for row in prompts)
    status = "solved-regression" if solved else "open"
    domain_link = DOMAIN_LINKS.get(survey["field"], "Mathematical Domain Atlas")
    prompt_sections = "\n\n".join(
        exact_prompt_block(row["prompt_type"].replace("_", " "), row["prompt"])
        for row in prompts
    )
    completeness = (
        "redacted-public-target" if redacted else "complete-public-text"
    )
    yaml_title = json.dumps(survey["title"], ensure_ascii=False)
    return f"""---
title: {yaml_title}
problem_id: {problem_id}
type: frontiermath-problem
status: {status}
prompt_completeness: {completeness}
source_sha256: {source_sha256}
source_snapshot_date: {snapshot_date}
source_retrieved_date: {retrieved_date}
local_priority: {strategy["priority"]}
epoch_field: {json.dumps(survey["field"], ensure_ascii=False)}
epoch_notability: {json.dumps(survey["notability"], ensure_ascii=False)}
created: {retrieved_date}
updated: {retrieved_date}
tags: [mathematics, frontiermath, open-problem]
---

# {survey["title"]}

> [!abstract] Public benchmark contract
> **Epoch ID:** `{problem_id}`
> **Field:** {survey["field"]}
> **Epoch tier:** {survey["notability"]}
> **Epoch survey horizon:** {survey["time_horizon"]}
> **Epoch survey solvability:** {survey["solvability"]}
> **Public prompt:** {completeness}
> **Pinned source SHA-256:** `{source_sha256}`
> These survey fields describe Epoch's published snapshot, not our forecast.

## Research target

{survey["short_description"]}

## Local triage

| Axis | Current decision |
|---|---|
| Portfolio | `{strategy["priority"]}` |
| Independent check | {strategy["checker"]} |
| Tool state | {strategy["tools"]} |
| Candidate families | {strategy["method"]} |
| First experiment | {strategy["next"]} |
| Principal risk | {strategy["risk"]} |

## Lane gate

- [x] Exact prompt copied from the pinned source snapshot
- [ ] Warmup reproduced, or absence recorded
- [ ] Shadow verifier has positive and adversarial fixtures
- [ ] Three structurally distinct directions logged
- [ ] Prior art checked at source level
- [ ] Candidate packet independently audited

`shadow-verifier-pass` is not an Epoch verifier result.

## Exact public prompts

{prompt_sections}

## Connections

- [[FrontierMath Campaign]]
- [[FrontierMath Problem Atlas]]
- [[FrontierMath Priority Portfolio]]
- [[FrontierMath Capability Matrix]]
- [[FrontierMath Verification Architecture]]
- [[{source_note}]]
- [[{domain_link}]]

## Source

Epoch AI, *FrontierMath Open Problems* public dataset, CC BY, snapshot mirrored
{retrieved_date} from <https://epoch.ai/data/open_problems_data.zip>. Dataset
snapshot date: {snapshot_date}.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--survey", required=True, type=Path)
    parser.add_argument("--prompts", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--snapshot-date", required=True)
    parser.add_argument("--retrieved-date", required=True)
    parser.add_argument("--source-note")
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{64}", args.source_sha256):
        raise SystemExit("--source-sha256 must be a lowercase SHA-256 digest")
    try:
        snapshot_date = validate_iso_date(args.snapshot_date, "--snapshot-date")
        retrieved_date = validate_iso_date(
            args.retrieved_date, "--retrieved-date"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    source_note = (
        args.source_note
        or f"FrontierMath Source Snapshot - {snapshot_date}"
    )

    survey_rows = rows(args.survey)
    prompt_rows = rows(args.prompts)
    try:
        validate_inputs(survey_rows, prompt_rows)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    by_problem: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in prompt_rows:
        by_problem[row["problem_id"]].append(row)

    unknown = sorted({row["problem_id"] for row in survey_rows} - STRATEGY.keys())
    if unknown:
        raise SystemExit(f"missing local strategy entries: {unknown}")

    targets = [args.output_dir / f"{survey['title']}.md" for survey in survey_rows]
    if len(set(targets)) != len(targets):
        raise SystemExit("duplicate output note paths")
    collisions = [path for path in targets if path.exists()]
    if collisions and not args.force:
        rendered = ", ".join(str(path) for path in collisions)
        raise SystemExit(
            f"refusing to overwrite existing notes: {rendered}; pass --force"
        )

    written: list[str] = []
    for survey in survey_rows:
        path = args.output_dir / f"{survey['title']}.md"
        atomic_write(
            path,
            build_note(
                survey,
                by_problem[survey["problem_id"]],
                source_note,
                args.source_sha256,
                snapshot_date,
                retrieved_date,
            ),
        )
        written.append(str(path))

    print(
        json.dumps(
            {"status": "notes-built", "count": len(written), "files": written},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
