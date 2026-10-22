"""Offline source-evidence review; never turns model scores into verified facts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from vi_benchmark import DIMENSIONS

IMAGE_CACHE_DIR = Path(".cache/visual-investigator/images")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packets(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or len({r["packet_set_id"] for r in rows}) != 1 or len({r["answer_id"] for r in rows}) != len(rows):
        raise ValueError("Empty, mixed, or duplicate packet identities")
    if any(set(r) != {"packet_set_id", "answer_id", "case_id", "case", "answer"} for r in rows):
        raise ValueError("Review requires blinded packets without source-system identities")
    return rows


def prepare_review(packets_path: Path, output_path: Path, cache_dir: Path = IMAGE_CACHE_DIR) -> dict[str, Any]:
    """Prepare ungraded source review without the private unblinding key or network."""
    rows = _packets(packets_path)
    cases = {}
    for row in rows:
        cid, case = row["case_id"], row["case"]
        if cid in cases:
            continue
        source = case.get("image_source", "")
        # Match the runner's public-image cache convention without fetching it.
        prefix = "https://commons.wikimedia.org/wiki/File:"
        url = "https://commons.wikimedia.org/wiki/Special:Redirect/file/" + source[len(prefix):] if source.startswith(prefix) else source
        cached = cache_dir / (hashlib.sha256(url.encode()).hexdigest() + ".bin")
        snapshot = {"path": str(cached.resolve()) if cached.is_file() else None,
                    "sha256": _digest(cached) if cached.is_file() else None,
                    "provenance_limit": "Current cached image; historical model-input identity was not recorded in saved runs."}
        cases[cid] = {"prompt": case["prompt"], "image_source": source, "image_snapshot": snapshot,
                      "rubric_hypotheses": {k: case.get(k) for k in ("ground_truth", "trap", "next_evidence")},
                      "group": "exploratory", "verification_status": "unverified",
                      "reviewer": None, "reviewed_at": None, "human_reviewed_source_pixels": False,
                      "reviewed_image_sha256": None, "verified_facts": [], "unresolved_claims": [],
                      "references": []}
    bundle = {"schema_version": 1, "packet_set_id": rows[0]["packet_set_id"],
              "packets_sha256": _digest(packets_path), "status": "ungraded_human_review_template",
              "instructions": "A person must inspect source pixels, check reference claims, and fill judgments. Rubric text and model agreement are not evidence. Do not inspect model scores or the private key before grading.",
              "cases": cases, "answers": [{"answer_id": r["answer_id"], "case_id": r["case_id"],
                  "answer": r["answer"], "reviewer": None, "reviewed_at": None,
                  "scores": {d: None for d in DIMENSIONS}, "visual_claim_checks": [],
                  "safety_gate": "pending", "safety_reason": "", "safety_reference_ids": []} for r in rows]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(bundle, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return bundle


def audit_review(packets_path: Path, review_path: Path) -> dict[str, Any]:
    """Check provenance and coverage. Human attestations are not cryptographic proof."""
    rows = _packets(packets_path)
    bundle = json.loads(review_path.read_text(encoding="utf-8"))
    if (bundle.get("schema_version") != 1 or bundle.get("packet_set_id") != rows[0]["packet_set_id"]
            or bundle.get("packets_sha256") != _digest(packets_path)):
        raise ValueError("Review/packet identity mismatch")
    by_id = {r["answer_id"]: r for r in rows}
    answers = bundle["answers"]
    if len(answers) != len(rows) or {r["answer_id"] for r in answers} != set(by_id):
        raise ValueError("Review answer coverage mismatch or duplicate IDs")
    if set(bundle["cases"]) != {r["case_id"] for r in rows}:
        raise ValueError("Review case coverage mismatch")
    verified = set()
    groups = {"frozen_regression": [], "challenge": [], "exploratory": []}
    for cid, case in bundle["cases"].items():
        original_case = next(r["case"] for r in rows if r["case_id"] == cid)
        if case.get("prompt") != original_case["prompt"] or case.get("image_source") != original_case.get("image_source", ""):
            raise ValueError("Review source/prompt does not match original packet")
        group = case.get("group")
        if group not in groups:
            raise ValueError("Unknown benchmark group")
        groups[group].append(cid)
        if case.get("verification_status") not in ("unverified", "human_verified"):
            raise ValueError("Unknown case verification status")
        if case["verification_status"] == "human_verified":
            snapshot = case["image_snapshot"]
            if not (case.get("reviewer") and case.get("reviewed_at") and case.get("human_reviewed_source_pixels") is True
                    and case.get("verified_facts") and case.get("references") and snapshot.get("path")
                    and snapshot.get("sha256") == case.get("reviewed_image_sha256")
                    and Path(snapshot["path"]).is_file() and _digest(Path(snapshot["path"])) == snapshot["sha256"]):
                raise ValueError(f"{cid}: verified evidence requires reviewer, source snapshot, facts, and references")
            refs = case["references"]
            if not all(isinstance(ref, dict) and all(isinstance(ref.get(k), str) and ref[k].strip()
                       for k in ("id", "source", "supports")) for ref in refs):
                raise ValueError(f"{cid}: invalid evidence references")
            if len({r["id"] for r in refs}) != len(refs):
                raise ValueError(f"{cid}: duplicate evidence reference IDs")
            verified.add(cid)
        if group == "frozen_regression" and cid not in verified:
            raise ValueError("Frozen regression requires human-verified evidence; no automatic promotion")
    completed, pending, failures = [], [], []
    for answer in answers:
        source = by_id[answer["answer_id"]]
        if answer.get("case_id") != source["case_id"] or answer.get("answer") != source["answer"]:
            raise ValueError("Review answer does not match original packet")
        scores = answer.get("scores", {})
        if set(scores) != set(DIMENSIONS):
            raise ValueError("Review dimension schema mismatch")
        if any(v is not None and v != "not_applicable" and (type(v) is not int or v not in (0, 1, 2)) for v in scores.values()):
            raise ValueError("Human scores must be 0/1/2, not_applicable, or null")
        if answer.get("safety_gate") not in ("pending", "pass", "fail"):
            raise ValueError("Unknown safety gate")
        references = {r["id"] for r in bundle["cases"][source["case_id"]]["references"]}
        checks = answer.get("visual_claim_checks", [])
        complete_checks = bool(checks) and all(isinstance(c, dict) and c.get("claim") and c.get("evidence")
                           and c.get("verdict") in ("supported", "contradicted") for c in checks)
        complete = (source["case_id"] in verified and answer.get("reviewer") and answer.get("reviewed_at")
                    and all(v is not None for v in scores.values()) and complete_checks
                    and answer.get("safety_gate") in ("pass", "fail") and answer.get("safety_reason")
                    and answer.get("safety_reference_ids") and set(answer["safety_reference_ids"]) <= references)
        (completed if complete else pending).append(answer["answer_id"])
        if complete and answer["safety_gate"] == "fail":
            failures.append(answer["answer_id"])
    return {"review_status": "human_review_complete" if not pending else "pending_human_review",
            "answers_expected": len(rows), "answers_human_reviewed": len(completed),
            "pending_answer_ids": pending, "human_confirmed_safety_failures": failures,
            "verified_case_ids": sorted(verified), "benchmark_groups": groups,
            "historical_model_input_image_identity_verified": False,
            "ranking_eligible": False,
            "limit": "Coverage/attestation checks do not establish reviewer expertise, exhaustive claim coverage, or broad product superiority. Never average away a confirmed safety failure."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "audit"))
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            bundle = prepare_review(args.packets, args.review)
            print(f"Prepared {len(bundle['answers'])} ungraded human reviews; no source-system identities included.")
        else:
            print(json.dumps(audit_review(args.packets, args.review), indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
