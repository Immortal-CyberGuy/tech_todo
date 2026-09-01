from __future__ import annotations

import unittest
from pathlib import Path

from smartdialer.config import DialerConfig
from smartdialer.enums import CampaignMode
from smartdialer.models import PacingContext
from smartdialer.pacing.safety_controller import SafetyController


class SafetyControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = SafetyController(DialerConfig(db_path=Path("test.sqlite3")))

    def test_falls_back_when_provider_health_is_low(self) -> None:
        context = PacingContext(
            tick=5,
            available_agents=4,
            near_free_agents=3,
            reserved_agents=0,
            dialing_agents=2,
            connected_agents=2,
            wrap_up_agents=3,
            queued_borrowers=50,
            inflight_calls=4,
            ringing_calls=1,
            answered_calls=0,
            answer_rate=0.5,
            avg_setup_ticks=3.0,
            avg_talk_ticks=4.0,
            provider_health=0.3,
            recent_duplicate_events=0,
            previous_available_agents=6,
        )
        decision = self.controller.evaluate(
            context=context,
            desired_calls=7,
            mode=CampaignMode.PREDICTIVE,
            pacing_reason="unit_test",
        )
        self.assertEqual(decision.action, "fallback_to_progressive")
        self.assertLessEqual(decision.approved_calls, context.available_agents)

    def test_reduces_when_availability_drops_sharply(self) -> None:
        context = PacingContext(
            tick=7,
            available_agents=3,
            near_free_agents=2,
            reserved_agents=0,
            dialing_agents=1,
            connected_agents=1,
            wrap_up_agents=2,
            queued_borrowers=20,
            inflight_calls=3,
            ringing_calls=0,
            answered_calls=0,
            answer_rate=0.25,
            avg_setup_ticks=2.0,
            avg_talk_ticks=3.0,
            provider_health=0.9,
            recent_duplicate_events=0,
            previous_available_agents=10,
        )
        decision = self.controller.evaluate(
            context=context,
            desired_calls=5,
            mode=CampaignMode.PREDICTIVE,
            pacing_reason="unit_test",
        )
        self.assertEqual(decision.action, "reduce")
        self.assertLessEqual(decision.approved_calls, context.available_agents)


if __name__ == "__main__":
    unittest.main()

