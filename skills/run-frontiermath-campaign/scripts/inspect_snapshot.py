#!/usr/bin/env python3
"""Inspect an extracted Epoch FrontierMath public data snapshot.

This utility is local-only. It reads CSV and optional ZIP bytes, performs no
network access, and does not execute candidate code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def inspect(
    dataset_dir: Path,
    zip_path: Path | None = None,
    expect_problems: int | None = None,
    expect_prompts: int | None = None,
) -> dict[str, object]:
    survey_path = dataset_dir / "open_problems_survey.csv"
    prompts_path = dataset_dir / "open_problems_prompts.csv"
    if not survey_path.is_file() or not prompts_path.is_file():
        raise ValueError("dataset must contain both survey and prompts CSV files")

    survey = read_rows(survey_path)
    prompts = read_rows(prompts_path)
    if not survey:
        raise ValueError("survey CSV is empty")
    if not prompts:
        raise ValueError("prompts CSV is empty")
    required_survey_columns = {
        "problem_id",
        "title",
        "field",
        "notability",
        "solved",
    }
    required_prompt_columns = {"problem_id", "prompt_type", "prompt"}
    missing_survey_columns = sorted(required_survey_columns - set(survey[0]))
    missing_prompt_columns = sorted(required_prompt_columns - set(prompts[0]))
    if missing_survey_columns:
        raise ValueError(
            f"survey CSV lacks required columns: {missing_survey_columns}"
        )
    if missing_prompt_columns:
        raise ValueError(
            f"prompts CSV lacks required columns: {missing_prompt_columns}"
        )

    survey_ids = [row["problem_id"] for row in survey]
    prompt_ids = [row["problem_id"] for row in prompts]
    prompt_types: dict[str, list[str]] = defaultdict(list)
    for row in prompts:
        prompt_types[row["problem_id"]].append(row["prompt_type"])

    duplicate_survey_ids = sorted(
        problem_id for problem_id, count in Counter(survey_ids).items() if count > 1
    )
    duplicate_prompt_keys = sorted(
        list(key)
        for key, count in Counter(
            (row["problem_id"], row["prompt_type"]) for row in prompts
        ).items()
        if count > 1
    )
    missing_survey = sorted(set(prompt_ids) - set(survey_ids))
    missing_prompts = sorted(set(survey_ids) - set(prompt_ids))
    redacted = sorted(
        {
            row["problem_id"]
            for row in prompts
            if "___" in row.get("prompt", "")
        }
    )
    solved = sorted(
        row["problem_id"]
        for row in survey
        if row.get("solved", "").strip().lower() == "true"
    )

    errors: list[str] = []
    if duplicate_survey_ids:
        errors.append(f"duplicate survey IDs: {duplicate_survey_ids}")
    if duplicate_prompt_keys:
        errors.append(f"duplicate prompt keys: {duplicate_prompt_keys}")
    if missing_survey:
        errors.append(f"prompt IDs absent from survey: {missing_survey}")
    if missing_prompts:
        errors.append(f"survey IDs without prompts: {missing_prompts}")
    if expect_problems is not None and len(survey) != expect_problems:
        errors.append(f"expected {expect_problems} problems, found {len(survey)}")
    if expect_prompts is not None and len(prompts) != expect_prompts:
        errors.append(f"expected {expect_prompts} prompts, found {len(prompts)}")

    return {
        "status": "snapshot-valid" if not errors else "snapshot-invalid",
        "dataset_dir": str(dataset_dir.resolve()),
        "zip_sha256": sha256(zip_path) if zip_path else None,
        "problem_count": len(survey),
        "prompt_count": len(prompts),
        "unsolved_count": len(survey) - len(solved),
        "solved_problem_ids": solved,
        "redacted_problem_ids": redacted,
        "problem_prompt_types": dict(sorted(prompt_types.items())),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_dir", type=Path)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--expect-problems", type=int)
    parser.add_argument("--expect-prompts", type=int)
    args = parser.parse_args()
    try:
        result = inspect(
            args.dataset_dir,
            args.zip_path,
            args.expect_problems,
            args.expect_prompts,
        )
    except (OSError, ValueError, csv.Error) as exc:
        result = {"status": "input-error", "error": str(exc)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "snapshot-valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
