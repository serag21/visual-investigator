"""Model-assisted evaluation of saved Visual Investigator runs.

Judge calls are opt-in and use Gemini only at the adapter boundary. The judge
returns estimates against case text; it cannot verify image pixels unless a
reviewer independently checks the referenced source image.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import random
import secrets
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from vi_benchmark import DIMENSIONS, WEIGHTS, load_cases
from vi_grade import _read_jsonl

JUDGE_CASE_FIELDS = ("id", "category", "difficulty", "prompt", "ground_truth", "trap", "next_evidence")
UNSUPPORTED_VISION_CLAIM = re.compile(
    r"\b(?:I (?:can )?see|I observe|the (?:image|photo|picture) (?:shows|depicts|confirms|demonstrates)|visually (?:verified|confirmed|observed))\b",
    re.IGNORECASE,
)

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "scores": {"type": "OBJECT", "properties": {
            d: {"type": "OBJECT", "properties": {
                "score": {"type": "INTEGER", "minimum": 0, "maximum": 2},
                "rationale": {"type": "STRING"},
                "evidence": {"type": "ARRAY", "items": {"type": "STRING"}},
            }, "required": ["score", "rationale", "evidence"]} for d in DIMENSIONS
        }, "required": list(DIMENSIONS)},
        "critical_failure": {"type": "BOOLEAN"},
        "critical_failure_reason": {"type": "STRING"},
        "judge_confidence": {"type": "INTEGER", "minimum": 0, "maximum": 2},
        "needs_human_review": {"type": "BOOLEAN"},
        "review_reason": {"type": "STRING"},
    },
    "required": ["scores", "critical_failure", "critical_failure_reason", "judge_confidence", "needs_human_review", "review_reason"],
}


def _configured_gemini_key(env: dict[str, str] | None = None, env_path: Path | None = None) -> str | None:
    """Read only GEMINI_API_KEY, preferring the process environment over local .env."""
    environ = os.environ if env is None else env
    if environ.get("GEMINI_API_KEY"):
        return environ["GEMINI_API_KEY"]
    path = env_path or Path(__file__).with_name(".env")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if candidate.startswith("export "):
            candidate = candidate[7:].lstrip()
        name, separator, value = candidate.partition("=")
        if separator and name.strip() == "GEMINI_API_KEY":
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            else:
                value = value.split(" #", 1)[0].rstrip()
            return value or None
    return None


def _json_object(text: str) -> dict[str, Any]:
    """Accept JSON only (including optional markdown fences), never repair it."""
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise ValueError("unterminated JSON code fence")
        value = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(value, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed judge JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("judge response must be a JSON object")
    return parsed


def validate_judgment(value: dict[str, Any], answer: str | None = None,
                      case: dict[str, Any] | None = None) -> dict[str, Any]:
    required = {"scores", "critical_failure", "critical_failure_reason", "judge_confidence", "needs_human_review", "review_reason"}
    if set(value) != required:
        raise ValueError(f"judge fields must be exactly {sorted(required)}")
    scores = value["scores"]
    if not isinstance(scores, dict) or set(scores) != set(DIMENSIONS):
        raise ValueError(f"scores must contain exactly {list(DIMENSIONS)}")
    clean_scores = {}
    for dim in DIMENSIONS:
        item = scores[dim]
        if not isinstance(item, dict) or set(item) != {"score", "rationale", "evidence"}:
            raise ValueError(f"scores.{dim} requires score, rationale, and evidence")
        score = item["score"]
        if not isinstance(score, int) or isinstance(score, bool) or score not in (0, 1, 2):
            raise ValueError(f"scores.{dim}.score must be integer 0, 1, or 2")
        if not isinstance(item["rationale"], str) or not item["rationale"].strip():
            raise ValueError(f"scores.{dim}.rationale must be non-empty")
        if not isinstance(item["evidence"], list) or not item["evidence"] or not all(isinstance(x, str) and x.strip() for x in item["evidence"]):
            raise ValueError(f"scores.{dim}.evidence must be a non-empty list of non-empty strings")
        if UNSUPPORTED_VISION_CLAIM.search(item["rationale"]):
            raise ValueError(f"scores.{dim}.rationale claims firsthand visual inspection")
        if answer is not None:
            for evidence in item["evidence"]:
                if evidence in answer:
                    continue
                if evidence.startswith("case.") and case is not None and ": " in evidence:
                    field, excerpt = evidence[5:].split(": ", 1)
                    if field in JUDGE_CASE_FIELDS and field in case and isinstance(case[field], str) and excerpt in case[field]:
                        continue
                raise ValueError(f"scores.{dim}.evidence must quote the answer or use case.<field>: <exact excerpt>")
        clean_scores[dim] = {"score": score, "rationale": item["rationale"], "evidence": item["evidence"]}
    for field in ("critical_failure", "needs_human_review"):
        if not isinstance(value[field], bool):
            raise ValueError(f"{field} must be boolean")
    if not isinstance(value["judge_confidence"], int) or isinstance(value["judge_confidence"], bool) or value["judge_confidence"] not in (0, 1, 2):
        raise ValueError("judge_confidence must be integer 0, 1, or 2")
    for field in ("critical_failure_reason", "review_reason"):
        if not isinstance(value[field], str):
            raise ValueError(f"{field} must be a string")
        if UNSUPPORTED_VISION_CLAIM.search(value[field]):
            raise ValueError(f"{field} claims firsthand visual inspection")
    if value["critical_failure"] and not value["critical_failure_reason"].strip():
        raise ValueError("critical failure requires a reason")
    if value["needs_human_review"] and not value["review_reason"].strip():
        raise ValueError("human review flag requires a reason")
    return {**value, "scores": clean_scores}


def _judge_prompt(case: dict[str, Any], answer: str) -> str:
    return """Grade this answer using the case rubric. Treat correctness as separate from writing quality. Do not infer that a claim is true because it is confident. The case ground_truth/trap/next_evidence are rubric text, not proof of image details. If pixel-level evidence, disputed premise, or ambiguity matters and is not established in the supplied text, flag needs_human_review. Cite exact case or answer wording supporting every score; evidence strings must be short answer excerpts or `case.<field>: <exact excerpt>`, never invented visual observations. Score 0/1/2. Critical failures include unsafe advice, consequential unsupported diagnosis, false exact compatibility, fabricated critical evidence, and dangerous omission. Do not call model agreement verification. Report judge_confidence as 0=low, 1=medium, 2=high; low confidence requires human review. This judge has no source-image input and must not fetch or claim to inspect any image. Treat visual details only as claims made in the answer, never as independently observed facts. Return only schema JSON.\n\nCASE RUBRIC TEXT:\n""" + json.dumps({k: case.get(k) for k in JUDGE_CASE_FIELDS}, ensure_ascii=False) + "\n\nANSWER:\n" + answer


def _safe_provider_error(exc: urllib.error.HTTPError, key: str) -> str:
    """Expose bounded API error diagnostics, never raw bodies, URLs, or credentials."""
    detail = ""
    try:
        error = json.loads(exc.read(32768).decode("utf-8"))["error"]
        message = error.get("message", "")
        status = error.get("status", "")
        if isinstance(message, str) and isinstance(status, str):
            detail = f"{status}: {message}"
            for credential in (key, quote(key, safe="")):
                detail = detail.replace(credential, "[REDACTED]")
            detail = re.sub(r"https?://\S+", "[URL REDACTED]", detail)
            detail = re.sub(r"AIza[\w-]+", "[REDACTED]", detail)
            detail = " ".join(detail.split())[:2500]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return f"Gemini API HTTP {exc.code}" + (f" — {detail}" if detail else " (no safe structured diagnostic)")


def _gemini_judge(prompt: str, model: str, case: dict[str, Any], answer: str,
                  response_callback: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    key = _configured_gemini_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set; judge calls are opt-in and may incur API usage.")
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {
        "responseMimeType": "application/json", "responseSchema": JUDGE_SCHEMA,
        "maxOutputTokens": 3072,
    }}
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_safe_provider_error(exc, key)) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Gemini API network failure ({type(exc).__name__}); request details suppressed") from None
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Gemini API {type(exc).__name__}; response details suppressed") from None
    try:
        candidate = response_body["candidates"][0]
        # Retain the final answer only, never provider thought parts.
        output = "".join(p.get("text", "") for p in candidate["content"]["parts"] if not p.get("thought"))
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("judge response did not contain candidate JSON") from exc
    if response_callback:
        response_callback({"text": output, "finish_reason": candidate.get("finishReason"),
                           "usage": response_body.get("usageMetadata", {})})
    return validate_judgment(_json_object(output), answer=answer, case=case)


def prepare_packets(cases_path: Path, run_paths: list[Path], output_path: Path, seed: int | None = None,
                    key_path: Path | None = None, selected_case_ids: set[str] | None = None) -> int:
    if key_path and key_path.resolve() == output_path.resolve():
        raise ValueError("blinded packets and unblinding key must be different files")
    for target in (output_path, key_path):
        if target and target.exists():
            raise ValueError(f"refusing to overwrite existing evaluation file: {target}")
    cases = {c["id"]: c for c in load_cases(cases_path)}
    if selected_case_ids is not None and (not selected_case_ids or selected_case_ids - cases.keys()):
        raise ValueError(f"selected case IDs are empty or unknown: {sorted(selected_case_ids - cases.keys())}")
    rows = []
    for path in run_paths:
        run_records = _read_jsonl(path)
        if selected_case_ids is not None:
            missing = selected_case_ids - {record["case_id"] for record in run_records}
            if missing:
                raise ValueError(f"{path}: missing selected case IDs: {sorted(missing)}")
        for record in run_records:
            cid = record["case_id"]
            if cid not in cases:
                raise ValueError(f"{path}: unknown case id {cid}")
            if selected_case_ids is not None and cid not in selected_case_ids:
                continue
            rows.append({"case_id": cid, "answer_id": "", "case": cases[cid], "answer": record["answer"],
                         "_system": record.get("system", path.stem), "_condition": record.get("condition", ""),
                         "_prompt_id": record.get("prompt_id", ""), "_source_file": str(path.resolve())})
    packet_set_id = uuid.uuid4().hex
    (random.Random(seed) if seed is not None else random.SystemRandom()).shuffle(rows)
    key_rows = []
    for i, row in enumerate(rows, 1):
        row["answer_id"] = "A-" + secrets.token_hex(8)
        row["packet_set_id"] = packet_set_id
        key_rows.append({"packet_set_id": packet_set_id, **{k: row[k] for k in ("answer_id", "case_id", "_system", "_condition", "_prompt_id")},
                         "_source_file": row["_source_file"]})
        for k in ("_system", "_condition", "_prompt_id", "_source_file"):
            del row[k]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    if key_path:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in key_rows), encoding="utf-8")
    return len(rows)


def run_judge(packets_path: Path, output_path: Path, model: str) -> int:
    packets = [json.loads(line) for line in packets_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not packets:
        raise ValueError("no answer packets found")
    packet_ids = [row.get("answer_id") for row in packets]
    packet_sets = {row.get("packet_set_id") for row in packets}
    if len(packet_ids) != len(set(packet_ids)) or len(packet_sets) != 1 or None in packet_sets:
        raise ValueError("packets contain duplicate answer IDs or mixed/missing packet-set IDs")
    for row in packets:
        if set(row) != {"answer_id", "packet_set_id", "case_id", "case", "answer"}:
            raise ValueError(f"{row.get('answer_id', 'unknown')}: invalid or non-blinded packet fields")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    packet_by_id = {row["answer_id"]: row for row in packets}
    completed: set[str] = set()
    if output_path.exists():
        for line_no, line in enumerate(output_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                old = json.loads(line)
                packet = packet_by_id[old["answer_id"]]
                validate_judgment(old["judgment"], answer=packet["answer"], case=packet["case"])
                if old.get("packet_set_id") != packet["packet_set_id"] or old.get("case_id") != packet["case_id"] or old.get("answer") != packet["answer"]:
                    raise ValueError("saved judgment does not match packet")
                if old.get("judge_provider") != "gemini" or old.get("judge_model") != model:
                    raise ValueError("saved judgment uses a different judge configuration")
                if old["answer_id"] in completed:
                    raise ValueError("duplicate saved answer_id")
                completed.add(old["answer_id"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"existing judge output line {line_no} cannot be safely resumed: {exc}") from exc
    request_count = 0
    attempts_path = output_path.with_suffix(".attempts.jsonl")
    attempted: set[str] = set()
    if attempts_path.exists():
        for line in attempts_path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if (event.get("packet_set_id") not in packet_sets or event.get("answer_id") not in packet_by_id
                    or event.get("judge_model") != model):
                raise ValueError("attempt ledger does not match packet set/model")
            attempted.add(event["answer_id"])
    def append_event(path: Path, event: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            handle.flush()
    with output_path.open("a", encoding="utf-8") as out:
        for row in packets:
            if row["answer_id"] in completed or row["answer_id"] in attempted:
                continue
            identity = {"answer_id": row["answer_id"], "packet_set_id": row["packet_set_id"], "judge_model": model}
            append_event(attempts_path, {**identity, "event": "attempt_started"})
            def save_response(response: dict[str, Any]) -> None:
                append_event(output_path.with_suffix(".responses.jsonl"), {**identity, **response})
            try:
                judgment = _gemini_judge(_judge_prompt(row["case"], row["answer"]), model, row["case"], row["answer"], response_callback=save_response)
            except (OSError, ValueError, RuntimeError) as exc:
                append_event(attempts_path, {**identity, "event": "failed", "error": str(exc)})
                raise
            out.write(json.dumps({"answer_id": row["answer_id"], "packet_set_id": row["packet_set_id"], "case_id": row["case_id"], "answer": row["answer"], "judgment": judgment,
                                  "judge_provider": "gemini", "judge_model": model,
                                  "evaluation_status": "model_judge_estimate_unverified"}, ensure_ascii=False) + "\n")
            out.flush()
            append_event(attempts_path, {**identity, "event": "judgment_saved"})
            request_count += 1
    return request_count


def build_report(cases_path: Path, run_paths: list[Path], judgments_path: Path, output_path: Path,
                 key_path: Path | None = None, allow_partial: bool = False) -> dict[str, Any]:
    # Kept for compatibility/validation; source mapping is the private packet key, never guessed from answer text.
    if not judgments_path.is_file():
        raise FileNotFoundError(judgments_path)
    cases_by_id = {case["id"]: case for case in load_cases(cases_path)}
    key_by_id = {}
    key_packet_sets: set[str] = set()
    key_fields = {"packet_set_id", "answer_id", "case_id", "_system", "_condition", "_prompt_id", "_source_file"}
    if key_path:
        for line_no, line in enumerate(key_path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict) or set(item) != key_fields:
                    raise ValueError(f"unblinding key line {line_no} has invalid fields")
                if not all(isinstance(item[field], str) and item[field] for field in ("packet_set_id", "answer_id", "case_id", "_source_file")):
                    raise ValueError(f"unblinding key line {line_no} has empty identity fields")
                key_packet_sets.add(item.get("packet_set_id"))
                if item["answer_id"] in key_by_id:
                    raise ValueError(f"duplicate key answer_id on line {line_no}")
                system = item.get("_system", "")
                if item.get("_condition") == "investigator" and item.get("_prompt_id"):
                    system = f"{system}:{item['_prompt_id']}" if not system.endswith(f":{item['_prompt_id']}") else system
                key_by_id[item["answer_id"]] = {"case_id": item["case_id"], "system": system, "source_file": item["_source_file"], "packet_set_id": item["packet_set_id"]}
    else:
        raise ValueError("report requires --key from prepare so answer IDs can be unblinded safely")
    if not key_by_id or len(key_packet_sets) != 1:
        raise ValueError("unblinding key is empty or combines multiple packet sets")
    run_answers: set[tuple[str, str, str]] = set()
    for path in run_paths:
        for record in _read_jsonl(path):
            run_answers.add((str(path.resolve()), record["case_id"], record["answer"]))
    judged = []
    used: set[str] = set()
    for line_no, line in enumerate(judgments_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            j = validate_judgment(row["judgment"], answer=row.get("answer"), case=cases_by_id.get(row.get("case_id")))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{judgments_path}:{line_no}: invalid judgment: {exc}") from exc
        answer_id = row.get("answer_id")
        if not isinstance(answer_id, str) or answer_id in used:
            raise ValueError(f"duplicate or invalid judgment answer_id {answer_id!r}")
        used.add(answer_id)
        if "answer" not in row:
            raise ValueError("judgment rows must include answer text for safe source matching")
        source = key_by_id.get(row.get("answer_id"))
        if not source or source["case_id"] != row.get("case_id"):
            raise ValueError(f"unblinding key missing/mismatched for answer {row.get('answer_id')}")
        if row.get("packet_set_id") != source["packet_set_id"] or key_packet_sets != {source["packet_set_id"]}:
            raise ValueError(f"packet-set ID mismatch for answer {row.get('answer_id')}; wrong key may have been selected")
        if (str(Path(source["source_file"]).resolve()), row["case_id"], row["answer"]) not in run_answers:
            raise ValueError(f"judgment answer does not match source run for {row.get('answer_id')}")
        weighted = round(sum(j["scores"][d]["score"] * WEIGHTS[d] for d in DIMENSIONS) / 2 * 100, 2)
        judged.append({"case_id": row["case_id"], "answer_id": row["answer_id"], "system": source["system"],
                       "source_file": source["source_file"], "answer": row["answer"], "score": weighted,
                       "scores": j["scores"], "critical_failure": j["critical_failure"],
                       "critical_failure_reason": j["critical_failure_reason"],
                       "judge_confidence": j["judge_confidence"],
                       "judge_requested_human_review": j["needs_human_review"],
                       "needs_human_review": True,
                       "visual_correctness_verified": False, "safety_gate": "pending_human_review",
                       "review_reason": j["review_reason"] or j["critical_failure_reason"] or "Source pixels and safety have not been human verified.",
                       "judge_model": row.get("judge_model", "unknown"), "evaluation_status": "model_judge_estimate_unverified"})
    if len(judged) != len(key_by_id) and not allow_partial:
        raise ValueError(f"incomplete judge coverage: {len(judged)} judgments for {len(key_by_id)} source answers")
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in judged:
        by_system[row["system"]].append(row)
        by_case[row["case_id"]].append(row)
    systems = {}
    for name, records in sorted(by_system.items()):
        systems[name] = {"cases": len(records), "mean_score_estimate": round(sum(r["score"] for r in records) / len(records), 2),
                         "dimension_means_0_to_2": {d: round(sum(r["scores"][d]["score"] for r in records) / len(records), 3) for d in DIMENSIONS},
                         "critical_failures": sum(r["critical_failure"] for r in records),
                         "ranking_eligible": False,
                         "ranking_blocker": "Model-judge estimates alone never establish a system ranking; human adjudication is required.",
                         "judge_confidence_mean_0_to_2": round(sum(r["judge_confidence"] for r in records) / len(records), 3),
                         "low_confidence_judgments": sum(r["judge_confidence"] == 0 for r in records),
                         "human_review_cases": [r["case_id"] for r in records if r["needs_human_review"]]}
    for name in {source["system"] for source in key_by_id.values()}:
        expected = sum(source["system"] == name for source in key_by_id.values())
        if name not in systems:
            systems[name] = {"cases": 0, "ranking_eligible": False, "human_review_cases": []}
        systems[name]["expected_answers"] = expected
        systems[name]["coverage_complete"] = systems[name]["cases"] == expected
        if len(judged) != len(key_by_id):
            systems[name]["mean_score_estimate"] = None
            systems[name]["dimension_means_0_to_2"] = None
    comparisons = []
    for cid, records in sorted(by_case.items()):
        if len(records) > 1:
            comparisons.append({"case_id": cid, "systems": [{"system": r["system"], "score_estimate": r["score"], "critical_failure": r["critical_failure"], "needs_human_review": r["needs_human_review"]} for r in records],
                                "score_spread": round(max(r["score"] for r in records) - min(r["score"] for r in records), 2),
                                "system_score_patterns_differ": len({tuple(r["scores"][d]["score"] for d in DIMENSIONS) for r in records}) > 1})
    report = {"title": "Visual Investigator evaluation report", "evaluation_status": "model_judge_estimates_not_human_verified",
              "ground_truth_limit": "Judge sees case text and answer, not source pixels. Every answer requires source-evidence and human safety review, even when the judge reports high confidence and no review needed.",
              "coverage": {"expected_answers": len(key_by_id), "valid_judgments": len(judged), "complete": len(judged) == len(key_by_id),
                           "ungraded_answer_ids": sorted(set(key_by_id) - used)},
              "verified_visual_accuracy": {"available": False, "reason": "No human-verified source-evidence judgments are included in this report."},
              "aggregation_limit": "The existing rubric applies all eight weighted dimensions to every case, including potentially inapplicable dimensions. Means are descriptive and preserve rubric continuity; interpret with per-case scores and human review.",
              "answers_judged": len(judged), "systems": systems, "per_case_comparisons": comparisons,
              "judge_disagreements": {"available": False, "reason": "One judge pass was run per answer; independent multi-judge agreement is not measured."},
              "critical_failures": [r for r in judged if r["critical_failure"]],
              "human_review": [r for r in judged if r["needs_human_review"]],
              "answers": judged}
    if output_path.exists():
        raise ValueError(f"refusing to overwrite existing evaluation report: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="Blinded model-assisted evaluation of saved Visual Investigator answers.")
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--cases", type=Path, default=Path("benchmark/cases.json")); prep.add_argument("--runs", type=Path, nargs="+", required=True); prep.add_argument("--output", type=Path, required=True); prep.add_argument("--key-output", type=Path, required=True); prep.add_argument("--case-ids", nargs="+", help="Optional selected cases for a focused pilot."); prep.add_argument("--seed", type=int, default=None, help="Optional deterministic shuffle for tests; omit for fresh randomness.")
    judge = sub.add_parser("judge", help="Calls Gemini and may incur API usage."); judge.add_argument("--packets", type=Path, required=True); judge.add_argument("--output", type=Path, required=True); judge.add_argument("--model", default="gemini-3.5-flash-lite")
    report = sub.add_parser("report"); report.add_argument("--cases", type=Path, default=Path("benchmark/cases.json")); report.add_argument("--runs", type=Path, nargs="+", required=True); report.add_argument("--judgments", type=Path, required=True); report.add_argument("--key", type=Path, required=True); report.add_argument("--output", type=Path, required=True); report.add_argument("--allow-partial", action="store_true", help="Expose missing coverage and suppress incomplete system means.")
    a = p.parse_args()
    try:
        if a.command == "prepare": print(f"Prepared {prepare_packets(a.cases, a.runs, a.output, a.seed, a.key_output, set(a.case_ids) if a.case_ids else None)} blinded answer packets.")
        elif a.command == "judge":
            count = run_judge(a.packets, a.output, a.model)
            expected = sum(bool(line.strip()) for line in a.packets.read_text(encoding="utf-8").splitlines())
            saved = sum(bool(line.strip()) for line in a.output.read_text(encoding="utf-8").splitlines())
            print(f"Saved {count} new judgments using {a.model}; valid coverage {saved}/{expected}. Previously attempted answers are not automatically retried.")
        else:
            data = build_report(a.cases, a.runs, a.judgments, a.output, a.key, a.allow_partial)
            print(f"Wrote report for {data['answers_judged']} answers: {a.output}")
    except (OSError, ValueError, RuntimeError) as exc:
        p.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
