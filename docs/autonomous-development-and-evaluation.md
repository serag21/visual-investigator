# Autonomous Development & Evaluation Workflow

**Status:** Proposed operating model, 2026-10-17  
**Goal:** Make meaningful progress between infrequent human check-ins without allowing automated agents to certify their own work.

## Product-development principle

The user's time is the scarcest resource. Agents should handle research, implementation, test execution, comparisons, documentation, and preparation of review artifacts. Human attention should be reserved for consequential product choices, genuinely ambiguous ground truth, user experience, and release/publication approvals.

Use Codex as the implementation environment where practical, with this repository as the durable source of truth. Multiple agents are useful when work can be split into independent tasks; avoid having agents edit the same files concurrently.

## Proposed agent roles

1. **Coordinator / engineering lead**
   - Reads project instructions, issues, current roadmap, latest results, and repo status.
   - Splits work into bounded tasks, assigns parallel work where safe, reconciles findings, runs final checks, and reports only decisions or blockers that genuinely need the owner.
   - Must not claim a test passed unless it was run and the result is available.

2. **Implementation agent**
   - Implements the highest-priority product or evaluation change.
   - Adds regression tests and documents assumptions.
   - Works on an isolated branch/worktree where available; never overwrites raw benchmark runs or secrets.

3. **Quality / red-team agent**
   - Independently reviews proposed changes and generated answers for unsupported claims, overconfidence, excessive hesitation, unsafe steps, incorrect compatibility, and verbosity.
   - Should receive a frozen rubric and anonymized candidate answers; should not be told which prompt version is expected to win.
   - Reports evidence and uncertainty, not just a numeric score.

4. **Market intelligence agent**
   - Periodically reviews competitor releases, store listings, representative user reviews, pricing/limits, and adjacent tools.
   - Records dated source links, sample sizes, observed complaints, counterexamples, and product implications.
   - Treats each review as an individual signal, not proof of a category-wide problem. Never use an unverified complaint as a marketing claim.

5. **Benchmark / evaluation agent**
   - Runs fixed regression cases against the current baseline and candidate.
   - Generates targeted challenge cases and summarizes per-case regressions, critical failures, response length, follow-up usefulness, provider failures, latency, and cost/usage where available.
   - Cannot independently declare ground truth for cases it generated.

## Evaluation architecture

### A. Keep three distinct test sets

- **Frozen regression set:** stable, reference-checked cases used for comparisons between versions.
- **Challenge set:** ambiguous, adversarial, incomplete-image, compatibility, safety, and concise-response tests. Add a case only when its expected behavior and evidence are documented.
- **Exploration set:** newly generated or sourced cases whose labels are not yet verified. Use these to discover failure modes, not to claim an accuracy improvement.

Generated cases should be based on real tasks, controlled transformations, or sourced reference material—not arbitrary random prompts. For each case, record the expected supported claims, unacceptable claims, minimum useful next evidence, safety boundaries, and reference/source. Mark unresolved facts explicitly.

### B. Use model-assisted grading, not self-certification

A separate judge model can score candidate answers against the case rubric and cite the exact text that supports each rating. The judge should be blind to the candidate's identity and version. Keep its rationale, confidence, and rubric version.

The judge is a triage layer, not the final authority:
- Compare automated scores with human grades on a small, recurring calibration sample.
- Human-review every flagged critical failure, low-confidence grade, judge disagreement, and new failure category.
- Track false positives and false negatives in the judge's flags.
- Never use a model's unsupported assertion as ground truth.
- Do not claim that a system improved from a judge-score increase until regressions and critical failures have been checked.

### C. Make the loop repeatable

1. Freeze a candidate prompt/configuration and record its version/hash.
2. Run the same regression cases for baseline and candidate under comparable settings.
3. Retry transient provider errors with bounded retries; report provider failures separately from answer quality.
4. Run the independent judge against anonymized outputs.
5. Compare case-level changes and identify regressions, not just the average.
6. Add new challenge cases for observed failures; verify their expected behavior before they enter the frozen set.
7. Keep raw inputs, outputs, run metadata, prompt hashes, grader results, and reports as separate versioned artifacts.
8. Promote a candidate only when it improves useful outcomes without introducing a critical failure. Require explicit human approval for release/publication or consequential external actions.

## Priorities for Visual Investigator

1. Finish a first human calibration pass on the current 24 answers, or grade a smaller balanced sample if time is limited. This is calibration data for the automated judge, not a permanent manual burden.
2. Build the machine-readable case schema and judge runner, with strict JSON output validation and an auditable score report.
3. Evaluate the judge on human-scored answers. Tune it until major disagreement types are visible and actionable.
4. Expand from the 8-case seed comparison to the existing 30-case benchmark; add repeated runs only where stochasticity could change a decision.
5. Prioritize the product behaviors competitors make valuable but hard to execute reliably: selecting the *single best next evidence request*, extracting visible specifications accurately, distinguishing diagnosis from hypothesis, and giving concise, safe, decision-ready responses.
6. Maintain the dated competitor/review watch. Use verified user complaints as inspiration for test cases; do not make competitor-comparison marketing claims without repeatable evidence.
7. Only after the core loop is useful, consider continuous scheduled evaluation. Set usage/cost ceilings, bounded retries, and a stop condition so a background run cannot loop indefinitely.

## Guardrails and owner checkpoints

Agents may research, code, run local tests, generate draft cases, grade outputs, update documentation, and open a proposed change. They must stop and surface a concise owner checkpoint when:
- Ground truth is disputed or the source image does not support a decisive label.
- A change affects safety policy, privacy, data retention, paid usage, or external publication.
- An experiment needs new paid API spend beyond an agreed cap.
- A regression affects safety, false compatibility, or a core user journey.
- A decision would commit the product to a major market positioning or claim.

Default report format: **what changed; what was tested; results; known failures; next best action; only the decision needed from the owner.** Do not ask the owner to run commands, inspect logs, or compare raw JSON unless the task genuinely requires local access or human judgment.

## Success measures

Track separately:
- Correctness and evidence grounding
- Calibration: unsupported certainty and unnecessary refusal
- Critical failure count and type
- First follow-up evidence usefulness
- Correct compatibility / replacement decisions
- Concision and time-to-useful-answer
- Resolution or successful next action when observable
- Provider reliability, retries, latency, and cost
- Automated-judge agreement with human calibration labels
- Competitor signals with source quality and sample size

An aggregate score never overrides a safety-critical or false-compatibility failure. An improvement on a small benchmark is evidence to investigate, not proof of market-wide superiority.
