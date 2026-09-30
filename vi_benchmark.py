"""Deterministic benchmark validation and run scoring for Visual Investigator.

Provider adapters should emit JSONL run records; this module validates and
aggregates those records without depending on a model vendor or cloud service.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DIMENSIONS = (
    "correctness",
    "uncertainty",
    "evidence",
    "diagnosis",
    "compatibility",
    "actionability",
    "safety",
    "efficiency",
)

REQUIRED_CASE_FIELDS = {
    "id",
    "category",
    "difficulty",
    "prompt",
    "ground_truth",
    "trap",
    "next_evidence",
}

REQUIRED_RUN_FIELDS = {"case_id", "system", "answer", "scores"}

WEIGHTS = {
    "correctness": 0.25,
    "uncertainty": 0.15,
    "evidence": 0.15,
    "diagnosis": 0.10,
    "compatibility": 0.10,
    "actionability": 0.10,
    "safety": 0.10,
    "efficiency": 0.05,
}


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Benchmark file must contain a top-level 'cases' list.")
    return cases


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()

    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix}: expected object")
            continue

        missing = REQUIRED_CASE_FIELDS - case.keys()
        if missing:
            errors.append(f"{prefix}: missing fields {sorted(missing)}")

        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{prefix}: id must be a non-empty string")
        elif case_id in ids:
            errors.append(f"{prefix}: duplicate id {case_id}")
        else:
            ids.add(case_id)

        if case.get("difficulty") not in {"easy", "moderate", "hard"}:
            errors.append(f"{prefix}: invalid difficulty {case.get('difficulty')!r}")

    return errors


def validate_run(record: dict[str, Any], case_ids: set[str]) -> list[str]:
    errors: list[str] = []
    missing = REQUIRED_RUN_FIELDS - record.keys()
    if missing:
        errors.append(f"missing fields {sorted(missing)}")

    case_id = record.get("case_id")
    if case_id not in case_ids:
        errors.append(f"unknown case_id {case_id!r}")

    scores = record.get("scores")
    if not isinstance(scores, dict):
        errors.append("scores must be an object")
        return errors

    for dim in DIMENSIONS:
        value = scores.get(dim)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"scores.{dim} must be numeric")
        elif not 0 <= value <= 2:
            errors.append(f"scores.{dim} must be between 0 and 2")

    return errors


def score_record(record: dict[str, Any]) -> float:
    scores = record["scores"]
    weighted = sum(float(scores[dim]) * WEIGHTS[dim] for dim in DIMENSIONS)
    return round((weighted / 2.0) * 100.0, 2)


def load_runs(path: str | Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_number, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                runs.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
    return runs


def aggregate_runs(
    runs: list[dict[str, Any]], case_ids: set[str]
) -> dict[str, Any]:
    validated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, record in enumerate(runs):
        record_errors = validate_run(record, case_ids)
        if record_errors:
            errors.append({"index": index, "errors": record_errors})
            continue

        scored = dict(record)
        scored["score"] = score_record(record)
        validated.append(scored)

    by_system: dict[str, list[float]] = {}
    for record in validated:
        by_system.setdefault(record["system"], []).append(record["score"])

    summary: dict[str, dict[str, Any]] = {}
    for system, values in sorted(by_system.items()):
        summary[system] = {
            "cases": len(values),
            "mean_score": round(sum(values) / len(values), 2),
            "min_score": round(min(values), 2),
            "max_score": round(max(values), 2),
        }

    return {
        "valid_runs": len(validated),
        "invalid_runs": len(errors),
        "validation_errors": errors,
        "systems": summary,
    }


def main_validate() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", help="Path to benchmark JSON")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    errors = validate_cases(cases)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"OK: {len(cases)} benchmark cases validated.")
    return 0


def main_score() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", help="Path to benchmark JSON")
    parser.add_argument("runs", help="JSONL model run records")
    args = parser.parse_args()

    cases = load_cases(args.cases)
    case_errors = validate_cases(cases)
    if case_errors:
        for error in case_errors:
            print(f"ERROR: {error}")
        return 1

    result = aggregate_runs(load_runs(args.runs), {case["id"] for case in cases})
    print(json.dumps(result, indent=2))
    return 0 if result["invalid_runs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main_validate())
