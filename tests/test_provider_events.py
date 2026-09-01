from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smartdialer.bootstrap import build_app
from smartdialer.enums import AgentState, CallState, CampaignMode
from smartdialer.models import ProviderEvent


class ProviderEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "events.sqlite3"
        self.app = build_app(db_path=self.db_path)
        self.repo = self.app.repository
        self.ingestor = self.app.runner.event_ingestor
        self.repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 1)
        self.repo.create_agents([("agent_1", AgentState.AVAILABLE, None, 0)])
        self.repo.create_borrowers([("borrower_1", "camp", "+1555000001", 0)])
        self.repo.reserve_agent("agent_1", "call_1", "worker_1", 0, 0)
        self.repo.reserve_borrower("borrower_1", "call_1", 0)
        self.repo.create_call_attempt(
            call_id="call_1",
            campaign_id="camp",
            borrower_id="borrower_1",
            agent_id="agent_1",
            provider="provider_a",
            state=CallState.RESERVED,
            tick=0,
            worker_id="worker_1",
            idempotency_key="camp:borrower_1:call_1",
        )
        self.repo.attach_provider_call("call_1", "provider_a-call-1", 0)
        self.repo.transition_call("call_1", CallState.INITIATED, 0)
        self.repo.transition_agent("agent_1", AgentState.DIALING, 0, active_call_id="call_1", wrap_up_until=None)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_duplicate_and_out_of_order_events_do_not_break_terminal_state(self) -> None:
        completed = ProviderEvent(
            event_key="provider_a-call-1:COMPLETED:0",
            provider="provider_a",
            provider_call_id="provider_a-call-1",
            call_attempt_id="call_1",
            event_type="COMPLETED",
            occurred_at=3,
        )
        answered_late = ProviderEvent(
            event_key="provider_a-call-1:ANSWERED:1",
            provider="provider_a",
            provider_call_id="provider_a-call-1",
            call_attempt_id="call_1",
            event_type="ANSWERED",
            occurred_at=4,
        )
        completed_duplicate = ProviderEvent(
            event_key="provider_a-call-1:COMPLETED:0",
            provider="provider_a",
            provider_call_id="provider_a-call-1",
            call_attempt_id="call_1",
            event_type="COMPLETED",
            occurred_at=5,
        )
        self.assertEqual(self.ingestor.process_event(completed, 3), "applied")
        self.assertEqual(self.ingestor.process_event(answered_late, 4), "late_after_terminal")
        self.assertEqual(self.ingestor.process_event(completed_duplicate, 5), "duplicate")
        call = self.repo.get_call("call_1")
        agent = self.repo.get_agent("agent_1")
        borrower = self.repo.get_borrower("borrower_1")
        self.assertEqual(call["state"], CallState.COMPLETED.value)
        self.assertEqual(agent["state"], AgentState.WRAP_UP.value)
        self.assertEqual(borrower["status"], "DONE")
        with self.repo.connect() as conn:
            rows = conn.execute(
                "SELECT reason, duplicate FROM provider_events ORDER BY occurred_at, ingest_id"
            ).fetchall()
        reasons = {(row["reason"], row["duplicate"]) for row in rows}
        self.assertIn(("applied", 0), reasons)
        self.assertIn(("late_after_terminal", 0), reasons)
        self.assertIn(("duplicate_event_key", 1), reasons)


if __name__ == "__main__":
    unittest.main()

