from __future__ import annotations

from ..config import DialerConfig
from ..enums import CallState
from ..models import PacingContext
from ..repository import Repository


class MetricsService:
    def __init__(self, repository: Repository, config: DialerConfig) -> None:
        self.repository = repository
        self.config = config

    def collect(
        self,
        *,
        campaign_id: str,
        provider: object,
        tick: int,
        previous_available_agents: int | None,
    ) -> PacingContext:
        agent_counts = self.repository.agent_state_counts()
        call_counts = self.repository.call_state_counts(campaign_id)
        lower_tick = max(0, tick - self.config.provider_event_window_ticks)
        provider_health = provider.health_snapshot(tick)
        return PacingContext(
            tick=tick,
            available_agents=agent_counts["AVAILABLE"],
            near_free_agents=self.repository.count_near_free_agents(tick + self.config.predictive_setup_buffer_ticks),
            reserved_agents=agent_counts["RESERVED"],
            dialing_agents=agent_counts["DIALING"],
            connected_agents=agent_counts["CONNECTED"],
            wrap_up_agents=agent_counts["WRAP_UP"],
            queued_borrowers=self.repository.count_ready_borrowers(campaign_id, tick),
            inflight_calls=(
                call_counts[CallState.INITIATED.value]
                + call_counts[CallState.RINGING.value]
                + call_counts[CallState.ANSWERED.value]
                + call_counts[CallState.CONNECTED.value]
            ),
            ringing_calls=call_counts[CallState.RINGING.value],
            answered_calls=call_counts[CallState.ANSWERED.value],
            answer_rate=self.repository.recent_answer_rate(campaign_id, self.config.recent_window_calls),
            avg_setup_ticks=self.repository.average_setup_ticks(campaign_id, self.config.recent_window_calls),
            avg_talk_ticks=self.repository.average_talk_ticks(campaign_id, self.config.recent_window_calls),
            provider_health=provider_health.score,
            recent_duplicate_events=self.repository.count_duplicate_events_since(lower_tick),
            previous_available_agents=previous_available_agents,
        )
