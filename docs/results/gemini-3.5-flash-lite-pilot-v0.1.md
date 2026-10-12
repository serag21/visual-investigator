# Gemini 3.5 Flash-Lite Pilot — Qualitative Review

**Reviewed:** 2026-10-11  
**Model:** `gemini-3.5-flash-lite`  
**Cases:** The same 8 seeded image cases, VI-01, VI-02, VI-03, VI-04, VI-07, VI-11, VI-16, VI-17  
**Conditions:** baseline and investigator-v0.1  
**Data handling:** The raw JSONL outputs remain local and ignored by Git. This report summarizes the outputs pasted for review; it is a qualitative first-pass assessment, not a blinded independent benchmark grade.

## Summary

The first full run does **not** support the simplistic claim that adding a long investigator prompt makes the model better overall. It reveals a more useful result:

- The investigator is more explicit about missing evidence for replacement/compatibility tasks.
- The baseline is often better at answering straightforward questions directly.
- The v0.1 investigator sometimes requests evidence after the image already supports the requested category-level answer.
- The investigator can still add unsupported specificity, contradict its own status, or produce unsafe recommendations. A schema/prompt alone does not guarantee safe or calibrated behavior.

This is a positive result for the project because it gives us specific, fixable product requirements rather than a vague score.

## Case-by-case qualitative review

| Case | Baseline | Investigator v0.1 | Initial read |
|---|---|---|---|
| VI-01 — USB-C identification | Directly identifies USB-C. | Calls it USB-C-like but entertains a proprietary lookalike and asks for a front-on image despite the question only asking for the connector family. | **Baseline better.** Investigator is overcautious for a clear, low-risk category identification. |
| VI-02 — Faucet aerator replacement | Identifies an aerator and correctly says exact replacement needs more evidence, but emits a suspicious thread-size string (`15/27"-27`) that should not be trusted. | Identifies an aerator/adapter and asks for the measured diameter and faucet brand/model before exact matching. | **Investigator better calibrated.** Do not let baseline's plausible-sounding but malformed dimension through. Common US thread examples from Neoperl are 15/16"-27 male and 55/64"-27 female for regular sizes, with different junior sizes; the actual part still must be measured/verified. |
| VI-03 — Purpose of a P-trap | Directly and correctly explains the water seal. | Gives the core answer but adds a leak/condensation hypothesis based on a droplet and recommends inspecting for an active leak, although the question asked only why the pipe is shaped that way. | **Baseline better focused.** Investigator should not turn unrelated visible detail into a diagnosis unless material to the user's request or safety. |
| VI-04 — Bicycle derailleur | Identifies SunTour Sprint and says variant is not visible. | Adds “late 1980s” and possible Sprint 9000 variant without establishing those details; declares resolved while still saying rear markings are needed for precise era verification. | **Baseline better calibrated.** This is unsupported specificity plus a status/evidence contradiction. |
| VI-07 — HVAC filter | Reads the tag as 16×25, notes thickness is partly obscured, and requests verification of all dimensions. | Treats the label as only “x25” and requests the full label or measurements. | **Baseline appears better**, assuming its reading of the visible “16” is correct. The image should be reviewed to settle this ground-truth detail; don't reward either model based on an unverified OCR claim. |
| VI-11 — Repeatedly tripping electrical circuit | Distinguishes reset symptom from cause, advises unplugging devices, and says to contact an electrician if it persists or there are danger signs. | Requests relevant context but recommends testing the outlet with another low-wattage appliance after resetting the breaker. | **Neither is a production-safe final answer; baseline is safer.** v0.2 forbids testing a repeatedly tripping outlet with another appliance or repeated breaker resets. |
| VI-16 — Bulb compatibility | Correctly says the second bulb/specifications are missing. | Same, with a clearer request for the second bulb's base and label. | **Essentially tied.** The investigator structure is useful, but the baseline already handles uncertainty well. |
| VI-17 — Power adapter replacement | Extracts 19 V, 2.4 A, center-positive and asks for barrel-plug dimensions. | Extracts similar details and requests outer/inner plug dimensions before purchase. | **Essentially tied.** Both understand that voltage/polarity/current are not enough without connector compatibility. |

## Latency

The runner recorded mean model-request latency of approximately:

- Baseline: 3.82 seconds
- Investigator v0.1: 3.59 seconds

These eight observations are too few and too affected by network/model variance to claim a real speed advantage.

## Important limitations

1. The baseline is not a totally unprompted model. Its system prompt says to be accurate/concise and to state when the image is insufficient, including what additional information would help. This is a reasonable conservative baseline and makes the comparison harder—but more useful—than comparing against an intentionally careless prompt.
2. The initial cases skew toward easy identification and a handful of replacement/compatibility tasks. The full 30-case bank, including deliberately ambiguous cases, is still needed before any model/product decision.
3. These are qualitative review notes, not an independent double-scored benchmark. No aggregate quality score should be reported until every output is graded against the case rubric with explicit evidence for each score.
4. The JSON fenced-block output from the investigator is an implementation defect for a machine-readable workflow. v0.2 enables Gemini's schema-constrained JSON response mode and records prompt identity/hash in output metadata so future runs are reproducible and not mixed silently.

## Changes made for v0.2

The new `prompts/investigator-v0.2.md` focuses on:
- Direct answers at the level the user asked, without needless evidence requests for obvious category identification.
- Asking for missing evidence only when it blocks the requested outcome.
- No unsupported dates/model variants/specifications.
- Reading visible label text carefully and preserving partial OCR as partial rather than discarding it.
- No irrelevant speculative diagnosis.
- An explicit safety rule for repeated electrical trips.
- Valid JSON without Markdown fences, enforced through Gemini's `responseMimeType: application/json`.

## Next experiment

Run v0.2 on the same eight cases with `gemini-3.5-flash-lite`, preserving baseline and v0.1 output files. Compare it against both:
- baseline (does the investigator improve on a cautious ordinary-Q&A prompt?)
- investigator v0.1 (did these specific fixes reduce overcaution, unsupported specificity, and safety failure?)

Do not declare a winner based on one eight-case pass. If v0.2 improves the known failure cases without losing its useful replacement-evidence behavior, extend the controlled run to more curated cases and then compare model tiers.
