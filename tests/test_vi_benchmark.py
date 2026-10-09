from io import BytesIO
from unittest.mock import MagicMock, patch
import urllib.error

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



def test_request_json_retries_503_then_succeeds():
    from run_benchmark import request_json

    url = "https://example.invalid/generate"
    unavailable = urllib.error.HTTPError(
        url, 503, "Service Unavailable", {}, BytesIO(b'{"status":"UNAVAILABLE"}')
    )
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b'{"ok":true}'

    with (
        patch("run_benchmark.urllib.request.urlopen", side_effect=[unavailable, response]) as urlopen,
        patch("run_benchmark.time.sleep") as sleep,
        patch("run_benchmark.random.uniform", return_value=0.1),
    ):
        result = request_json(url, {"test": True}, {})

    assert result == {"ok": True}
    assert urlopen.call_count == 2
    sleep.assert_called_once_with(1.1)


def test_request_json_does_not_retry_non_transient_http_errors():
    from run_benchmark import request_json

    url = "https://example.invalid/generate"
    bad_request = urllib.error.HTTPError(
        url, 400, "Bad Request", {}, BytesIO(b'{"error":"bad request"}')
    )

    with patch("run_benchmark.urllib.request.urlopen", side_effect=bad_request) as urlopen:
        try:
            request_json(url, {"test": True}, {})
        except RuntimeError as exc:
            assert "HTTP 400" in str(exc)
        else:
            raise AssertionError("Expected HTTP 400 to fail immediately")

    assert urlopen.call_count == 1


def test_fetch_bytes_retries_429_and_caches(tmp_path):
    import run_benchmark

    url = "https://example.invalid/reference-image"
    rate_limited = urllib.error.HTTPError(
        url, 429, "Too Many Requests", {"Retry-After": "0"}, BytesIO(b"rate limited")
    )
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"fake-image-bytes"
    response.headers = {"Content-Type": "image/jpeg"}

    with (
        patch.object(run_benchmark, "IMAGE_CACHE_DIR", tmp_path),
        patch("run_benchmark.urllib.request.urlopen", side_effect=[rate_limited, response]) as urlopen,
        patch("run_benchmark.time.sleep") as sleep,
    ):
        first = run_benchmark.fetch_bytes(url)
        second = run_benchmark.fetch_bytes(url)

    assert first == (b"fake-image-bytes", "image/jpeg")
    assert second == first
    assert urlopen.call_count == 2  # 429 then successful fetch; second call reads local cache.
    sleep.assert_called_once_with(0.0)


def test_fetch_bytes_waits_at_least_five_seconds_for_429_without_retry_after(tmp_path):
    import run_benchmark

    url = "https://example.invalid/reference-image"
    rate_limited = urllib.error.HTTPError(
        url, 429, "Too Many Requests", {}, BytesIO(b"rate limited")
    )
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"fake-image-bytes"
    response.headers = {"Content-Type": "image/jpeg"}

    with (
        patch.object(run_benchmark, "IMAGE_CACHE_DIR", tmp_path),
        patch("run_benchmark.urllib.request.urlopen", side_effect=[rate_limited, response]),
        patch("run_benchmark.time.sleep") as sleep,
        patch("run_benchmark.random.uniform", return_value=0.1),
    ):
        result = run_benchmark.fetch_bytes(url)

    assert result == (b"fake-image-bytes", "image/jpeg")
    sleep.assert_called_once_with(5.0)
