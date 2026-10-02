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
- Cases where the system stops too early
- Cases where the system asks for too much
- Safety failures
- Whether the workflow helps more on ambiguous or high-risk cases

## First run

Start with the eight cases whose reference images are already seeded in the repository:

- VI-01 USB-C capability boundary
- VI-02 faucet replacement
- VI-03 plumbing P-trap identification / context
- VI-04 bicycle derailleur identification
- VI-07 HVAC filter replacement requirements
- VI-11 electrical troubleshooting
- VI-16 bulb compatibility
- VI-17 power-adapter compatibility

The runner selects these cases automatically. The remaining cases are holdouts for subsequent iterations.

## Decision rules

Do not treat the first run as a final product verdict.

A strong positive signal is a material reduction in false confidence plus better targeted evidence requests, especially on ambiguous, compatibility, and troubleshooting cases.

A weak or negative signal should trigger prompt/workflow changes and another small run before considering a product pivot.

If several workflow variants fail to improve real-world resolution over baseline, narrow the product hypothesis rather than simply adding UI.

## Important

The benchmark is intended to expose failure modes, not produce a vanity score. Every low-scoring case should be inspected individually.
