from __future__ import annotations

from ..models import PacingContext


class ProgressivePacingEngine:
    def propose(self, context: PacingContext) -> tuple[int, str]:
        proposed = min(context.available_agents, context.queued_borrowers)
        reason = (
            f"progressive mode uses immediate availability only: "
            f"available_agents={context.available_agents}, queued_borrowers={context.queued_borrowers}"
        )
        return proposed, reason

