from __future__ import annotations

from ..config import DialerConfig
from ..enums import CampaignMode
from ..models import PacingContext, SafetyDecision


class SafetyController:
    def __init__(self, config: DialerConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        context: PacingContext,
        desired_calls: int,
        mode: CampaignMode,
        pacing_reason: str,
    ) -> SafetyDecision:
        hard_capacity = context.available_agents + context.near_free_agents
        approved = min(desired_calls, hard_capacity, context.queued_borrowers)
        action = "approve"
        reasons = [pacing_reason]
        if mode == CampaignMode.PROGRESSIVE:
            approved = min(approved, context.available_agents)
            reasons.append("progressive hard-cap uses immediately available agents only")
        if context.provider_health < 0.45:
            approved = min(approved, context.available_agents)
            action = "fallback_to_progressive"
            reasons.append("provider health below 0.45, forcing progressive safety behavior")
        if context.previous_available_agents is not None and context.previous_available_agents > 0:
            drop_ratio = max(0.0, context.previous_available_agents - context.available_agents) / context.previous_available_agents
            if drop_ratio >= 0.30:
                approved = min(approved, context.available_agents)
                if action != "fallback_to_progressive":
                    action = "reduce" if approved > 0 else "reject"
                reasons.append(f"availability dropped sharply by {drop_ratio:.0%}")
        if context.recent_duplicate_events >= 3:
            approved = min(approved, context.available_agents + max(0, context.near_free_agents // 2))
            if action == "approve":
                action = "reduce"
            reasons.append("provider duplicates are elevated, shrinking predictive headroom")
        if desired_calls > 0 and approved == 0:
            action = "reject"
            reasons.append("no safe capacity available")
        elif approved < desired_calls and action == "approve":
            action = "reduce"
            reasons.append("safety controller trimmed aggressive pacing request")
        return SafetyDecision(
            requested_calls=desired_calls,
            approved_calls=max(0, approved),
            action=action,
            reason="; ".join(reasons),
        )
