# Experiment v0.1

## Question

Does an explicit evidence-driven investigation workflow improve real-world resolution versus ordinary multimodal question answering?

## Controlled comparison

Run the same multimodal model on the same case and image set under two conditions:

- **Baseline:** ordinary user question with minimal instruction.
- **Investigator:** the workflow in prompts/investigator-v0.1.md.

Keep model, image, temperature/configuration, and tool access constant where possible.

## What we will compare

Primary:
- Correctness
- False-confidence rate
- Quality of next-evidence requests
- Exact compatibility / replacement safety
- Real-world actionability

Secondary:
- Response length
- Number of unnecessary follow-ups
- Cases where the system stops too early
- Cases where the system asks for too much
- Safety failures
- Whether the workflow helps more on hard cases than easy cases

## First run

Start with 8 high-information cases rather than all 30:

- VI-01 USB-C capability boundary
- VI-02 faucet replacement
- VI-08 faucet cartridge exact replacement
- VI-11 electrical troubleshooting
- VI-14 laptop charging diagnosis
- VI-17 power-adapter compatibility
- VI-21 deliberate ambiguity
- VI-29 outcome-first replacement

The remaining cases become holdout cases after the first prompt iteration.

## Decision rules

Do not treat the first run as a final product verdict.

A strong positive signal is a material reduction in false confidence plus better targeted evidence requests, especially on hard/ambiguous cases.

A weak or negative signal should trigger prompt/workflow changes and another small run before considering a product pivot.

If several workflow variants fail to improve real-world resolution over baseline, narrow the product hypothesis rather than simply adding UI.

## Important

The benchmark is intended to expose failure modes, not produce a vanity score. Every low-scoring case should be inspected individually.
