# SmartDialer: Functional Prototype

Standalone submission for the 2026 SmartDialer assignment. It is independent of every other project in this workspace and runs locally with Python 3.12 and no third-party packages.

## Submission At A Glance

| Assignment requirement | Evidence in this submission |
| --- | --- |
| Working source code | `src/smartdialer/` |
| Setup instructions | This README |
| Architecture diagram | `docs/architecture.md` |
| Agent and call state machines | `docs/state-machines.md` |
| Progressive and predictive dialing | `src/smartdialer/pacing/` |
| Deterministic Safety Controller | `src/smartdialer/pacing/safety_controller.py` |
| Two mock telecom providers | `src/smartdialer/providers/` |
| Failure handling and recovery | `docs/failure-walkthroughs.md` |
| Automated tests | `tests/` |
| Simulation and load-test evidence | `docs/simulation-report.md`, `docs/load-test-report.md` |
| Architecture decisions | `docs/adr.md` |
| Final assignment answer | `docs/final-answer.md` |

## Design In One Minute

The pacing engine is advisory. It may propose a number of calls, but it cannot initiate one. Every call must pass through the Safety Controller and then conditional agent and borrower claims before a telecom provider is invoked. Each claim is atomic; the two-step allocation flow compensates safely when its second claim cannot be made. SQLite is the persisted source of truth; mock providers deliberately model normal and hostile event behaviour; recovery and idempotent event ingestion protect correctness after failures.

The prototype includes both dialing modes even though the brief permits either:

- Progressive mode proposes at most one call per immediately available agent.
- Predictive mode considers current availability, near-free wrap-up agents, recent answer rate, setup time, talk time, in-flight calls, and provider health.
- The Safety Controller can approve, reduce, reject, or fall back to progressive behaviour. Predictive logic has no bypass path.

## Run Locally

From this directory, with Python 3.12 available on `PATH`:

```powershell
python -m compileall src
python -m unittest discover -s tests -t . -v
```

No package installation, external service, credentials, or network connection is required.

## Run The Demonstrations

```powershell
# Basic simulation: low answer rate
python scripts\run_simulation.py simulate --scenario A

# Adverse simulation: provider noise, outage, and agent availability loss
python scripts\run_simulation.py simulate --scenario D

# Basic load test required by the brief
python scripts\run_load_test.py load-test --agents 100 --borrowers 1000 --ticks 40 --mode predictive --provider provider_b

# Full test, concurrency, simulation, and load verification pass
python scripts\run_rigorous_verification.py
```

The full verification run takes several minutes on a typical local machine. Generated evidence is committed under `docs/results/`; it can be regenerated with `python scripts\generate_submission_artifacts.py`.

## Reviewer Guide

Read these in order:

1. `docs/submission-checklist.md` for requirement-to-evidence traceability and technical-discussion prompts.
2. `docs/architecture.md` for the safety boundary, data ownership, concurrency, and scaling path.
3. `docs/state-machines.md` for legal lifecycle transitions.
4. `docs/failure-walkthroughs.md` for crash, outage, duplicate, disorder, and agent-loss handling.
5. `docs/simulation-report.md` and `docs/load-test-report.md` for execution evidence.
6. `docs/adr.md` and `docs/final-answer.md` for the trade-offs and design conclusion.

## Scope And Deliberate Omissions

The PDF requires a provider interface and at least two distinct mock providers; both are included. A real telecom API, dashboard, queue, cache, cloud deployment, and production database are not submission requirements and are intentionally excluded so the correctness-critical path remains small, inspectable, and easy to run.

SQLite is a deliberate prototype choice. It makes local persistence, atomic conditional reservations, idempotency, and crash recovery explicit. At larger scale, write contention, broad recovery scans, and single-process event ingestion are the first limits; the intended evolution is PostgreSQL, campaign partitioning, and queue-backed workers.
