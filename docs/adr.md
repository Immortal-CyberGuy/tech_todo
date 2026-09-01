# Architecture Decision Record

## Context

The assignment prioritizes correctness, explainability, and local reproducibility over a production-sized telecom platform. It asks for explicit concurrency handling, an unbypassable safety boundary, provider disorder handling, and a clear explanation of what the chosen architecture makes harder.

## Decision

Build a standalone Python 3.12 application using only the standard library and SQLite as the local persisted source of truth.

## Why This Stack

| Choice | Why it was chosen | What it solves | What it makes harder |
| --- | --- | --- | --- |
| Python standard library | Zero installation cost for reviewers | Fast local setup and readable business logic | Fewer production integrations out of the box |
| SQLite with WAL | A persistent, inspectable source of truth | Atomic conditional reservations, durable calls/events, crash recovery | High-write multi-process throughput |
| Single-process prototype | Keeps critical paths visible | Direct reasoning about state, safety, and failure recovery | Horizontal scale and isolation |
| Mock provider interface | Exercises telecom uncertainty without credentials | Provider independence, retries, duplicate/disordered events | Validation against a real provider contract |

## Critical Design Decisions

- The database is authoritative. The prototype deliberately has no cache, avoiding a database/cache split-brain decision.
- Reservation is conditional. An agent or borrower is claimed only if the row is still eligible at update time; a zero-row update means another worker won the race.
- Pacing is advisory. Only the Safety Controller may authorize a requested dial count, and only the allocator may invoke a provider.
- Provider events are persisted before they are applied. Deduplication and transition validation make duplicate and late events harmless.
- Recovery uses the same event-ingestion path as normal processing, so crash recovery does not have a separate, less-safe state mutation path.

## Why Not Add More Infrastructure

Redis, Kafka, RabbitMQ, PostgreSQL, microservices, a dashboard, and a real telecom provider are not required to prove the assignment's core concerns. Adding them would increase operational surface area while making reservations, state transitions, and safety behaviour harder to inspect during review.

## Limits And Production Evolution

The first bottlenecks are SQLite write contention, broad recovery scans, and single-process provider-event ingestion. A production evolution would replace SQLite with PostgreSQL, partition work by campaign, introduce durable queue-backed work and event consumers, use lease-aware recovery rather than scans, and validate the provider adapter against an actual telecom contract.
