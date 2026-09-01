# Failure Walkthroughs

This document explains how the prototype behaves under the exact failure cases called out in the assignment PDF.

## 1. Worker crash after reservation and initiation

Scenario:

- an agent is reserved
- a borrower is reserved
- the call attempt is created
- the worker crashes before the call fully resolves

Relevant code:

- `src/smartdialer/services/allocator.py`
- `src/smartdialer/services/recovery.py`
- `src/smartdialer/services/event_ingestor.py`

What happens:

1. The reservation and call state are already persisted in SQLite.
2. When the system resumes, `RecoveryService` scans stale `RESERVED`, `INITIATED`, `RINGING`, and `ANSWERED` calls.
3. If the provider snapshot is terminal, recovery synthesizes the terminal event and replays it through `EventIngestor`.
4. If provider state is missing or stalled too long, the call is failed safely and the agent/borrower are released consistently.

Why the state remains safe:

- no in-memory-only reservation is trusted
- recovery works from persisted state
- event replay goes through the same idempotent transition path as normal provider events

Tests:

- `tests/test_recovery.py`
- `tests/test_assignment_integration.py::test_recovery_reconciles_stalled_answered_call_using_terminal_provider_snapshot`

## 2. Provider outage / timeout storm

Scenario:

- the provider begins timing out or enters an outage window

Relevant code:

- `src/smartdialer/providers/base.py`
- `src/smartdialer/pacing/safety_controller.py`
- `src/smartdialer/services/metrics.py`

What happens:

1. Provider initiation calls begin failing or timing out.
2. Provider health score drops based on recent timeout and failure ratios.
3. `MetricsService` feeds that health score into the pacing context.
4. `SafetyController` reduces pacing or falls back to progressive behavior.
5. New aggressive predictive dialing is suppressed until provider health improves.

Why the state remains safe:

- predictive mode cannot talk to the provider directly
- Safety Controller remains in the path even when the predictive engine wants to dial more
- failed initiations release the agent and borrower cleanly

Tests:

- `tests/test_safety_controller.py`
- `tests/test_assignment_integration.py::test_severe_provider_outage_blocks_new_calls`
- `tests/test_simulation.py`

## 3. Sudden agent availability drop

Scenario:

- many agents disappear or go offline in a short time

Relevant code:

- `src/smartdialer/services/campaign_runner.py`
- `src/smartdialer/pacing/safety_controller.py`
- `src/smartdialer/simulation/scenarios.py`

What happens:

1. The next campaign tick recalculates current agent availability.
2. `SafetyController` compares previous availability to current availability.
3. If the drop is large, it trims approvals sharply or rejects additional predictive aggression.
4. If provider health is also poor, the controller can fall back to progressive behavior.

Why the state remains safe:

- new dialing decisions are recomputed every tick
- approvals are based on current capacity, not stale forecast alone
- the controller does not let the pacing engine overrun the new lower capacity

Tests:

- `tests/test_safety_controller.py::test_reduces_when_availability_drops_sharply`
- `tests/test_simulation.py`
- `tests/test_invariants.py`

## 4. Duplicate provider events

Scenario:

- the provider sends the same logical event multiple times

Relevant code:

- `src/smartdialer/services/event_ingestor.py`
- `src/smartdialer/repository.py`

What happens:

1. The first event with a given dedup key is persisted.
2. If the same key arrives again, it is recorded as a duplicate.
3. Duplicate events are not allowed to trigger another transition.

Why the state remains safe:

- event dedup happens before transition application
- duplicates are preserved for auditability but do not produce repeated side effects

Tests:

- `tests/test_provider_events.py`
- `tests/test_assignment_integration.py::test_answered_answered_answered_completed_sequence_ends_consistently`

## 5. Out-of-order provider events

Scenario:

- the provider sends `COMPLETED` before `ANSWERED`
- or sends late `RINGING` after the call is already terminal

Relevant code:

- `src/smartdialer/state_machine.py`
- `src/smartdialer/services/event_ingestor.py`

What happens:

1. The event ingestor maps provider events to call states.
2. It checks whether the transition is valid from the current persisted state.
3. Some sensible forward jumps are allowed, such as `INITIATED -> COMPLETED`.
4. Once a call is terminal, later non-terminal events are logged but ignored.

Why the state remains safe:

- terminal states remain terminal
- impossible backward transitions are rejected
- late events do not overwrite a finished call

Tests:

- `tests/test_provider_events.py`
- `tests/test_assignment_integration.py::test_out_of_order_completed_answered_ringing_sequence_stays_terminal`

## 6. Agent disappears during setup

Scenario:

- the call was initiated, but the reserved agent goes offline during setup

Relevant code:

- `src/smartdialer/services/allocator.py`

What happens:

1. Allocation reserves the agent and borrower, then initiates the provider call.
2. If the agent transition to `DIALING` fails, the provider call is cancelled.
3. The call attempt is marked `CANCELLED` with an explicit error reason.
4. The borrower is released and can be retried later.
5. The agent remains offline instead of being incorrectly reused.

Why the state remains safe:

- call setup is not treated as successful until the agent transition succeeds
- the failure path cleans up borrower and provider state immediately

Tests:

- `tests/test_assignment_integration.py::test_agent_disappearing_during_setup_cancels_call_and_preserves_consistency`

