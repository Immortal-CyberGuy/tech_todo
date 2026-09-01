# Simulation Report

This report captures committed scenario outputs for the SmartDialer prototype.

Generated on `2026-08-31`.

## Scenarios

| Scenario Artifact | Mode | Provider | Calls Initiated | Calls Connected | Calls Completed | Calls Failed | Peak Utilization | Safety Decisions |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| scenario-a-progressive-provider-a | progressive | provider_a | 120 | 25 | 25 | 95 | 1.00 | approve=32 |
| scenario-a-predictive-provider-a | predictive | provider_a | 120 | 25 | 24 | 95 | 1.00 | approve=32 |
| scenario-b-predictive-provider-a | predictive | provider_a | 115 | 58 | 51 | 50 | 1.00 | approve=32 |
| scenario-c-predictive-provider-a | predictive | provider_a | 73 | 47 | 39 | 22 | 1.00 | approve=36 |
| scenario-d-predictive-provider-b | predictive | provider_b | 88 | 36 | 31 | 50 | 1.00 | approve=2, reduce=32, fallback_to_progressive=4 |

## Interpretation

- Scenario `A` is the low-answer-rate case. It shows that lower answer probability permits more outbound attempts without overwhelming agents.
- Scenario `B` increases the answer rate and decreases talk time, which leads to materially more connected and completed calls.
- Scenario `C` combines high answer rate with longer talk time. Predictive pacing becomes naturally more conservative because agent capacity is consumed longer.
- Scenario `D` uses the noisy provider, outage windows, duplicates, and an agent drop. This is the main proof that the Safety Controller can reduce pacing and fall back when uncertainty rises.

## What To Open

- `docs/results/scenario-a-progressive-provider-a.json`
- `docs/results/scenario-a-predictive-provider-a.json`
- `docs/results/scenario-b-predictive-provider-a.json`
- `docs/results/scenario-c-predictive-provider-a.json`
- `docs/results/scenario-d-predictive-provider-b.json`
