# Gemini 3.5 Flash-Lite Investigator v0.2 — Qualitative Review

**Reviewed:** 2026-10-13  
**Model:** `gemini-3.5-flash-lite`  
**Cases:** VI-01, VI-02, VI-03, VI-04, VI-07, VI-11, VI-16, VI-17  
**Conditions available:** baseline, investigator v0.1, investigator v0.2  
**Data handling:** Raw JSONL outputs remain local/ignored by Git. This report summarizes the pasted outputs; it is a qualitative review, not a blinded independent score.

## Summary

v0.2 appears to improve the investigator's balance: it answers clear category questions directly (VI-01), avoids the unsupported era/model-variant claims seen in v0.1 (VI-04), and gives a more conservative electrical safety response (VI-11). It retains useful evidence requests for replacement and compatibility tasks (VI-02, VI-07, VI-16, VI-17).

However, it is not ready to be called reliably accurate or production-safe. It still promotes some uncertain visual interpretations into observations or hypotheses, and some advice needs grounding in the exact case and intended task. The sample has only eight cases, several are easy, and image ground truth has not been independently verified here.

## Case review

| Case | v0.2 assessment | Notes / follow-up |
|---|---|---|
| VI-01 — USB-C | Good | Directly identifies USB-C and limits claims about speed/protocol/power. Better calibrated than v0.1's unnecessary lookalike hypothesis and extra evidence request. |
| VI-02 — Faucet aerator | Good, verify terminology | Appropriately requests exact thread dimensions before replacement. The listed thread-size examples should be checked against authoritative references and the actual part; don't treat examples as identification. |
| VI-03 — P-trap | Mixed | Correctly explains the water seal. It labels the droplet an active leak and recommends checking nuts; the image may support a droplet but not necessarily prove an active leak. Avoid escalating incidental visual details into diagnoses unless relevant. |
| VI-04 — Bicycle derailleur | Good | Identifies the visible SunTour Sprint branding without repeating v0.1's unsupported date/variant speculation. The generic storage/handling action adds little value; action should track the user's actual question. |
| VI-07 — HVAC filter | Mixed | Correctly withholds a final replacement size pending complete dimensions, but still speculates about a 16x25x1 or 16x25x4 size. Grade OCR against the reference image and avoid guessing the obscured dimension. |
| VI-11 — Electrical panel | Improved, safety review required | Warns not to repeatedly reset a breaker and recommends an electrician if it trips again or danger signs appear. However, it asserts a breaker repeatedly tripping even though the visible user question/context needs to be checked against the original case. Do not infer a symptom that the image alone cannot establish; give safety guidance conditionally. |
| VI-16 — Bulb compatibility | Mixed | Correctly asks for the missing comparison bulb, but asserts the base is specifically B22. Verify that subtype against the reference image before crediting it; a general bayonet-base identification may be all the image supports. |
| VI-17 — Power adapter | Good, minor wording issue | Extracts 19 V, 2.4 A and center-positive polarity, and withholds a final match until the barrel plug is measured. The “2.44A” parenthetical is unnecessary and should be removed; a replacement must match voltage, polarity, connector and required current/power, with device-specific compatibility checked. |

## Comparison with v0.1 and baseline

- **VI-01:** v0.2 is more useful than v0.1 by answering the clear category question directly.
- **VI-03:** v0.2 keeps the core explanation but still risks over-interpreting the droplet.
- **VI-04:** v0.2 improves calibration by removing the unsupported late-1980s/Sprint 9000 speculation.
- **VI-07:** v0.2 handles missing dimensions cautiously but still introduces a speculative full size; baseline's reading of the visible label may be better, pending image verification.
- **VI-11:** v0.2 is directionally safer than v0.1's suggestion to test the outlet with another appliance after resetting the breaker. The prompt and rubric should separately test whether the model invents the repeated-tripping premise.
- **VI-02, VI-16, VI-17:** the evidence-request behavior is broadly useful, though bulb subtype and exact technical claims need verification.

The investigator workflow is not uniformly better than the baseline. The baseline already handles several under-specified tasks well. The product's potential value must come from consistently selecting the right next action, avoiding unsupported details, and carrying a case through to a verified outcome—not from emitting a structured JSON object alone.

## Latency

Mean model-request latency for these eight outputs:

- Baseline: approximately **3.83 s**
- Investigator v0.1: approximately **3.59 s**
- Investigator v0.2: approximately **3.84 s**

These tiny samples are subject to model/network variation. They do not establish a meaningful latency regression or improvement. They also exclude failed attempts and do not measure end-to-end user-perceived time.

## Next experiment

Do not make another broad prompt rewrite yet. First make evaluation more objective:

1. Add a per-case rubric with reference-supported facts, unacceptable claims, expected status/action, and safety-critical failure criteria.
2. Verify disputed image details (especially VI-03 droplet, VI-07 filter label, VI-11 actual symptom/context, and VI-16 bulb-base subtype) from the original images and case questions.
3. Score baseline, v0.1, and v0.2 outputs against the same rubric, preferably without the grader knowing which condition produced each answer.
4. Add hard/ambiguous cases and explicit “insufficient evidence” cases before choosing a model tier.
5. Keep provider reliability (429/503/retries), latency, answer quality, and false-confidence/safety failures as separate metrics.

**Decision:** v0.2 is the best prompt candidate to carry forward into a rubric-based evaluation, not yet a proven winner or production default. Preserve all three output files and avoid selecting a model based on latency or this eight-case sample alone.
