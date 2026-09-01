# Architecture

## Overview

This prototype keeps the system intentionally simple while still making the safety boundary, recovery path, and provider behavior explicit.

- one application process
- SQLite as the local source of truth
- explicit state machines for agents and calls
- a strict safety boundary between pacing and provider initiation
- mock providers that can emit failures, duplicates, and out-of-order events

The goal is not to mimic a full telecom platform. The goal is to demonstrate correctness, safety, and recovery under the failure modes described in the assignment.

## System Architecture

```mermaid
flowchart LR
    subgraph control["Campaign Control Plane"]
        campaign["Campaign Runner<br/>tick loop per campaign"]
        metrics["Metrics Service<br/>answer rate, setup time, talk time,<br/>duplicate-event volume, provider health"]
        pacing["Pacing Engines<br/>Progressive or Predictive"]
        safety["Safety Controller<br/>approve / reduce / reject / fallback"]
        decisions["Decision Log<br/>pacing rationale + safety outcome"]
    end

    subgraph execution["Execution Plane"]
        allocator["Allocation Service<br/>conditional claims + safe compensation"]
        calls["Call Attempts<br/>explicit lifecycle"]
        agents["Agents<br/>explicit lifecycle"]
        borrowers["Borrowers<br/>retry / done ownership state"]
    end

    subgraph provider_layer["Provider Layer"]
        gateway["Provider Interface"]
        provider_a["Mock Provider A<br/>fast, reliable, low failure"]
        provider_b["Mock Provider B<br/>slower, timeouts, duplicates,<br/>out-of-order events"]
        provider_health["Provider Health Snapshot"]
    end

    subgraph consistency["Consistency + Recovery"]
        ingestor["Event Ingestor<br/>dedup + transition validation"]
        recovery["Recovery Service<br/>stale reservation + stalled call scan"]
        events["Provider Event Log"]
    end

    subgraph storage["SQLite Source of Truth"]
        repo_agents[("agents")]
        repo_borrowers[("borrowers")]
        repo_calls[("call_attempts")]
        repo_events[("provider_events")]
        repo_decisions[("decision_log")]
    end

    campaign --> metrics
    metrics --> pacing
    pacing -->|"proposed dial count"| safety
    safety -->|"approved dial count"| allocator
    safety --> decisions
    decisions --> repo_decisions

    allocator --> agents
    allocator --> borrowers
    allocator --> calls
    allocator -->|"initiate / cancel"| gateway

    gateway --> provider_a
    gateway --> provider_b
    provider_a --> provider_health
    provider_b --> provider_health
    provider_health --> metrics

    provider_a -->|"events"| ingestor
    provider_b -->|"events"| ingestor
    ingestor --> events
    events --> repo_events
    ingestor --> calls
    ingestor --> agents
    ingestor --> borrowers

    recovery --> repo_agents
    recovery --> repo_calls
    recovery --> repo_events
    recovery -->|"replayed synthetic terminal events"| ingestor

    agents --> repo_agents
    borrowers --> repo_borrowers
    calls --> repo_calls
```

## Successful Dial Sequence

```mermaid
sequenceDiagram
    participant CR as Campaign Runner
    participant MS as Metrics Service
    participant PE as Pacing Engine
    participant SC as Safety Controller
    participant AS as Allocation Service
    participant DB as SQLite
    participant TP as Telecom Provider
    participant EI as Event Ingestor
    participant RS as Recovery Service

    CR->>MS: collect current campaign metrics
    MS->>DB: read agents, calls, events, recent history
    DB-->>MS: availability + answer-rate inputs
    MS-->>CR: pacing context
    CR->>PE: propose dial count
    PE-->>CR: desired_calls + reasoning
    CR->>SC: evaluate desired_calls
    SC-->>CR: approve / reduce / reject / fallback
    CR->>AS: allocate approved calls
    AS->>DB: reserve borrower + agent atomically
    AS->>TP: initiate call attempt
    TP-->>AS: accepted / timeout
    AS->>DB: persist initiation result
    TP-->>EI: ringing / answered / connected / completed
    EI->>DB: dedup event + validate transition + mutate state
    RS->>DB: scan stale reservations / stalled calls
    RS->>EI: replay terminal recovery event when needed
```

## Design Responsibilities

- `Campaign Runner`
  - owns the tick loop for a campaign
  - gathers metrics, runs pacing, applies safety, and triggers allocation
- `Metrics Service`
  - computes the inputs used by pacing and safety decisions
  - includes provider health, duplicate-event pressure, and recent answer behavior
- `ProgressivePacingEngine`
  - proposes calls from immediately available agents only
- `PredictivePacingEngine`
  - proposes calls using current availability plus imminently free wrap-up agents
- `SafetyController`
  - is the hard boundary between pacing and provider initiation
  - clamps aggressive predictions using real capacity and provider health
- `AllocationService`
  - claims agent and borrower ownership with separate atomic conditional updates
  - compensates safely if the second claim or provider initiation fails
  - creates the call attempt and initiates the provider
- `EventIngestor`
  - persists provider events
  - rejects duplicates and invalid backward transitions
  - preserves terminal call consistency
- `RecoveryService`
  - repairs stale reservations and stalled in-flight calls
  - replays recovery events through the same ingestion logic used for normal provider events

## Why the Safety Boundary Matters

The predictive engine never talks to the provider directly. It only suggests a dial count. The Safety Controller is the only component allowed to approve or reduce that suggestion before any call is initiated.

That means:

- predictive logic cannot bypass safety
- provider health can force fallback behavior
- sudden capacity loss can stop aggressive pacing quickly

## Persistence Strategy

SQLite stores:

- campaigns
- agents
- borrowers
- call attempts
- provider events
- decision logs

Even though SQLite is not the final scale choice, it gives a deterministic and inspectable source of truth for a local prototype.

## Concurrency Strategy

Agent and borrower reservation use atomic conditional updates:

- reserve only if `state = AVAILABLE`
- or reserve wrap-up agents only if `wrap_up_until <= current_tick + setup_buffer`
- treat success only if exactly one row is updated

This prevents two workers from successfully reserving the same agent or borrower.

## Failure-Control Loops

```mermaid
flowchart TD
    provider_issue["Provider timeouts / duplicates / disorder"] --> health["Provider health score drops"]
    health --> safety_reduce["Safety Controller reduces or blocks new calls"]

    late_event["Late or out-of-order provider event"] --> ingestor_check["Event Ingestor validates transition"]
    ingestor_check --> apply["Apply safe forward transition"]
    ingestor_check --> ignore["Ignore late terminal-breaking event"]

    crash["Worker crash or stalled in-flight call"] --> reconcile["Recovery scan finds stale record"]
    reconcile --> snapshot["Use provider snapshot if available"]
    snapshot --> replay["Replay synthetic terminal event"]
    snapshot --> fail_safe["Fail safely and release ownership if state is unknown"]
```

## Failure Handling

The prototype explicitly demonstrates:

- stale reservation expiry
- worker crash recovery
- duplicate provider events
- out-of-order provider events
- provider timeout / outage degradation
- sudden agent availability drops

## Expected Scaling Bottlenecks

The first things to break at larger scale are:

- SQLite write contention
- full-table reconciliation scans
- single-process provider event ingestion

The first upgrades would be:

- PostgreSQL instead of SQLite
- queue-backed work distribution
- campaign partitioning
- dedicated event ingestion workers
