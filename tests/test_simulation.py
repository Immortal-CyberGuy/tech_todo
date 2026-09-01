from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smartdialer.enums import CampaignMode
from smartdialer.simulation.runner import SimulationRunner
from smartdialer.simulation.scenarios import Scenario


class SimulationTests(unittest.TestCase):
    def test_small_noisy_scenario_runs_and_exercises_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scenario = Scenario(
                name="TINY",
                description="Small noisy scenario for test coverage",
                mode=CampaignMode.PREDICTIVE,
                provider_name="provider_b",
                ticks=8,
                agent_count=6,
                borrower_count=18,
                target_concurrency=6,
                provider_b_kwargs={"outage_windows": [(3, 4)]},
                agent_drop_events=[(5, 2)],
            )
            result = SimulationRunner(Path(temp_dir)).run(scenario)
        summary = result["summary"]
        self.assertGreater(summary["calls_initiated"], 0)
        self.assertEqual(summary["provider_name"], "provider_b")
        actions = [entry["decision"]["action"] for entry in result["tick_log"]]
        self.assertTrue(any(action != "approve" for action in actions))


if __name__ == "__main__":
    unittest.main()

