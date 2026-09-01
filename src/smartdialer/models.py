from __future__ import annotations

from dataclasses import dataclass, field

from .enums import CampaignMode


@dataclass(slots=True)
class Campaign:
    id: str
    mode: CampaignMode
    provider_name: str
    target_concurrency: int


@dataclass(slots=True)
class PacingContext:
    tick: int
    available_agents: int
    near_free_agents: int
    reserved_agents: int
    dialing_agents: int
    connected_agents: int
    wrap_up_agents: int
    queued_borrowers: int
    inflight_calls: int
    ringing_calls: int
    answered_calls: int
    answer_rate: float
    avg_setup_ticks: float
    avg_talk_ticks: float
    provider_health: float
    recent_duplicate_events: int
    previous_available_agents: int | None = None


@dataclass(slots=True)
class SafetyDecision:
    requested_calls: int
    approved_calls: int
    action: str
    reason: str


@dataclass(slots=True)
class AllocationResult:
    requested: int
    started: int = 0
    failed: int = 0
    skipped: int = 0
    call_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProviderHealth:
    score: float
    reason: str


@dataclass(slots=True)
class ProviderEvent:
    event_key: str
    provider: str
    provider_call_id: str
    call_attempt_id: str
    event_type: str
    occurred_at: int
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SimulationSummary:
    scenario_name: str
    mode: CampaignMode
    provider_name: str
    ticks_run: int
    calls_initiated: int
    calls_connected: int
    calls_completed: int
    calls_failed: int
    peak_agent_utilization: float
    decision_breakdown: dict[str, int]
    notes: list[str] = field(default_factory=list)

