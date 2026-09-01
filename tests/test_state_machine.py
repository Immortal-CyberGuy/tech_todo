from __future__ import annotations

import unittest

from smartdialer.enums import AgentState, CallState
from smartdialer.state_machine import can_agent_transition, can_call_transition


class StateMachineTests(unittest.TestCase):
    def test_agent_predictive_wrap_up_reservation_is_allowed(self) -> None:
        self.assertTrue(can_agent_transition(AgentState.WRAP_UP, AgentState.RESERVED))

    def test_agent_connected_cannot_jump_back_to_reserved(self) -> None:
        self.assertFalse(can_agent_transition(AgentState.CONNECTED, AgentState.RESERVED))

    def test_call_allows_direct_terminal_jump_for_out_of_order_provider(self) -> None:
        self.assertTrue(can_call_transition(CallState.INITIATED, CallState.COMPLETED))

    def test_call_terminal_state_rejects_late_answered(self) -> None:
        self.assertFalse(can_call_transition(CallState.COMPLETED, CallState.ANSWERED))


if __name__ == "__main__":
    unittest.main()

