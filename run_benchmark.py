"""Run Visual Investigator benchmark cases against OpenAI or Gemini.

This runner deliberately separates execution from grading. It emits JSONL with
model answers; scoring/grading happens afterward.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

def load_local_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


FIRST_RUN_IDS = {
    "VI-01",
    "VI-02",
    "VI-03",
    "VI-04",
    "VI-07",
    "VI-11",
    "VI-16",
    "VI-17",
}

BASELINE_PROMPT = """Answer the user's question based on the supplied image.
Be accurate and concise. If the image does not provide enough information,
say what you cannot determine and what additional information would help."""

WIKIMEDIA_FILE_RE = re.compile(r"^https://commons\.wikimedia\.org/wiki/File:(.+)$")


def load_cases(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def resolve_image_url(source: str) -> str:
    match = WIKIMEDIA_FILE_RE.match(source)
    if match:
        filename = match.group(1)
        return f"https://commons.wikimedia.org/wiki/Special:Redirect/file/{filename}"
    return source


def fetch_bytes(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "visual-investigator-benchmark/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0]
    return data, content_type


def request_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    transient_codes = {429, 500, 502, 503, 504}

    for attempt in range(5):
        request = urllib.request.Request(
            url,
            data=body,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in transient_codes or attempt == 4:
                raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc

            retry_after = exc.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else min(20.0, 2.0 ** attempt)
            except ValueError:
                delay = min(20.0, 2.0 ** attempt)

            print(f"Transient HTTP {exc.code}; retrying in {delay:.1f}s...")
            time.sleep(delay)


def run_openai(case: dict[str, Any], system_prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    image_url = resolve_image_url(case["image_source"])
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": case["prompt"]},
                    {"type": "input_image", "image_url": image_url, "detail": "auto"},
                ],
            },
        ],
    }
    data = request_json(
        "https://api.openai.com/v1/responses",
        payload,
        {"Authorization": f"Bearer {api_key}"},
    )
    text = data.get("output_text")
    if not isinstance(text, str):
        raise RuntimeError(f"OpenAI response did not contain output_text: {data!r}")
    return text


def run_gemini(case: dict[str, Any], system_prompt: str, model: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    image_bytes, mime_type = fetch_bytes(resolve_image_url(case["image_source"]))
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": case["prompt"]},
                    {"inlineData": {"mimeType": mime_type, "data": image_b64}},
                ],
            }
        ],
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = request_json(url, payload, {"x-goog-api-key": api_key})
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini response had no candidates: {data!r}")
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if isinstance(part.get("text"), str)]
    answer = "".join(texts).strip()
    if not answer:
        raise RuntimeError(f"Gemini response contained no text: {data!r}")
    return answer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("openai", "gemini"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--condition", choices=("baseline", "investigator"), required=True)
    parser.add_argument("--cases", type=Path, default=Path("benchmark/cases.json"))
    parser.add_argument(
        "--investigator-prompt",
        type=Path,
        default=Path("prompts/investigator-v0.1.md"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    load_local_env()
    benchmark = load_cases(args.cases)
    prompt = (
        BASELINE_PROMPT
        if args.condition == "baseline"
        else load_prompt(args.investigator_prompt)
    )

    selected = [case for case in benchmark["cases"] if case["id"] in FIRST_RUN_IDS]
    selected.sort(key=lambda case: case["id"])

    args.output.parent.mkdir(parents=True, exist_ok=True)

    completed_ids: set[str] = set()
    if args.output.exists():
        with args.output.open("r", encoding="utf-8") as existing:
            for line in existing:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    record.get("provider") == args.provider
                    and record.get("model") == args.model
                    and record.get("condition") == args.condition
                ):
                    completed_ids.add(record.get("case_id", ""))

    pending = [case for case in selected if case["id"] not in completed_ids]
    if completed_ids:
        print(f"Resuming {args.condition}: skipping {len(completed_ids)} completed case(s).")

    mode = "a" if args.output.exists() else "w"
    with args.output.open(mode, encoding="utf-8") as fh:
        completed_now = len(completed_ids)
        for case in pending:
            completed_now += 1
            started = time.perf_counter()
            if args.provider == "openai":
                answer = run_openai(case, prompt, args.model)
            else:
                answer = run_gemini(case, prompt, args.model)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)

            record = {
                "case_id": case["id"],
                "system": f"{args.provider}:{args.model}:{args.condition}",
                "provider": args.provider,
                "model": args.model,
                "condition": args.condition,
                "answer": answer,
                "latency_ms": latency_ms,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{completed_now}/{len(selected)}] {case['id']} {latency_ms} ms")

    print(f"Benchmark output contains {len(completed_ids) + len(pending)} run(s) at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
