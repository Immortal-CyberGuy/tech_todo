from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smartdialer.bootstrap import build_app
from smartdialer.enums import AgentState, CallState, CampaignMode
from smartdialer.models import ProviderEvent
from smartdialer.providers.base import ProviderCallSnapshot
from smartdialer.verification import collect_invariant_violations


class AssignmentIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "integration.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_progressive_mode_never_exceeds_immediate_agent_capacity(self) -> None:
        app = build_app(db_path=self.db_path)
        repo = app.repository
        repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 5)
        repo.create_agents([(f"agent_{index}", AgentState.AVAILABLE, None, 0) for index in range(5)])
        repo.create_borrowers([(f"borrower_{index}", "camp", f"+155500{index:04d}", 0) for index in range(20)])
        tick_result = app.runner.run_tick("camp", 0, "worker_1")
        live_counts = repo.call_state_counts("camp")
        live_calls = sum(
            live_counts[state.value]
            for state in [CallState.RESERVED, CallState.INITIATED, CallState.RINGING, CallState.ANSWERED, CallState.CONNECTED]
        )
        self.assertLessEqual(tick_result["decision"].approved_calls, 5)
        self.assertLessEqual(live_calls, 5)
        self.assertEqual(collect_invariant_violations(self.db_path, campaign_id="camp", expected_agent_count=5), [])

    def test_severe_provider_outage_blocks_new_calls(self) -> None:
        app = build_app(db_path=self.db_path, provider_b_kwargs={"outage_windows": [(1, 3)]})
        repo = app.repository
        repo.create_campaign("camp", CampaignMode.PREDICTIVE, "provider_b", 8)
        repo.create_agents([(f"agent_{index}", AgentState.AVAILABLE, None, 0) for index in range(8)])
        repo.create_borrowers([(f"borrower_{index}", "camp", f"+155500{index:04d}", 0) for index in range(30)])
        tick0 = app.runner.run_tick("camp", 0, "worker_1")
        tick1 = app.runner.run_tick("camp", 1, "worker_2")
        tick2 = app.runner.run_tick("camp", 2, "worker_3")
        self.assertGreaterEqual(tick0["allocation"].started + tick0["allocation"].failed, 1)
        self.assertEqual(tick1["decision"].approved_calls, 0)
        self.assertEqual(tick2["decision"].approved_calls, 0)
        self.assertIn(tick1["decision"].action, {"reject", "fallback_to_progressive"})
        self.assertIn(tick2["decision"].action, {"reject", "fallback_to_progressive"})

    def test_answered_answered_answered_completed_sequence_ends_consistently(self) -> None:
        app = build_app(db_path=self.db_path)
        repo = app.repository
        ingestor = app.runner.event_ingestor
        repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 1)
        repo.create_agents([("agent_1", AgentState.AVAILABLE, None, 0)])
        repo.create_borrowers([("borrower_1", "camp", "+1555000001", 0)])
        repo.reserve_agent("agent_1", "call_1", "worker_1", 0, 0)
        repo.reserve_borrower("borrower_1", "call_1", 0)
        repo.create_call_attempt(
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
        repo.attach_provider_call("call_1", "provider_a-call-1", 0)
        repo.transition_call("call_1", CallState.INITIATED, 0)
        repo.transition_agent("agent_1", AgentState.DIALING, 0, active_call_id="call_1", wrap_up_until=None)
        for index in range(3):
            status = ingestor.process_event(
                ProviderEvent(
                    event_key=f"provider_a-call-1:ANSWERED:{index}",
                    provider="provider_a",
                    provider_call_id="provider_a-call-1",
                    call_attempt_id="call_1",
                    event_type="ANSWERED",
                    occurred_at=index + 1,
                ),
                index + 1,
            )
            self.assertEqual(status, "applied")
        status = ingestor.process_event(
            ProviderEvent(
                event_key="provider_a-call-1:COMPLETED:99",
                provider="provider_a",
                provider_call_id="provider_a-call-1",
                call_attempt_id="call_1",
                event_type="COMPLETED",
                occurred_at=5,
            ),
            5,
        )
        self.assertEqual(status, "applied")
        call = repo.get_call("call_1")
        agent = repo.get_agent("agent_1")
        borrower = repo.get_borrower("borrower_1")
        self.assertEqual(call["state"], CallState.COMPLETED.value)
        self.assertEqual(agent["state"], AgentState.WRAP_UP.value)
        self.assertEqual(borrower["status"], "DONE")
        self.assertEqual(collect_invariant_violations(self.db_path, campaign_id="camp", expected_agent_count=1), [])

    def test_out_of_order_completed_answered_ringing_sequence_stays_terminal(self) -> None:
        app = build_app(db_path=self.db_path)
        repo = app.repository
        ingestor = app.runner.event_ingestor
        repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 1)
        repo.create_agents([("agent_1", AgentState.AVAILABLE, None, 0)])
        repo.create_borrowers([("borrower_1", "camp", "+1555000001", 0)])
        repo.reserve_agent("agent_1", "call_1", "worker_1", 0, 0)
        repo.reserve_borrower("borrower_1", "call_1", 0)
        repo.create_call_attempt(
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
        repo.attach_provider_call("call_1", "provider_a-call-1", 0)
        repo.transition_call("call_1", CallState.INITIATED, 0)
        repo.transition_agent("agent_1", AgentState.DIALING, 0, active_call_id="call_1", wrap_up_until=None)
        completed = ingestor.process_event(
            ProviderEvent(
                event_key="provider_a-call-1:COMPLETED:1",
                provider="provider_a",
                provider_call_id="provider_a-call-1",
                call_attempt_id="call_1",
                event_type="COMPLETED",
                occurred_at=2,
            ),
            2,
        )
        answered = ingestor.process_event(
            ProviderEvent(
                event_key="provider_a-call-1:ANSWERED:2",
                provider="provider_a",
                provider_call_id="provider_a-call-1",
                call_attempt_id="call_1",
                event_type="ANSWERED",
                occurred_at=3,
            ),
            3,
        )
        ringing = ingestor.process_event(
            ProviderEvent(
                event_key="provider_a-call-1:RINGING:3",
                provider="provider_a",
                provider_call_id="provider_a-call-1",
                call_attempt_id="call_1",
                event_type="RINGING",
                occurred_at=4,
            ),
            4,
        )
        self.assertEqual(completed, "applied")
        self.assertEqual(answered, "late_after_terminal")
        self.assertEqual(ringing, "late_after_terminal")
        self.assertEqual(repo.get_call("call_1")["state"], CallState.COMPLETED.value)

    def test_recovery_reconciles_stalled_answered_call_using_terminal_provider_snapshot(self) -> None:
        app = build_app(db_path=self.db_path)
        repo = app.repository
        provider = app.providers["provider_a"]
        recovery = app.runner.recovery_service
        ingestor = app.runner.event_ingestor
        repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 1)
        repo.create_agents([("agent_1", AgentState.AVAILABLE, None, 0)])
        repo.create_borrowers([("borrower_1", "camp", "+1555000001", 0)])
        repo.reserve_agent("agent_1", "call_1", "worker_1", 0, 0)
        repo.reserve_borrower("borrower_1", "call_1", 0)
        repo.create_call_attempt(
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
        repo.attach_provider_call("call_1", "provider_a-call-1", 0)
        repo.transition_call("call_1", CallState.INITIATED, 0)
        repo.transition_agent("agent_1", AgentState.DIALING, 0, active_call_id="call_1", wrap_up_until=None)
        ingestor.process_event(
            ProviderEvent(
                event_key="provider_a-call-1:ANSWERED:1",
                provider="provider_a",
                provider_call_id="provider_a-call-1",
                call_attempt_id="call_1",
                event_type="ANSWERED",
                occurred_at=1,
            ),
            1,
        )
        if provider.get_call_snapshot("provider_a-call-1") is None:
            provider.snapshots["provider_a-call-1"] = ProviderCallSnapshot(
                provider_call_id="provider_a-call-1",
                state="COMPLETED",
                terminal=True,
                last_tick=10,
            )
        else:
            snapshot = provider.snapshots["provider_a-call-1"]
            snapshot.state = "COMPLETED"
            snapshot.terminal = True
            snapshot.last_tick = 10
        actions = recovery.reconcile(10, app.providers)
        call = repo.get_call("call_1")
        self.assertIn("reconciled_terminal_snapshot:call_1", actions)
        self.assertEqual(call["state"], CallState.COMPLETED.value)
        self.assertEqual(repo.get_borrower("borrower_1")["status"], "DONE")
        self.assertEqual(collect_invariant_violations(self.db_path, campaign_id="camp", expected_agent_count=1), [])

    def test_agent_disappearing_during_setup_cancels_call_and_preserves_consistency(self) -> None:
        app = build_app(db_path=self.db_path)
        repo = app.repository
        allocator = app.runner.allocator
        campaign = None
        repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 1)
        campaign = repo.get_campaign("camp")
        repo.create_agents([("agent_1", AgentState.AVAILABLE, None, 0)])
        repo.create_borrowers([("borrower_1", "camp", "+1555000001", 0)])

        def disappear(*args, **kwargs) -> bool:
            repo.force_agent_state("agent_1", AgentState.OFFLINE, 0, active_call_id=None, wrap_up_until=None)
            return False

        with patch.object(repo, "transition_agent", side_effect=disappear):
            result = allocator.allocate_calls(
                campaign=campaign,
                provider=app.providers["provider_a"],
                approved_calls=1,
                tick=0,
                worker_id="worker_1",
            )
        self.assertEqual(result.failed, 1)
        call = repo.list_calls_by_states([CallState.CANCELLED])[0]
        borrower = repo.get_borrower("borrower_1")
        agent = repo.get_agent("agent_1")
        self.assertEqual(call["last_error"], "agent_disappeared_during_setup")
        self.assertEqual(borrower["status"], "READY")
        self.assertEqual(agent["state"], AgentState.OFFLINE.value)
        self.assertEqual(collect_invariant_violations(self.db_path, campaign_id="camp", expected_agent_count=1), [])


if __name__ == "__main__":
    unittest.main()
