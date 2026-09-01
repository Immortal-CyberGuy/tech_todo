# State Machines

## Agent State Machine

```mermaid
stateDiagram-v2
    [*] --> OFFLINE

    OFFLINE --> AVAILABLE: agent comes online
    OFFLINE --> PAUSED: agent is logged in but unavailable

    AVAILABLE --> RESERVED: atomic reservation succeeds
    AVAILABLE --> PAUSED: manual pause
    AVAILABLE --> OFFLINE: disconnect / logout

    RESERVED --> DIALING: provider initiation accepted
    RESERVED --> AVAILABLE: reservation expires or setup fails
    RESERVED --> OFFLINE: agent disappears during setup

    DIALING --> CONNECTED: provider CONNECTED event
    DIALING --> AVAILABLE: provider FAILED / CANCELLED before connect
    DIALING --> WRAP_UP: call ends during transition window
    DIALING --> OFFLINE: disconnect during setup

    CONNECTED --> WRAP_UP: call completes normally
    CONNECTED --> OFFLINE: disconnect during live call

    WRAP_UP --> AVAILABLE: wrap-up timer finishes
    WRAP_UP --> RESERVED: predictive pre-reserve within setup buffer
    WRAP_UP --> OFFLINE: disconnect / logout

    PAUSED --> AVAILABLE: resume
    PAUSED --> OFFLINE: disconnect / logout
```

### Agent State Intent

- `OFFLINE`
  - agent is unusable for dialing
- `AVAILABLE`
  - agent can be reserved immediately
- `RESERVED`
  - ownership has been claimed, but the call is not yet fully initiated
- `DIALING`
  - provider accepted the attempt and the call is in setup / ringing stages
- `CONNECTED`
  - borrower and agent are live on the call
- `WRAP_UP`
  - post-call cooldown before the agent becomes fully available again
- `PAUSED`
  - agent is intentionally not dialable

### Agent Design Notes

- `WRAP_UP -> RESERVED` is the key transition that allows safe predictive behavior without bypassing real capacity.
- Agents are never considered reusable just because a forecast says they should be free soon. The system requires either `AVAILABLE` or a wrap-up completion time inside the allowed setup buffer.
- Losing the agent during setup does not silently continue the call attempt. The system cancels or fails the call path and preserves consistency.

## Call State Machine

```mermaid
stateDiagram-v2
    [*] --> QUEUED

    QUEUED --> RESERVED: borrower + agent reserved
    QUEUED --> CANCELLED: campaign stop / explicit cancellation

    RESERVED --> INITIATED: provider accepts initiation
    RESERVED --> FAILED: timeout / reservation expiry / provider reject
    RESERVED --> CANCELLED: agent vanished or campaign cancelled

    INITIATED --> RINGING: provider RINGING event
    INITIATED --> ANSWERED: accepted out-of-order jump
    INITIATED --> CONNECTED: accepted out-of-order jump
    INITIATED --> COMPLETED: accepted terminal jump
    INITIATED --> FAILED: initiation stall / provider fail
    INITIATED --> CANCELLED: explicit cancel

    RINGING --> ANSWERED: provider ANSWERED event
    RINGING --> CONNECTED: accepted out-of-order jump
    RINGING --> COMPLETED: accepted terminal jump
    RINGING --> FAILED: timeout / provider fail
    RINGING --> CANCELLED: explicit cancel

    ANSWERED --> CONNECTED: provider CONNECTED event
    ANSWERED --> COMPLETED: accepted terminal jump
    ANSWERED --> FAILED: provider fail / recovery timeout
    ANSWERED --> CANCELLED: explicit cancel

    CONNECTED --> COMPLETED: provider COMPLETED event
    CONNECTED --> FAILED: abnormal termination
```

### Call State Intent

- `QUEUED`
  - logical candidate before ownership is taken
- `RESERVED`
  - borrower and agent ownership exist, but the provider has not accepted the attempt yet
- `INITIATED`
  - provider accepted the call attempt
- `RINGING`
  - phone is ringing
- `ANSWERED`
  - provider claims the borrower answered, but the agent may not be bridged yet
- `CONNECTED`
  - the borrower and agent are in the live call
- `COMPLETED`
  - successful terminal completion
- `FAILED`
  - terminal failure
- `CANCELLED`
  - terminal cancellation before or during setup

### Call Design Notes

- Direct jumps like `INITIATED -> COMPLETED` are allowed because real providers may send partial, duplicate, or out-of-order event sequences.
- Terminal states stay terminal. Late `ANSWERED` or `RINGING` events after `COMPLETED` are recorded for auditability but do not mutate the call.
- Recovery never bypasses the state machine. It synthesizes a terminal event and reuses the same ingestion path to preserve consistency rules.

## Event Ordering Rules

- The first non-duplicate event with a valid transition wins.
- Duplicate provider events are stored and marked as duplicates.
- Impossible backward transitions are rejected.
- Late events for terminal calls do not mutate state.

## State Ownership Summary

```mermaid
flowchart LR
    borrower["Borrower ownership"] --> reserved_call["Call in RESERVED / INITIATED / live state"]
    agent["Agent ownership"] --> reserved_call
    reserved_call --> terminal["Call reaches terminal state"]
    terminal --> borrower_release["Borrower released or marked done"]
    terminal --> agent_release["Agent moves to AVAILABLE, WRAP_UP, or OFFLINE"]
```

### Reviewer Takeaway

- The agent state machine protects capacity.
- The call state machine protects event consistency.
- The Safety Controller sits above both and ensures predictive behavior cannot bypass hard limits.
