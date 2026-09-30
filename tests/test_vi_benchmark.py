import tempfile
from pathlib import Path

from vi_benchmark import DIMENSIONS, aggregate_runs, score_record, validate_cases


def test_case_bank_validation():
    cases = [
        {
            "id": "VI-TEST",
            "category": "identification",
            "difficulty": "easy",
            "prompt": "What is this?",
            "ground_truth": "A connector",
            "trap": "Guessing the exact part number",
            "next_evidence": "A label close-up",
        }
    ]
    assert validate_cases(cases) == []


def test_score_record_is_bounded():
    record = {
        "case_id": "VI-TEST",
        "system": "baseline",
        "answer": "It is a connector. I would need the label for an exact match.",
        "scores": {dimension: 2 for dimension in DIMENSIONS},
    }
    assert score_record(record) == 100.0

    zero_record = dict(record)
    zero_record["scores"] = {dimension: 0 for dimension in DIMENSIONS}
    assert score_record(zero_record) == 0.0


def test_aggregate_runs():
    runs = [
        {
            "case_id": "VI-TEST",
            "system": "baseline",
            "answer": "connector",
            "scores": {dimension: 1 for dimension in DIMENSIONS},
        },
        {
            "case_id": "VI-TEST",
            "system": "investigator",
            "answer": "connector; need label for exact match",
            "scores": {dimension: 2 for dimension in DIMENSIONS},
        },
    ]
    result = aggregate_runs(runs, {"VI-TEST"})
    assert result["valid_runs"] == 2
    assert result["invalid_runs"] == 0
    assert result["systems"]["baseline"]["mean_score"] == 50.0
    assert result["systems"]["investigator"]["mean_score"] == 100.0
