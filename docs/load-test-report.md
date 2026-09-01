# Load Test Report

This report captures the committed basic load-test evidence required by the assignment.

Generated on `2026-08-31`.

## Primary Basic Load Test

- Command shape: `python scripts\run_load_test.py load-test --agents 100 --borrowers 1000 --ticks 40 --mode predictive --provider provider_b`
- Wall-clock time: `91.379s`
- Calls initiated: `597`
- Calls connected: `213`
- Calls completed: `194`
- Calls failed: `344`

## Test Scope

This is a deterministic local simulation, not a throughput benchmark for a production telecom platform. Its purpose is to exercise the assignment's basic load-test requirement with 100 agents, 1,000 borrowers, predictive pacing, and the noisy provider. Correctness invariants are checked by the rigorous verification run; the recorded wall-clock time is useful only as a local reference.

## Verification Load Runs

| Scenario | Provider | Ticks | Calls Initiated | Calls Connected | Calls Completed | Calls Failed | Decision Counts |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| LOAD_A | provider_a | 18 | 196 | 81 | 70 | 99 | approve=18 |
| LOAD_B | provider_b | 20 | 182 | 70 | 61 | 92 | approve=1, reduce=19 |

## What Breaks First

- At `100` agents, the prototype is still usable locally, but SQLite write contention and repeated reconciliation scans start becoming the dominant cost.
- At `1,000` agents, SQLite and single-process event ingestion become the primary bottlenecks long before business logic becomes the issue.
- At `10,000` agents, this prototype shape would not be appropriate without architectural changes. The first things to replace would be SQLite, full-table recovery scans, and the single-process execution model.

## How To Fix It

- Move from SQLite to PostgreSQL.
- Partition work by campaign.
- Separate event ingestion from pacing workers.
- Replace broad scans with queue-backed or lease-aware recovery jobs.
- Add indexed work queues and stronger operational metrics.

## Evidence Files

- `docs/results/load-basic-provider-b.json`
- `docs/results/rigorous-verification.json`
