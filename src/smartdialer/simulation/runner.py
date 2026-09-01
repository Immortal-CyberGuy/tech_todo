from __future__ import annotations

import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from ..bootstrap import build_app
from ..enums import AgentState, CampaignMode
from ..models import SimulationSummary
from ..repository import Repository
from .scenarios import Scenario


class SimulationRunner:
    def __init__(self, root: Path) -> None:
        self.root = root

    def run(self, scenario: Scenario) -> dict[str, object]:
        db_path = Path(tempfile.gettempdir()) / f"smartdialer_{scenario.name.lower()}_{int(time.time() * 1000)}.sqlite3"
        app = build_app(
            db_path=db_path,
            provider_a_kwargs=scenario.provider_a_kwargs,
            provider_b_kwargs=scenario.provider_b_kwargs,
        )
        repository = app.repository
        campaign_id = f"campaign_{scenario.name.lower()}"
        repository.create_campaign(
            campaign_id,
            scenario.mode,
            scenario.provider_name,
            scenario.target_concurrency,
            created_at=0,
        )
        repository.create_agents(
            [
                (f"agent_{index:03d}", AgentState.AVAILABLE, None, 0)
                for index in range(scenario.agent_count)
            ]
        )
        repository.create_borrowers(
            [
                (f"borrower_{index:04d}", campaign_id, f"+155500{index:04d}", 0)
                for index in range(scenario.borrower_count)
            ]
        )
        tick_log: list[dict[str, object]] = []
        peak_utilization = 0.0
        for tick in range(scenario.ticks):
            self._apply_agent_drop(repository, scenario, tick)
            tick_result = app.runner.run_tick(campaign_id, tick, worker_id=f"worker_{tick % 3}")
            counts = repository.agent_state_counts()
            total_agents = max(1, scenario.agent_count)
            utilization = (counts["RESERVED"] + counts["DIALING"] + counts["CONNECTED"] + counts["WRAP_UP"]) / total_agents
            peak_utilization = max(peak_utilization, utilization)
            tick_log.append(
                {
                    "tick": tick,
                    "available_agents": counts["AVAILABLE"],
                    "connected_agents": counts["CONNECTED"],
                    "decision": asdict(tick_result["decision"]),
                    "allocation": asdict(tick_result["allocation"]),
                }
            )
        for drain_tick in range(scenario.ticks, scenario.ticks + 8):
            app.runner.run_tick(campaign_id, drain_tick, worker_id="drain_worker")
        summary_counts = repository.summary_counts(campaign_id)
        decision_rows = repository.get_recent_decisions(campaign_id)
        decision_breakdown: dict[str, int] = {}
        for row in decision_rows:
            decision_breakdown[row["action"]] = decision_breakdown.get(row["action"], 0) + 1
        summary = SimulationSummary(
            scenario_name=scenario.name,
            mode=scenario.mode,
            provider_name=scenario.provider_name,
            ticks_run=scenario.ticks,
            calls_initiated=summary_counts["calls_initiated"],
            calls_connected=summary_counts["calls_connected"],
            calls_completed=summary_counts["calls_completed"],
            calls_failed=summary_counts["calls_failed"],
            peak_agent_utilization=peak_utilization,
            decision_breakdown=decision_breakdown,
            notes=[scenario.description],
        )
        return {
            "summary": asdict(summary),
            "tick_log": tick_log,
            "db_path": str(db_path),
        }

    def _apply_agent_drop(self, repository: Repository, scenario: Scenario, tick: int) -> None:
        for event_tick, count in scenario.agent_drop_events:
            if event_tick != tick:
                continue
            agents = repository.list_agents_by_state(AgentState.AVAILABLE, limit=count)
            for agent in agents:
                repository.force_agent_state(agent["id"], AgentState.OFFLINE, tick)


def run_load_test(
    *,
    root: Path,
    agent_count: int,
    borrower_count: int,
    ticks: int,
    mode: CampaignMode,
    provider_name: str,
) -> dict[str, object]:
    scenario = Scenario(
        name="LOAD",
        description="Basic load-test harness",
        mode=mode,
        provider_name=provider_name,
        ticks=ticks,
        agent_count=agent_count,
        borrower_count=borrower_count,
        target_concurrency=agent_count,
    )
    started = time.perf_counter()
    result = SimulationRunner(root).run(scenario)
    duration = time.perf_counter() - started
    result["load_test"] = {
        "agent_count": agent_count,
        "borrower_count": borrower_count,
        "ticks": ticks,
        "wall_clock_seconds": round(duration, 3),
        "note": "SQLite is expected to be the first bottleneck under larger write-heavy runs.",
    }
    return result

