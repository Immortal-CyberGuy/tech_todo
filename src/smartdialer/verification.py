from __future__ import annotations

import sqlite3
from pathlib import Path

from .enums import AgentState, CallState


def collect_invariant_violations(
    db_path: str | Path,
    *,
    campaign_id: str | None = None,
    expected_agent_count: int | None = None,
) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return _collect_invariant_violations_from_conn(
            conn,
            campaign_id=campaign_id,
            expected_agent_count=expected_agent_count,
        )
    finally:
        conn.close()


def _collect_invariant_violations_from_conn(
    conn: sqlite3.Connection,
    *,
    campaign_id: str | None = None,
    expected_agent_count: int | None = None,
) -> list[str]:
    violations: list[str] = []

    if expected_agent_count is not None:
        row = conn.execute("SELECT COUNT(*) AS count FROM agents").fetchone()
        if int(row["count"]) != expected_agent_count:
            violations.append(
                f"agent_count_mismatch: expected {expected_agent_count}, found {int(row['count'])}"
            )

    rows = conn.execute(
        """
        SELECT id, state, active_call_id
        FROM agents
        """
    ).fetchall()
    for row in rows:
        state = row["state"]
        has_active_call = row["active_call_id"] is not None
        if state in {
            AgentState.AVAILABLE.value,
            AgentState.WRAP_UP.value,
            AgentState.PAUSED.value,
            AgentState.OFFLINE.value,
        } and has_active_call:
            violations.append(
                f"agent_{row['id']}_state_{state}_should_not_have_active_call"
            )
        if state in {AgentState.RESERVED.value, AgentState.DIALING.value, AgentState.CONNECTED.value} and not has_active_call:
            violations.append(
                f"agent_{row['id']}_state_{state}_is_missing_active_call"
            )

    rows = conn.execute(
        """
        SELECT id, status, active_call_id
        FROM borrowers
        """
    ).fetchall()
    for row in rows:
        if row["status"] == "DONE" and row["active_call_id"] is not None:
            violations.append(f"borrower_{row['id']}_done_but_still_active")
        if row["status"] == "RESERVED" and row["active_call_id"] is None:
            violations.append(f"borrower_{row['id']}_reserved_without_call")

    live_call_states = (
        CallState.RESERVED.value,
        CallState.INITIATED.value,
        CallState.RINGING.value,
        CallState.ANSWERED.value,
        CallState.CONNECTED.value,
    )
    placeholders = ", ".join("?" for _ in live_call_states)
    campaign_filter = ""
    params: tuple[object, ...]
    if campaign_id is None:
        params = live_call_states
    else:
        campaign_filter = " AND campaign_id = ?"
        params = live_call_states + (campaign_id,)

    rows = conn.execute(
        f"""
        SELECT agent_id, COUNT(*) AS count
        FROM call_attempts
        WHERE state IN ({placeholders}){campaign_filter}
        GROUP BY agent_id
        HAVING COUNT(*) > 1
        """,
        params,
    ).fetchall()
    for row in rows:
        violations.append(
            f"agent_{row['agent_id']}_has_{int(row['count'])}_live_calls"
        )

    rows = conn.execute(
        f"""
        SELECT borrower_id, COUNT(*) AS count
        FROM call_attempts
        WHERE state IN ({placeholders}){campaign_filter}
        GROUP BY borrower_id
        HAVING COUNT(*) > 1
        """,
        params,
    ).fetchall()
    for row in rows:
        violations.append(
            f"borrower_{row['borrower_id']}_has_{int(row['count'])}_live_calls"
        )

    query = """
        SELECT id, state, initiated_at, connected_at, completed_at
        FROM call_attempts
    """
    query_params: tuple[object, ...] = ()
    if campaign_id is not None:
        query += " WHERE campaign_id = ?"
        query_params = (campaign_id,)
    rows = conn.execute(query, query_params).fetchall()
    for row in rows:
        if row["state"] in {
            CallState.INITIATED.value,
            CallState.RINGING.value,
            CallState.ANSWERED.value,
            CallState.CONNECTED.value,
            CallState.COMPLETED.value,
        } and row["initiated_at"] is None:
            violations.append(f"call_{row['id']}_missing_initiated_at_for_state_{row['state']}")
        if row["state"] == CallState.CONNECTED.value and row["connected_at"] is None:
            violations.append(f"call_{row['id']}_connected_without_connected_at")
        if row["state"] in {
            CallState.COMPLETED.value,
            CallState.FAILED.value,
            CallState.CANCELLED.value,
        } and row["completed_at"] is None:
            violations.append(f"call_{row['id']}_terminal_without_completed_at")

    rows = conn.execute(
        """
        SELECT ingest_id, duplicate, applied
        FROM provider_events
        WHERE duplicate = 1 AND applied != 0
        """
    ).fetchall()
    for row in rows:
        violations.append(
            f"provider_event_{row['ingest_id']}_duplicate_should_not_be_marked_applied"
        )

    return violations
