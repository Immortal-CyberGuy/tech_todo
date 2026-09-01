from __future__ import annotations

import uuid

from ..config import DialerConfig
from ..enums import AgentState, CallState, ProviderEventType
from ..models import ProviderEvent
from ..repository import Repository
from ..state_machine import can_call_transition, is_terminal_call_state

EVENT_TO_CALL_STATE = {
    ProviderEventType.RINGING.value: CallState.RINGING,
    ProviderEventType.ANSWERED.value: CallState.ANSWERED,
    ProviderEventType.CONNECTED.value: CallState.CONNECTED,
    ProviderEventType.COMPLETED.value: CallState.COMPLETED,
    ProviderEventType.FAILED.value: CallState.FAILED,
    ProviderEventType.CANCELLED.value: CallState.CANCELLED,
}


class EventIngestor:
    def __init__(self, repository: Repository, config: DialerConfig) -> None:
        self.repository = repository
        self.config = config

    def process_event(self, event: ProviderEvent, received_at: int) -> str:
        ingest_id = uuid.uuid4().hex
        if self.repository.has_provider_event(event.event_key):
            self.repository.record_provider_event(
                ingest_id=ingest_id,
                event_key=event.event_key,
                provider=event.provider,
                provider_call_id=event.provider_call_id,
                call_attempt_id=event.call_attempt_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                received_at=received_at,
                payload=event.payload,
                duplicate=True,
                applied=False,
                reason="duplicate_event_key",
            )
            return "duplicate"
        self.repository.record_provider_event(
            ingest_id=ingest_id,
            event_key=event.event_key,
            provider=event.provider,
            provider_call_id=event.provider_call_id,
            call_attempt_id=event.call_attempt_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            received_at=received_at,
            payload=event.payload,
            duplicate=False,
            applied=False,
        )
        call = self.repository.get_call_by_provider_call_id(event.provider_call_id) or self.repository.get_call(event.call_attempt_id)
        if call is None:
            self.repository.update_provider_event_status(ingest_id, applied=False, reason="unknown_call")
            return "unknown_call"
        target_state = EVENT_TO_CALL_STATE[event.event_type]
        current_state = CallState(call["state"])
        if is_terminal_call_state(current_state):
            self.repository.update_provider_event_status(ingest_id, applied=False, reason="late_after_terminal")
            return "late_after_terminal"
        if not can_call_transition(current_state, target_state):
            self.repository.update_provider_event_status(ingest_id, applied=False, reason="invalid_transition")
            return "invalid_transition"
        if not self.repository.transition_call(call["id"], target_state, received_at):
            self.repository.update_provider_event_status(ingest_id, applied=False, reason="concurrent_transition_lost")
            return "concurrent_transition_lost"
        self._update_agent_for_call_event(call["agent_id"], target_state, received_at)
        if target_state in {CallState.COMPLETED, CallState.FAILED, CallState.CANCELLED}:
            self.repository.release_borrower(call["borrower_id"], target_state.value.lower(), received_at)
        self.repository.update_provider_event_status(ingest_id, applied=True, reason="applied")
        return "applied"

    def _update_agent_for_call_event(self, agent_id: str, target_state: CallState, tick: int) -> None:
        agent = self.repository.get_agent(agent_id)
        if agent is None:
            return
        current_state = AgentState(agent["state"])
        if target_state == CallState.CONNECTED and current_state != AgentState.CONNECTED:
            if current_state in {AgentState.DIALING, AgentState.RESERVED}:
                self.repository.force_agent_state(agent_id, AgentState.CONNECTED, tick, active_call_id=agent["active_call_id"])
            return
        if target_state == CallState.COMPLETED:
            next_state = AgentState.OFFLINE if current_state == AgentState.OFFLINE else AgentState.WRAP_UP
            wrap_up_until = None if next_state == AgentState.OFFLINE else tick + self.config.wrap_up_ticks
            self.repository.force_agent_state(agent_id, next_state, tick, active_call_id=None, wrap_up_until=wrap_up_until)
            return
        if target_state in {CallState.FAILED, CallState.CANCELLED}:
            next_state = AgentState.OFFLINE if current_state == AgentState.OFFLINE else AgentState.AVAILABLE
            self.repository.force_agent_state(agent_id, next_state, tick, active_call_id=None, wrap_up_until=None)

