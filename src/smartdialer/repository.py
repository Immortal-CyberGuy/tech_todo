from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .enums import AgentState, CallState, CampaignMode
from .models import Campaign
from .state_machine import assert_agent_transition, assert_call_transition

_UNCHANGED = object()


class _ClosingConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def __enter__(self) -> sqlite3.Connection:
        self._connection.__enter__()
        return self._connection

    def __exit__(self, exc_type, exc_value, traceback) -> bool | None:
        try:
            return self._connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self._connection.close()


class Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def connect(self) -> _ClosingConnection:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return _ClosingConnection(conn)

    def init_db(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            provider_name TEXT NOT NULL,
            target_concurrency INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            active_call_id TEXT,
            reserved_by_worker TEXT,
            reserved_at INTEGER,
            wrap_up_until INTEGER,
            last_state_change INTEGER NOT NULL,
            version INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS borrowers (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            phone TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'READY',
            active_call_id TEXT,
            last_outcome TEXT,
            next_retry_tick INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_state_change INTEGER NOT NULL,
            version INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
        );

        CREATE TABLE IF NOT EXISTS call_attempts (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            borrower_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_call_id TEXT,
            state TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            reserved_at INTEGER,
            initiated_at INTEGER,
            connected_at INTEGER,
            completed_at INTEGER,
            worker_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            last_error TEXT,
            attempt_no INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
            FOREIGN KEY(borrower_id) REFERENCES borrowers(id),
            FOREIGN KEY(agent_id) REFERENCES agents(id)
        );

        CREATE TABLE IF NOT EXISTS provider_events (
            ingest_id TEXT PRIMARY KEY,
            event_key TEXT NOT NULL,
            provider TEXT NOT NULL,
            provider_call_id TEXT NOT NULL,
            call_attempt_id TEXT,
            event_type TEXT NOT NULL,
            occurred_at INTEGER NOT NULL,
            received_at INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            duplicate INTEGER NOT NULL DEFAULT 0,
            applied INTEGER NOT NULL DEFAULT 0,
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS decision_log (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            tick INTEGER NOT NULL,
            mode TEXT NOT NULL,
            requested_calls INTEGER NOT NULL,
            approved_calls INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
        );

        CREATE INDEX IF NOT EXISTS idx_agents_state ON agents(state);
        CREATE INDEX IF NOT EXISTS idx_borrowers_campaign_active ON borrowers(campaign_id, active_call_id);
        CREATE INDEX IF NOT EXISTS idx_calls_campaign_state ON call_attempts(campaign_id, state);
        CREATE INDEX IF NOT EXISTS idx_calls_provider_call_id ON call_attempts(provider_call_id);
        CREATE INDEX IF NOT EXISTS idx_provider_events_event_key ON provider_events(event_key);
        CREATE INDEX IF NOT EXISTS idx_provider_events_received_at ON provider_events(received_at);
        CREATE INDEX IF NOT EXISTS idx_decisions_campaign_tick ON decision_log(campaign_id, tick);
        """
        with self.connect() as conn:
            conn.executescript(schema)

    def create_campaign(
        self,
        campaign_id: str,
        mode: CampaignMode | str,
        provider_name: str,
        target_concurrency: int,
        created_at: int = 0,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO campaigns (id, mode, provider_name, target_concurrency, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (campaign_id, mode.value if isinstance(mode, CampaignMode) else str(mode), provider_name, target_concurrency, created_at),
            )

    def get_campaign(self, campaign_id: str) -> Campaign:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, mode, provider_name, target_concurrency
                FROM campaigns
                WHERE id = ?
                """,
                (campaign_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown campaign: {campaign_id}")
        return Campaign(
            id=row["id"],
            mode=CampaignMode(row["mode"]),
            provider_name=row["provider_name"],
            target_concurrency=row["target_concurrency"],
        )

    def create_agents(self, agents: list[tuple[str, AgentState, int | None, int]]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO agents (id, state, wrap_up_until, last_state_change)
                VALUES (?, ?, ?, ?)
                """,
                [(agent_id, state.value, wrap_up_until, changed_at) for agent_id, state, wrap_up_until, changed_at in agents],
            )

    def create_borrowers(self, borrowers: list[tuple[str, str, str, int]]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO borrowers (id, campaign_id, phone, last_state_change)
                VALUES (?, ?, ?, ?)
                """,
                borrowers,
            )

    def get_agent(self, agent_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()

    def get_call(self, call_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM call_attempts WHERE id = ?", (call_id,)).fetchone()

    def get_borrower(self, borrower_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM borrowers WHERE id = ?", (borrower_id,)).fetchone()

    def get_call_by_provider_call_id(self, provider_call_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM call_attempts WHERE provider_call_id = ?",
                (provider_call_id,),
            ).fetchone()

    def count_near_free_agents(self, cutoff_tick: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM agents
                WHERE state = ? AND wrap_up_until IS NOT NULL AND wrap_up_until <= ?
                """,
                (AgentState.WRAP_UP.value, cutoff_tick),
            ).fetchone()
        return int(row["count"])

    def release_ready_wrap_up_agents(self, tick: int) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE agents
                SET state = ?, active_call_id = NULL, reserved_by_worker = NULL, reserved_at = NULL,
                    wrap_up_until = NULL, last_state_change = ?, version = version + 1
                WHERE state = ? AND wrap_up_until IS NOT NULL AND wrap_up_until <= ?
                """,
                (AgentState.AVAILABLE.value, tick, AgentState.WRAP_UP.value, tick),
            )
        return cursor.rowcount

    def list_candidate_agents(self, tick: int, setup_buffer_ticks: int, limit: int = 20) -> list[sqlite3.Row]:
        cutoff = tick + setup_buffer_ticks
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM agents
                WHERE state = ?
                   OR (state = ? AND wrap_up_until IS NOT NULL AND wrap_up_until <= ?)
                ORDER BY
                    CASE WHEN state = ? THEN 0 ELSE 1 END,
                    COALESCE(wrap_up_until, 0),
                    id
                LIMIT ?
                """,
                (
                    AgentState.AVAILABLE.value,
                    AgentState.WRAP_UP.value,
                    cutoff,
                    AgentState.AVAILABLE.value,
                    limit,
                ),
            ).fetchall()

    def reserve_agent(
        self,
        agent_id: str,
        call_attempt_id: str,
        worker_id: str,
        tick: int,
        setup_buffer_ticks: int,
    ) -> bool:
        cutoff = tick + setup_buffer_ticks
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE agents
                SET state = ?, active_call_id = ?, reserved_by_worker = ?, reserved_at = ?, last_state_change = ?, version = version + 1
                WHERE id = ?
                  AND (
                        state = ?
                     OR (state = ? AND wrap_up_until IS NOT NULL AND wrap_up_until <= ?)
                  )
                """,
                (
                    AgentState.RESERVED.value,
                    call_attempt_id,
                    worker_id,
                    tick,
                    tick,
                    agent_id,
                    AgentState.AVAILABLE.value,
                    AgentState.WRAP_UP.value,
                    cutoff,
                ),
            )
        return cursor.rowcount == 1

    def transition_agent(
        self,
        agent_id: str,
        new_state: AgentState,
        tick: int,
        *,
        active_call_id: str | None | object = _UNCHANGED,
        wrap_up_until: int | None | object = _UNCHANGED,
    ) -> bool:
        agent = self.get_agent(agent_id)
        if agent is None:
            return False
        current_state = AgentState(agent["state"])
        assert_agent_transition(current_state, new_state)
        next_call_id = agent["active_call_id"] if active_call_id is _UNCHANGED else active_call_id
        next_wrap_up_until = agent["wrap_up_until"] if wrap_up_until is _UNCHANGED else wrap_up_until
        reserved_by_worker = agent["reserved_by_worker"] if new_state == AgentState.RESERVED else None
        reserved_at = agent["reserved_at"] if new_state == AgentState.RESERVED else None
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE agents
                SET state = ?, active_call_id = ?, reserved_by_worker = ?, reserved_at = ?,
                    wrap_up_until = ?, last_state_change = ?, version = version + 1
                WHERE id = ? AND state = ?
                """,
                (
                    new_state.value,
                    next_call_id,
                    reserved_by_worker,
                    reserved_at,
                    next_wrap_up_until,
                    tick,
                    agent_id,
                    current_state.value,
                ),
            )
        return cursor.rowcount == 1

    def force_agent_state(
        self,
        agent_id: str,
        new_state: AgentState,
        tick: int,
        *,
        active_call_id: str | None = None,
        wrap_up_until: int | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE agents
                SET state = ?, active_call_id = ?, reserved_by_worker = NULL, reserved_at = NULL,
                    wrap_up_until = ?, last_state_change = ?, version = version + 1
                WHERE id = ?
                """,
                (new_state.value, active_call_id, wrap_up_until, tick, agent_id),
            )

    def list_available_borrowers(self, campaign_id: str, tick: int, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM borrowers
                WHERE campaign_id = ?
                  AND status = 'READY'
                  AND active_call_id IS NULL
                  AND next_retry_tick <= ?
                ORDER BY attempt_count, version, id
                LIMIT ?
                """,
                (campaign_id, tick, limit),
            ).fetchall()

    def reserve_borrower(self, borrower_id: str, call_attempt_id: str, tick: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE borrowers
                SET status = 'RESERVED', active_call_id = ?, last_state_change = ?, attempt_count = attempt_count + 1, version = version + 1
                WHERE id = ? AND status = 'READY' AND active_call_id IS NULL
                """,
                (call_attempt_id, tick, borrower_id),
            )
        return cursor.rowcount == 1

    def release_borrower(self, borrower_id: str, outcome: str, tick: int) -> None:
        terminal_outcomes = {"completed", "failed", "cancelled"}
        next_status = "DONE" if outcome in terminal_outcomes else "READY"
        next_retry_tick = tick if next_status == "DONE" else tick + 2
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE borrowers
                SET status = ?, active_call_id = NULL, last_outcome = ?, next_retry_tick = ?, last_state_change = ?, version = version + 1
                WHERE id = ?
                """,
                (next_status, outcome, next_retry_tick, tick, borrower_id),
            )

    def create_call_attempt(
        self,
        *,
        call_id: str,
        campaign_id: str,
        borrower_id: str,
        agent_id: str,
        provider: str,
        state: CallState,
        tick: int,
        worker_id: str,
        idempotency_key: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO call_attempts (
                    id, campaign_id, borrower_id, agent_id, provider, state, created_at,
                    updated_at, reserved_at, worker_id, idempotency_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    campaign_id,
                    borrower_id,
                    agent_id,
                    provider,
                    state.value,
                    tick,
                    tick,
                    tick,
                    worker_id,
                    idempotency_key,
                ),
            )

    def attach_provider_call(self, call_id: str, provider_call_id: str, tick: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE call_attempts
                SET provider_call_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (provider_call_id, tick, call_id),
            )

    def transition_call(
        self,
        call_id: str,
        new_state: CallState,
        tick: int,
        *,
        last_error: str | None = None,
    ) -> bool:
        call = self.get_call(call_id)
        if call is None:
            return False
        current_state = CallState(call["state"])
        assert_call_transition(current_state, new_state)
        initiated_at = call["initiated_at"]
        connected_at = call["connected_at"]
        completed_at = call["completed_at"]
        if new_state == CallState.INITIATED and initiated_at is None:
            initiated_at = tick
        if new_state == CallState.CONNECTED and connected_at is None:
            connected_at = tick
        if new_state in {CallState.COMPLETED, CallState.FAILED, CallState.CANCELLED} and completed_at is None:
            completed_at = tick
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE call_attempts
                SET state = ?, updated_at = ?, initiated_at = ?, connected_at = ?, completed_at = ?, last_error = COALESCE(?, last_error)
                WHERE id = ? AND state = ?
                """,
                (
                    new_state.value,
                    tick,
                    initiated_at,
                    connected_at,
                    completed_at,
                    last_error,
                    call_id,
                    current_state.value,
                ),
            )
        return cursor.rowcount == 1

    def force_call_state(
        self,
        call_id: str,
        new_state: CallState,
        tick: int,
        *,
        last_error: str | None = None,
    ) -> None:
        call = self.get_call(call_id)
        if call is None:
            return
        initiated_at = call["initiated_at"] or (tick if new_state == CallState.INITIATED else None)
        connected_at = call["connected_at"] or (tick if new_state == CallState.CONNECTED else None)
        completed_at = call["completed_at"] or (
            tick if new_state in {CallState.COMPLETED, CallState.FAILED, CallState.CANCELLED} else None
        )
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE call_attempts
                SET state = ?, updated_at = ?, initiated_at = ?, connected_at = ?, completed_at = ?, last_error = COALESCE(?, last_error)
                WHERE id = ?
                """,
                (new_state.value, tick, initiated_at, connected_at, completed_at, last_error, call_id),
            )

    def list_calls_by_states(self, states: list[CallState]) -> list[sqlite3.Row]:
        placeholders = ", ".join("?" for _ in states)
        with self.connect() as conn:
            return conn.execute(
                f"""
                SELECT *
                FROM call_attempts
                WHERE state IN ({placeholders})
                """,
                tuple(state.value for state in states),
            ).fetchall()

    def list_stale_calls(self, states: list[CallState], older_than_tick: int) -> list[sqlite3.Row]:
        placeholders = ", ".join("?" for _ in states)
        with self.connect() as conn:
            return conn.execute(
                f"""
                SELECT *
                FROM call_attempts
                WHERE state IN ({placeholders}) AND updated_at <= ?
                ORDER BY updated_at, id
                """,
                tuple(state.value for state in states) + (older_than_tick,),
            ).fetchall()

    def has_provider_event(self, event_key: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM provider_events WHERE event_key = ? AND duplicate = 0 LIMIT 1",
                (event_key,),
            ).fetchone()
        return row is not None

    def record_provider_event(
        self,
        *,
        ingest_id: str,
        event_key: str,
        provider: str,
        provider_call_id: str,
        call_attempt_id: str | None,
        event_type: str,
        occurred_at: int,
        received_at: int,
        payload: dict[str, Any],
        duplicate: bool,
        applied: bool = False,
        reason: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_events (
                    ingest_id, event_key, provider, provider_call_id, call_attempt_id, event_type,
                    occurred_at, received_at, payload_json, duplicate, applied, reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ingest_id,
                    event_key,
                    provider,
                    provider_call_id,
                    call_attempt_id,
                    event_type,
                    occurred_at,
                    received_at,
                    json.dumps(payload, sort_keys=True),
                    int(duplicate),
                    int(applied),
                    reason,
                ),
            )

    def update_provider_event_status(self, ingest_id: str, *, applied: bool, reason: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE provider_events
                SET applied = ?, reason = ?
                WHERE ingest_id = ?
                """,
                (int(applied), reason, ingest_id),
            )

    def log_decision(
        self,
        *,
        decision_id: str,
        campaign_id: str,
        tick: int,
        mode: CampaignMode,
        requested_calls: int,
        approved_calls: int,
        action: str,
        reason: str,
        metrics: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO decision_log (
                    id, campaign_id, tick, mode, requested_calls, approved_calls, action, reason, metrics_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    campaign_id,
                    tick,
                    mode.value,
                    requested_calls,
                    approved_calls,
                    action,
                    reason,
                    json.dumps(metrics, sort_keys=True),
                    tick,
                ),
            )

    def agent_state_counts(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS count FROM agents GROUP BY state"
            ).fetchall()
        counts = {state.value: 0 for state in AgentState}
        counts.update({row["state"]: int(row["count"]) for row in rows})
        return counts

    def call_state_counts(self, campaign_id: str) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT state, COUNT(*) AS count
                FROM call_attempts
                WHERE campaign_id = ?
                GROUP BY state
                """,
                (campaign_id,),
            ).fetchall()
        counts = {state.value: 0 for state in CallState}
        counts.update({row["state"]: int(row["count"]) for row in rows})
        return counts

    def count_ready_borrowers(self, campaign_id: str, tick: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM borrowers
                WHERE campaign_id = ? AND status = 'READY' AND active_call_id IS NULL AND next_retry_tick <= ?
                """,
                (campaign_id, tick),
            ).fetchone()
        return int(row["count"])

    def recent_answer_rate(self, campaign_id: str, limit: int) -> float:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT state, connected_at
                FROM call_attempts
                WHERE campaign_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (campaign_id, limit),
            ).fetchall()
        if not rows:
            return 0.35
        answered = sum(1 for row in rows if row["connected_at"] is not None)
        return answered / len(rows)

    def average_setup_ticks(self, campaign_id: str, limit: int) -> float:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT initiated_at, connected_at
                FROM call_attempts
                WHERE campaign_id = ?
                  AND initiated_at IS NOT NULL
                  AND connected_at IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (campaign_id, limit),
            ).fetchall()
        if not rows:
            return 2.0
        durations = [row["connected_at"] - row["initiated_at"] for row in rows]
        return sum(durations) / len(durations)

    def average_talk_ticks(self, campaign_id: str, limit: int) -> float:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT connected_at, completed_at
                FROM call_attempts
                WHERE campaign_id = ?
                  AND connected_at IS NOT NULL
                  AND completed_at IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (campaign_id, limit),
            ).fetchall()
        if not rows:
            return 4.0
        durations = [row["completed_at"] - row["connected_at"] for row in rows]
        return sum(durations) / len(durations)

    def count_duplicate_events_since(self, lower_tick: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM provider_events
                WHERE duplicate = 1 AND received_at >= ?
                """,
                (lower_tick,),
            ).fetchone()
        return int(row["count"])

    def get_recent_decisions(self, campaign_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM decision_log
                WHERE campaign_id = ?
                ORDER BY tick, id
                """,
                (campaign_id,),
            ).fetchall()

    def list_agents_by_state(self, state: AgentState, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM agents WHERE state = ? ORDER BY id"
        params: tuple[Any, ...] = (state.value,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (state.value, limit)
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def summary_counts(self, campaign_id: str) -> dict[str, int]:
        call_counts = self.call_state_counts(campaign_id)
        total_initiated = sum(call_counts[state.value] for state in CallState if state != CallState.QUEUED)
        return {
            "calls_initiated": total_initiated,
            "calls_connected": call_counts[CallState.CONNECTED.value] + call_counts[CallState.COMPLETED.value],
            "calls_completed": call_counts[CallState.COMPLETED.value],
            "calls_failed": call_counts[CallState.FAILED.value] + call_counts[CallState.CANCELLED.value],
        }
