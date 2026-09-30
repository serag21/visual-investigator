# AGENTS.md

## Project purpose

Visual Investigator is currently a benchmark-first project. The goal is to test and improve an evidence-driven visual investigation workflow before building a consumer app.

## Working rules

- Prefer small, testable increments.
- Keep benchmark data, execution, grading, and product/UI code separate.
- Never commit API keys, credentials, private user photos, or raw benchmark outputs that may contain sensitive data.
- Do not claim a model result is verified until the relevant case evidence and grading support it.
- Treat false confidence as a first-class failure.
- Preserve the distinction between observed facts, hypotheses, verified facts, and unknowns.
- Do not add a new dependency when the standard library is sufficient for benchmark infrastructure.
- Run the local test suite after substantive code changes.
- Keep provider-specific code isolated so the benchmark can compare models without coupling the product architecture to one vendor.
- Do not add hidden chain-of-thought capture or request model chain-of-thought. Store concise answers and structured outputs only.

## Current milestone

Run the same multimodal model under:
1. baseline visual Q&A
2. investigator workflow

Then inspect failures case-by-case and iterate on the workflow.

Do not start building the consumer mobile UI until benchmark evidence identifies a promising workflow.
