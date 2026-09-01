from __future__ import annotations

from ..config import DialerConfig
from ..enums import AgentState, CallState, ProviderEventType
from ..models import ProviderEvent
from ..repository import Repository
from .event_ingestor import EventIngestor


class RecoveryService:
    def __init__(self, repository: Repository, config: DialerConfig, event_ingestor: EventIngestor) -> None:
        self.repository = repository
        self.config = config
        self.event_ingestor = event_ingestor

    def reconcile(self, tick: int, providers: dict[str, object]) -> list[str]:
        actions: list[str] = []
        for call in self.repository.list_stale_calls(
            [CallState.RESERVED],
            tick - self.config.reserve_timeout_ticks,
        ):
            agent = self.repository.get_agent(call["agent_id"])
            if agent and agent["state"] == AgentState.OFFLINE.value:
                self.repository.force_call_state(call["id"], CallState.FAILED, tick, last_error="agent_offline_while_reserved")
                self.repository.release_borrower(call["borrower_id"], "agent_offline", tick)
                actions.append(f"failed_reserved_call:{call['id']}")
                continue
            self.repository.force_call_state(call["id"], CallState.FAILED, tick, last_error="reservation_timeout")
            self.repository.force_agent_state(call["agent_id"], AgentState.AVAILABLE, tick, active_call_id=None, wrap_up_until=None)
            self.repository.release_borrower(call["borrower_id"], "reservation_timeout", tick)
            actions.append(f"released_stale_reservation:{call['id']}")
        for call in self.repository.list_stale_calls(
            [CallState.INITIATED, CallState.RINGING, CallState.ANSWERED],
            tick - self.config.call_stall_timeout_ticks,
        ):
            provider = providers.get(call["provider"])
            snapshot = None if provider is None else provider.get_call_snapshot(call["provider_call_id"])
            if snapshot is None:
                self.repository.force_call_state(call["id"], CallState.FAILED, tick, last_error="provider_state_missing")
                self.repository.force_agent_state(call["agent_id"], AgentState.AVAILABLE, tick, active_call_id=None, wrap_up_until=None)
                self.repository.release_borrower(call["borrower_id"], "provider_state_missing", tick)
                actions.append(f"failed_missing_provider_call:{call['id']}")
                continue
            if snapshot.terminal:
                event = ProviderEvent(
                    event_key=f"recovery:{snapshot.provider_call_id}:{snapshot.state}",
                    provider=call["provider"],
                    provider_call_id=snapshot.provider_call_id,
                    call_attempt_id=call["id"],
                    event_type=snapshot.state,
                    occurred_at=tick,
                    payload={"source": "recovery"},
                )
                self.event_ingestor.process_event(event, tick)
                actions.append(f"reconciled_terminal_snapshot:{call['id']}")
            elif snapshot.last_tick <= tick - self.config.call_stall_timeout_ticks:
                terminal_type = ProviderEventType.FAILED.value
                event = ProviderEvent(
                    event_key=f"recovery-timeout:{snapshot.provider_call_id}:{tick}",
                    provider=call["provider"],
                    provider_call_id=snapshot.provider_call_id,
                    call_attempt_id=call["id"],
                    event_type=terminal_type,
                    occurred_at=tick,
                    payload={"source": "recovery_timeout"},
                )
                self.event_ingestor.process_event(event, tick)
                actions.append(f"timed_out_inflight_call:{call['id']}")
        return actions

