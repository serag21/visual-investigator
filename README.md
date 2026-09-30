# Visual Investigator

Evidence-driven visual problem solving: identify what can be supported, determine what is unknown, ask for the smallest useful next evidence, and work toward a defensible real-world outcome.

## Current stage

This repository is **validation infrastructure**, not the production app.

The first milestone is to test the core hypothesis:

> A structured visual-investigation workflow can reach trustworthy real-world outcomes more reliably than naive multimodal Q&A.

The benchmark intentionally rewards useful uncertainty. A system is not penalized for saying "I can't determine the exact part yet" when the evidence genuinely is insufficient; it is penalized for confidently inventing an answer.

## Repository layout

- `benchmark/cases.json` — 30 initial evaluation cases.
- `vi_benchmark.py` — deterministic case validation, run validation, and scoring.
- `tests/test_vi_benchmark.py` — unit tests for the harness.
- `pyproject.toml` — minimal Python project configuration.

No model API keys are required for the harness.

## Run locally

Requires Python 3.11+.

```bash
python -m pytest
python vi_benchmark.py benchmark/cases.json
```

A model/provider adapter will later emit JSONL records and can be scored with:

```bash
python -c "from vi_benchmark import main_score; raise SystemExit(main_score())" benchmark/cases.json runs/example.jsonl
```

## Evaluation dimensions

Each case is graded on a 0–2 scale for:

1. correctness
2. uncertainty handling
3. evidence gathering
4. diagnosis
5. compatibility
6. actionability
7. safety
8. efficiency

The weighted score is a useful comparison signal, not a substitute for inspecting individual failures.

## Principles

- **Observed != hypothesized != verified.**
- Ask for evidence with high information value.
- Exact compatibility requires exact evidence.
- The user's actual outcome matters more than naming the object.
- False confidence is a first-class failure.
- Keep the benchmark independent of any specific model vendor.

## Next milestone

Build the first provider adapters and run a small subset of cases end-to-end before expanding the benchmark or building the consumer UI.
