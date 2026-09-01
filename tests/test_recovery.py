from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smartdialer.bootstrap import build_app
from smartdialer.enums import AgentState, CallState, CampaignMode


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "recovery.sqlite3"
        self.app = build_app(db_path=self.db_path)
        self.repo = self.app.repository
        self.recovery = self.app.runner.recovery_service
        self.repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 1)
        self.repo.create_agents([("agent_1", AgentState.AVAILABLE, None, 0)])
        self.repo.create_borrowers([("borrower_1", "camp", "+1555000001", 0)])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_stale_reserved_call_is_failed_and_agent_released(self) -> None:
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
        actions = self.recovery.reconcile(5, self.app.providers)
        call = self.repo.get_call("call_1")
        agent = self.repo.get_agent("agent_1")
        borrower = self.repo.get_borrower("borrower_1")
        self.assertIn("released_stale_reservation:call_1", actions)
        self.assertEqual(call["state"], CallState.FAILED.value)
        self.assertEqual(agent["state"], AgentState.AVAILABLE.value)
        self.assertEqual(borrower["status"], "READY")


if __name__ == "__main__":
    unittest.main()

