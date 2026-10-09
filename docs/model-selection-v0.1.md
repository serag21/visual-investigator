# Model selection experiment v0.1

## Goal

Choose a multimodal model based on measured Visual Investigator performance, not marketing claims. Evaluate answer quality, false confidence, evidence requests, run completion/reliability, latency, and cost.

## Candidates

| Role | API model ID | Why test it |
|---|---|---|
| Quality/control candidate | `gemini-3.8-flash` | Official Google documentation lists this as a stable Flash model. Keep the existing partial run and finish it when availability allows. |
| Lower-cost/high-throughput candidate | `gemini-3.5-flash-lite` | Official Google documentation lists it as a stable multimodal model optimized for cost-efficient, high-volume agentic tasks. It supports image input and has a free tier. |
| Optional follow-up | `gemini-3.1-flash-lite` | Consider only after the first two candidates, if we need to measure whether the additional cost/capability tradeoff is worthwhile. |

Official references (checked 2026-10-09):
- Models and stable endpoint IDs: https://ai.google.dev/gemini-api/docs/models
- Gemini 3.8 Flash: https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- Gemini 3.5 Flash-Lite: https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- Pricing and free-tier status: https://ai.google.dev/gemini-api/docs/pricing
- Retry behavior for 429/503/5xx: https://ai.google.dev/gemini-api/docs/troubleshooting

## Controlled method

For each model, run the same eight seeded image cases twice:
1. `baseline`: minimal visual question-answering instructions.
2. `investigator`: the Visual Investigator procedure.

Use separate output files per exact model and condition. Never compare the baseline from one model against the investigator from another model as if that isolates the workflow effect.

The primary comparison within each model is baseline vs investigator. The secondary comparison is how each model performs across equivalent conditions.

## Reliability interpretation

- A 503 is a provider service-availability event, not evidence that the model's answers are poor.
- A completed response should be graded separately from request completion/failure.
- Record provider errors and retry counts separately from model-quality scores; do not silently treat failed calls as incorrect answers.
- A lower-tier model may cost less or offer higher throughput, but it is not guaranteed to avoid provider outages.
- More API keys in the same Google Cloud project do not multiply project quotas. Don't rotate keys to try to bypass limits.
- Production architecture should eventually use bounded retry/backoff, explicit error telemetry, and a fallback model/provider where policy, privacy, and product requirements allow it.

## Decision gate

Do not select a production default from eight cases alone. Use the pilot to identify failure modes and decide whether to extend the same comparison to the full 30-case set. A cheap model is acceptable only if its resolution quality and false-confidence behavior meet the product's minimum bar.
