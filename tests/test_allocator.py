from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from smartdialer.bootstrap import build_app
from smartdialer.enums import AgentState, CampaignMode


class AllocationRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "allocator.sqlite3"
        self.app = build_app(db_path=self.db_path)
        self.repo = self.app.repository
        self.repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 1)
        self.repo.create_agents([("agent_1", AgentState.AVAILABLE, None, 0)])
        self.repo.create_borrowers([("borrower_1", "camp", "+1555000001", 0)])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_only_one_worker_can_reserve_same_agent(self) -> None:
        barrier = threading.Barrier(2)
        results: list[bool] = []

        def reserve(call_id: str) -> None:
            barrier.wait()
            results.append(self.repo.reserve_agent("agent_1", call_id, call_id, 0, 0))

        threads = [
            threading.Thread(target=reserve, args=("call_a",)),
            threading.Thread(target=reserve, args=("call_b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(True), 1)

    def test_only_one_worker_can_reserve_same_borrower(self) -> None:
        barrier = threading.Barrier(2)
        results: list[bool] = []

        def reserve(call_id: str) -> None:
            barrier.wait()
            results.append(self.repo.reserve_borrower("borrower_1", call_id, 0))

        threads = [
            threading.Thread(target=reserve, args=("call_a",)),
            threading.Thread(target=reserve, args=("call_b",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(True), 1)


if __name__ == "__main__":
    unittest.main()

