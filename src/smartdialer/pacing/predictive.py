from __future__ import annotations

from ..models import PacingContext


class PredictivePacingEngine:
    def propose(self, context: PacingContext) -> tuple[int, str]:
        safe_capacity = context.available_agents + context.near_free_agents
        expected_answer_rate = min(0.9, max(0.1, context.answer_rate))
        setup_factor = min(1.5, max(0.75, context.avg_setup_ticks / 2.0))
        talk_penalty = 1.0 if context.avg_talk_ticks <= 4 else min(2.0, context.avg_talk_ticks / 4.0)
        inflight_penalty = int(round(context.inflight_calls * expected_answer_rate / setup_factor))
        health_adjusted_capacity = int(round(safe_capacity * context.provider_health))
        proposed = health_adjusted_capacity - inflight_penalty
        if context.provider_health > 0.7 and context.answer_rate < 0.55:
            proposed += max(0, context.near_free_agents // 2)
        proposed = max(0, min(proposed, context.queued_borrowers))
        proposed = int(max(0, proposed / talk_penalty))
        reason = (
            "predictive mode considered available_agents={available}, near_free_agents={near_free}, "
            "answer_rate={answer_rate:.2f}, inflight_calls={inflight}, avg_setup_ticks={setup:.2f}, "
            "avg_talk_ticks={talk:.2f}, provider_health={health:.2f}"
        ).format(
            available=context.available_agents,
            near_free=context.near_free_agents,
            answer_rate=context.answer_rate,
            inflight=context.inflight_calls,
            setup=context.avg_setup_ticks,
            talk=context.avg_talk_ticks,
            health=context.provider_health,
        )
        return proposed, reason

