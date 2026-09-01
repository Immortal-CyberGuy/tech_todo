from __future__ import annotations

import uuid

from ..config import DialerConfig
from ..enums import AgentState, CallState
from ..models import AllocationResult, Campaign
from ..repository import Repository


class AllocationService:
    def __init__(self, repository: Repository, config: DialerConfig) -> None:
        self.repository = repository
        self.config = config

    def allocate_calls(
        self,
        *,
        campaign: Campaign,
        provider: object,
        approved_calls: int,
        tick: int,
        worker_id: str,
    ) -> AllocationResult:
        result = AllocationResult(requested=approved_calls)
        for _ in range(approved_calls):
            borrower = self._next_borrower(campaign.id, tick)
            agent = self._next_agent(tick)
            if borrower is None or agent is None:
                result.skipped += 1
                break
            call_id = uuid.uuid4().hex
            if not self.repository.reserve_agent(
                agent["id"],
                call_id,
                worker_id,
                tick,
                self.config.predictive_setup_buffer_ticks,
            ):
                result.skipped += 1
                continue
            if not self.repository.reserve_borrower(borrower["id"], call_id, tick):
                self._restore_unstarted_agent(agent, tick)
                result.skipped += 1
                continue
            idempotency_key = f"{campaign.id}:{borrower['id']}:{call_id}"
            self.repository.create_call_attempt(
                call_id=call_id,
                campaign_id=campaign.id,
                borrower_id=borrower["id"],
                agent_id=agent["id"],
                provider=campaign.provider_name,
                state=CallState.RESERVED,
                tick=tick,
                worker_id=worker_id,
                idempotency_key=idempotency_key,
            )
            initiation = provider.initiate_call(
                call_attempt_id=call_id,
                tick=tick,
                idempotency_key=idempotency_key,
            )
            if not initiation.accepted or initiation.provider_call_id is None:
                self.repository.force_call_state(call_id, CallState.FAILED, tick, last_error=initiation.reason)
                self._restore_unstarted_agent(agent, tick)
                self.repository.release_borrower(borrower["id"], "provider_failed", tick)
                result.failed += 1
                continue
            self.repository.attach_provider_call(call_id, initiation.provider_call_id, tick)
            self.repository.transition_call(call_id, CallState.INITIATED, tick)
            if not self.repository.transition_agent(
                agent["id"],
                AgentState.DIALING,
                tick,
                active_call_id=call_id,
                wrap_up_until=None,
            ):
                provider.cancel_call(initiation.provider_call_id, tick)
                self.repository.force_call_state(call_id, CallState.CANCELLED, tick, last_error="agent_disappeared_during_setup")
                self.repository.release_borrower(borrower["id"], "agent_disappeared", tick)
                result.failed += 1
                continue
            result.started += 1
            result.call_ids.append(call_id)
        return result

    def _next_borrower(self, campaign_id: str, tick: int):
        borrowers = self.repository.list_available_borrowers(campaign_id, tick, limit=1)
        return borrowers[0] if borrowers else None

    def _next_agent(self, tick: int):
        agents = self.repository.list_candidate_agents(
            tick,
            self.config.predictive_setup_buffer_ticks,
            limit=1,
        )
        return agents[0] if agents else None

    def _restore_unstarted_agent(self, agent, tick: int) -> None:
        original_state = AgentState(agent["state"])
        next_state = AgentState.AVAILABLE if original_state == AgentState.AVAILABLE else AgentState.WRAP_UP
        wrap_up_until = None if next_state == AgentState.AVAILABLE else agent["wrap_up_until"]
        self.repository.force_agent_state(
            agent["id"],
            next_state,
            tick,
            active_call_id=None,
            wrap_up_until=wrap_up_until,
        )
