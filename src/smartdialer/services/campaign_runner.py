from __future__ import annotations

import uuid
from dataclasses import asdict

from ..enums import CampaignMode
from ..repository import Repository
from ..services.allocator import AllocationService
from ..services.event_ingestor import EventIngestor
from ..services.metrics import MetricsService
from ..services.recovery import RecoveryService


class CampaignRunner:
    def __init__(
        self,
        *,
        repository: Repository,
        progressive_engine: object,
        predictive_engine: object,
        safety_controller: object,
        allocator: AllocationService,
        metrics_service: MetricsService,
        event_ingestor: EventIngestor,
        recovery_service: RecoveryService,
        providers: dict[str, object],
    ) -> None:
        self.repository = repository
        self.progressive_engine = progressive_engine
        self.predictive_engine = predictive_engine
        self.safety_controller = safety_controller
        self.allocator = allocator
        self.metrics_service = metrics_service
        self.event_ingestor = event_ingestor
        self.recovery_service = recovery_service
        self.providers = providers
        self.previous_available_agents: dict[str, int] = {}

    def run_tick(self, campaign_id: str, tick: int, worker_id: str) -> dict[str, object]:
        campaign = self.repository.get_campaign(campaign_id)
        provider = self.providers[campaign.provider_name]
        self.repository.release_ready_wrap_up_agents(tick)
        ingested = [self.event_ingestor.process_event(event, tick) for event in provider.drain_events(tick)]
        recovery_actions = self.recovery_service.reconcile(tick, self.providers)
        context = self.metrics_service.collect(
            campaign_id=campaign_id,
            provider=provider,
            tick=tick,
            previous_available_agents=self.previous_available_agents.get(campaign_id),
        )
        if campaign.mode == CampaignMode.PROGRESSIVE:
            desired_calls, pacing_reason = self.progressive_engine.propose(context)
        else:
            desired_calls, pacing_reason = self.predictive_engine.propose(context)
        decision = self.safety_controller.evaluate(
            context=context,
            desired_calls=desired_calls,
            mode=campaign.mode,
            pacing_reason=pacing_reason,
        )
        self.repository.log_decision(
            decision_id=uuid.uuid4().hex,
            campaign_id=campaign_id,
            tick=tick,
            mode=campaign.mode,
            requested_calls=decision.requested_calls,
            approved_calls=decision.approved_calls,
            action=decision.action,
            reason=decision.reason,
            metrics=asdict(context),
        )
        allocation = self.allocator.allocate_calls(
            campaign=campaign,
            provider=provider,
            approved_calls=decision.approved_calls,
            tick=tick,
            worker_id=worker_id,
        )
        self.previous_available_agents[campaign_id] = self.repository.agent_state_counts()["AVAILABLE"]
        return {
            "campaign_id": campaign_id,
            "tick": tick,
            "mode": campaign.mode.value,
            "decision": decision,
            "allocation": allocation,
            "ingested_events": ingested,
            "recovery_actions": recovery_actions,
        }

