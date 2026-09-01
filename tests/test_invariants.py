from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from smartdialer.enums import CampaignMode
from smartdialer.simulation.runner import SimulationRunner
from smartdialer.simulation.scenarios import get_named_scenario
from smartdialer.verification import collect_invariant_violations


class InvariantScenarioTests(unittest.TestCase):
    def test_named_scenarios_preserve_database_invariants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runner = SimulationRunner(root)
            combinations = [
                ("A", CampaignMode.PROGRESSIVE, "provider_a"),
                ("A", CampaignMode.PREDICTIVE, "provider_a"),
                ("D", CampaignMode.PREDICTIVE, "provider_b"),
            ]
            for scenario_name, mode, provider_name in combinations:
                scenario = get_named_scenario(scenario_name, mode=mode, provider_name=provider_name)
                result = runner.run(scenario)
                campaign_id = f"campaign_{scenario.name.lower()}"
                violations = collect_invariant_violations(
                    result["db_path"],
                    campaign_id=campaign_id,
                    expected_agent_count=scenario.agent_count,
                )
                self.assertEqual(violations, [], msg=f"{scenario_name}/{mode.value}/{provider_name}: {violations}")


if __name__ == "__main__":
    unittest.main()

