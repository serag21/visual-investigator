import csv
import json
from pathlib import Path

import pytest

from vi_benchmark import DIMENSIONS
from vi_grade import create_blind_sheet, score_blind_sheet


def write_jsonl(path: Path, system: str, condition: str, answers: dict[str, str]) -> Path:
    with path.open("w", encoding="utf-8") as handle:
        for case_id, answer in answers.items():
            handle.write(json.dumps({
                "case_id": case_id,
                "system": system,
                "provider": "test-provider",
                "model": "test-model",
                "condition": condition,
                "prompt_id": condition,
                "answer": answer,
                "latency_ms": 10,
            }) + "\n")
    return path


def write_cases(path: Path) -> Path:
    path.write_text(json.dumps({
        "benchmark": "test",
        "cases": [
            {
                "id": "VI-A", "category": "identification", "difficulty": "easy",
                "prompt": "What is shown?", "ground_truth": "A connector.",
                "trap": "Do not invent a model.", "next_evidence": "Ask for its label.",
            },
            {
                "id": "VI-B", "category": "compatibility", "difficulty": "hard",
                "prompt": "Which replacement fits?", "ground_truth": "Exact fit needs dimensions.",
                "trap": "Do not assume compatibility.", "next_evidence": "Request dimensions.",
            },
        ],
    }), encoding="utf-8")
    return path


def test_blind_sheet_separates_key_and_shuffles_answers(tmp_path):
    cases = write_cases(tmp_path / "cases.json")
    first = write_jsonl(
        tmp_path / "baseline.jsonl", "test:model:baseline", "baseline",
        {"VI-A": "A connector.", "VI-B": "Need dimensions."},
    )
    second = write_jsonl(
        tmp_path / "investigator.jsonl", "test:model:investigator", "investigator",
        {"VI-A": "A USB-C connector.", "VI-B": "Please measure the part."},
    )
    grades_path = tmp_path / "blind.csv"
    key_path = tmp_path / "private-key.csv"

    count = create_blind_sheet(cases, [first, second], grades_path, key_path, seed=11)

    assert count == 4
    with grades_path.open(encoding="utf-8-sig", newline="") as handle:
        grades = list(csv.DictReader(handle))
    with key_path.open(encoding="utf-8-sig", newline="") as handle:
        key = list(csv.DictReader(handle))

    assert len(grades) == len(key) == 4
    assert "condition" not in grades[0]
    assert all(row["critical_failure"] == "" for row in grades)
    assert {row["condition"] for row in key} == {"baseline", "investigator"}
    assert {row["grade_id"] for row in grades} == {row["grade_id"] for row in key}
    assert all(row["reference_expectation"] for row in grades)


def test_score_sheet_reports_weighted_scores_and_critical_failures(tmp_path):
    cases = write_cases(tmp_path / "cases.json")
    first = write_jsonl(
        tmp_path / "baseline.jsonl", "test:model:baseline", "baseline",
        {"VI-A": "A connector.", "VI-B": "Need dimensions."},
    )
    second = write_jsonl(
        tmp_path / "investigator.jsonl", "test:model:investigator", "investigator",
        {"VI-A": "A USB-C connector.", "VI-B": "Buy this exact part."},
    )
    grades_path = tmp_path / "blind.csv"
    key_path = tmp_path / "private-key.csv"
    create_blind_sheet(cases, [first, second], grades_path, key_path, seed=7)

    with grades_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    for row in rows:
        for dimension in DIMENSIONS:
            row[dimension] = "2" if row["answer"] != "Buy this exact part." else "0"
        row["critical_failure"] = "yes" if row["answer"] == "Buy this exact part." else "no"
        row["critical_failure_reason"] = (
            "Unsupported exact compatibility claim."
            if row["critical_failure"] == "yes" else ""
        )
        row["grader_notes"] = ""
    with grades_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    scored_path = tmp_path / "scored.jsonl"
    summary_path = tmp_path / "summary.json"
    summary = score_blind_sheet(grades_path, key_path, scored_path, summary_path)

    assert summary["scored_answers"] == 4
    by_system = summary["systems"]
    assert by_system["test:model:baseline"]["mean_score"] == 100.0
    assert by_system["test:model:investigator"]["critical_failures"] == 1
    assert by_system["test:model:investigator"]["critical_failure_rate"] == 0.5
    scored = [json.loads(line) for line in scored_path.read_text(encoding="utf-8").splitlines()]
    assert len(scored) == 4
    assert any(record["critical_failure"] for record in scored)
    assert json.loads(summary_path.read_text(encoding="utf-8")) == summary


def test_blind_sheet_rejects_different_case_sets(tmp_path):
    cases = write_cases(tmp_path / "cases.json")
    first = write_jsonl(
        tmp_path / "first.jsonl", "first", "baseline", {"VI-A": "A connector."}
    )
    second = write_jsonl(
        tmp_path / "second.jsonl", "second", "investigator", {"VI-B": "Need dimensions."}
    )
    with pytest.raises(ValueError, match="same cases"):
        create_blind_sheet(
            cases, [first, second], tmp_path / "blind.csv", tmp_path / "key.csv"
        )


def test_scoring_rejects_missing_rating(tmp_path):
    cases = write_cases(tmp_path / "cases.json")
    first = write_jsonl(
        tmp_path / "first.jsonl", "first", "baseline",
        {"VI-A": "A connector.", "VI-B": "Need dimensions."},
    )
    second = write_jsonl(
        tmp_path / "second.jsonl", "second", "investigator",
        {"VI-A": "A connector.", "VI-B": "Need dimensions."},
    )
    grades_path = tmp_path / "blind.csv"
    key_path = tmp_path / "key.csv"
    create_blind_sheet(cases, [first, second], grades_path, key_path)
    with grades_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0])
    rows[0]["critical_failure"] = "no"
    for dimension in DIMENSIONS:
        rows[0][dimension] = "2"
    with grades_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="must be 0, 1, or 2"):
        score_blind_sheet(
            grades_path, key_path, tmp_path / "scored.jsonl", tmp_path / "summary.json"
        )
