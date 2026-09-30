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
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


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

    benchmark = load_cases(args.cases)
    prompt = (
        BASELINE_PROMPT
        if args.condition == "baseline"
        else load_prompt(args.investigator_prompt)
    )

    selected = [case for case in benchmark["cases"] if case["id"] in FIRST_RUN_IDS]
    selected.sort(key=lambda case: case["id"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for index, case in enumerate(selected, 1):
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
            print(f"[{index}/{len(selected)}] {case['id']} {latency_ms} ms")

    print(f"Wrote {len(selected)} runs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
