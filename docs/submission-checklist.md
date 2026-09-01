# Submission Evidence Matrix

This document maps the assignment PDF to runnable code and review evidence.

## Required Deliverables

| Requirement | Implementation or evidence | How to verify |
| --- | --- | --- |
| Working source code | `src/smartdialer/` | `python -m compileall src` |
| Local setup instructions | `README.md` | Follow “Run Locally” |
| Architecture diagram | `docs/architecture.md` | Review system, sequence, and failure-control diagrams |
| Agent state machine | `docs/state-machines.md` | Review legal states and ownership |
| Call state machine | `docs/state-machines.md` | Review legal states, terminal handling, and event ordering |
| Progressive Dialer | `pacing/progressive.py`, `services/campaign_runner.py` | Run scenario A in progressive mode |
| Predictive Pacing Engine | `pacing/predictive.py` | Run scenarios A-D and inspect decision reasons |
| Safety Controller | `pacing/safety_controller.py` | Run safety tests and scenario D |
| Mock telecom providers | `providers/base.py`, `provider_a.py`, `provider_b.py` | Run provider-event tests and scenario D |
| Tests | `tests/` | `python -m unittest discover -s tests -t . -v` |
| Basic simulation | `simulation/`, `docs/simulation-report.md` | `python scripts\run_simulation.py simulate --scenario D` |
| Basic load test | `scripts/run_load_test.py`, `docs/load-test-report.md` | Run the documented 100-agent command |
| Architecture decision document | `docs/adr.md` | Review chosen stack and explicit trade-offs |
| Final design answer | `docs/final-answer.md` | Review predictive benefits with deterministic safety |

## Integration Scope

The only required integration boundary in the PDF is telecom provision. This project implements:

| Integration | Evidence | Purpose |
| --- | --- | --- |
| Provider interface | `providers/base.py` | Keeps the dialer independent of provider internals |
| Mock Provider A | `providers/provider_a.py` | Fast and reliable baseline |
| Mock Provider B | `providers/provider_b.py` | Latency, timeouts, duplicate events, and out-of-order events |
| Provider health feedback | `services/metrics.py`, `pacing/safety_controller.py` | Reduces or falls back from predictive pacing during degradation |
| Provider event ingestion | `services/event_ingestor.py` | Deduplicates and validates state transitions |
| Provider-aware recovery | `services/recovery.py` | Reconciles stalled calls after worker failure |

Real telecom credentials, a dashboard, Redis, Kafka, RabbitMQ, PostgreSQL, and cloud deployment are intentionally outside scope. They are optional in the brief and would not improve the correctness proof of this local prototype.

## Technical Discussion Map

| Likely question | Concise answer | Evidence |
| --- | --- | --- |
| Two workers reserve one agent. What happens? | The first conditional `UPDATE` that sees an eligible state wins. Every later update affects zero rows, so the caller skips that candidate. | `repository.py::reserve_agent`, `tests/test_allocator.py` |
| Database says AVAILABLE but cache says RESERVED. Which wins? | There is no cache in this design. SQLite is the sole source of truth, deliberately avoiding split-brain state in the prototype. | `docs/adr.md`, `repository.py` |
| ANSWERED arrives, worker crashes, then COMPLETED arrives. | The event log and call state are persisted. Recovery or normal ingestion applies the terminal event idempotently; a later terminal-breaking event is ignored. | `docs/failure-walkthroughs.md`, `tests/test_recovery.py` |
| Answer rate drops from 70% to 10%. | Recent results lower the pacing proposal. The independent Safety Controller still clamps to real capacity and can fall back when health or availability deteriorates. | `pacing/predictive.py`, `pacing/safety_controller.py` |
| Why initiate 17 calls instead of 10? | The pacing reason and safety decision are persisted for every tick with the input metrics and approved count. | `repository.py::log_decision`, `docs/results/` |
| What breaks first from 1,000 to 100,000 agents? | SQLite write contention, full recovery scans, and single-process event ingestion. The first evolution is PostgreSQL, partitions, and queue-backed workers. | `docs/load-test-report.md`, `docs/adr.md` |
| Least-confident production area? | Real provider semantics and high-throughput multi-process operation. They are represented by mocks here and called out as the next production validation work. | `docs/adr.md` |
