from __future__ import annotations

from dataclasses import dataclass, field

from ..enums import CampaignMode


@dataclass(slots=True)
class Scenario:
    name: str
    description: str
    mode: CampaignMode
    provider_name: str
    ticks: int
    agent_count: int
    borrower_count: int
    target_concurrency: int
    provider_a_kwargs: dict[str, object] = field(default_factory=dict)
    provider_b_kwargs: dict[str, object] = field(default_factory=dict)
    agent_drop_events: list[tuple[int, int]] = field(default_factory=list)


def get_named_scenario(name: str, *, mode: CampaignMode | None = None, provider_name: str | None = None) -> Scenario:
    upper = name.upper()
    scenarios = {
        "A": Scenario(
            name="A",
            description="Low answer rate, moderate talk time",
            mode=CampaignMode.PREDICTIVE,
            provider_name="provider_a",
            ticks=24,
            agent_count=20,
            borrower_count=120,
            target_concurrency=20,
            provider_a_kwargs={"answer_rate": 0.20, "talk_ticks": 4, "setup_ticks": 2},
        ),
        "B": Scenario(
            name="B",
            description="Balanced answer rate, faster talk time",
            mode=CampaignMode.PREDICTIVE,
            provider_name="provider_a",
            ticks=24,
            agent_count=20,
            borrower_count=120,
            target_concurrency=20,
            provider_a_kwargs={"answer_rate": 0.50, "talk_ticks": 3, "setup_ticks": 2},
        ),
        "C": Scenario(
            name="C",
            description="High answer rate, long talk time",
            mode=CampaignMode.PREDICTIVE,
            provider_name="provider_a",
            ticks=28,
            agent_count=20,
            borrower_count=120,
            target_concurrency=20,
            provider_a_kwargs={"answer_rate": 0.70, "talk_ticks": 6, "setup_ticks": 2},
        ),
        "D": Scenario(
            name="D",
            description="Changing behavior with provider noise and agent drop",
            mode=CampaignMode.PREDICTIVE,
            provider_name="provider_b",
            ticks=30,
            agent_count=24,
            borrower_count=180,
            target_concurrency=24,
            provider_b_kwargs={
                "answer_rate_schedule": [(0, 0.55), (10, 0.25), (18, 0.65)],
                "talk_ticks_schedule": [(0, 4), (10, 3), (18, 6)],
                "outage_windows": [(12, 14)],
            },
            agent_drop_events=[(16, 8)],
        ),
    }
    if upper not in scenarios:
        raise KeyError(f"Unknown scenario {name}")
    scenario = scenarios[upper]
    if mode is not None:
        scenario.mode = mode
    if provider_name is not None:
        scenario.provider_name = provider_name
    return scenario

