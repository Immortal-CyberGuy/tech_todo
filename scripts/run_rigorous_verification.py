from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from smartdialer.bootstrap import build_app
from smartdialer.enums import AgentState, CampaignMode
from smartdialer.providers.base import ProviderCallSnapshot
from smartdialer.simulation.scenarios import Scenario, get_named_scenario
from smartdialer.verification import collect_invariant_violations


def run_unittest_suite() -> dict[str, object]:
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "successful": result.wasSuccessful(),
    }


def run_concurrency_stress(iterations: int = 30, contenders: int = 6) -> dict[str, object]:
    started = time.perf_counter()
    for index in range(iterations):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / f"race_{index}.sqlite3"
            app = build_app(db_path=db_path)
            repo = app.repository
            repo.create_campaign("camp", CampaignMode.PROGRESSIVE, "provider_a", 1)
            repo.create_agents([("agent_1", AgentState.AVAILABLE, None, 0)])
            repo.create_borrowers([("borrower_1", "camp", "+1555000001", 0)])
            agent_results: list[bool] = []
            borrower_results: list[bool] = []
            barrier = threading.Barrier(contenders)

            def race_agent(call_id: str) -> None:
                barrier.wait()
                agent_results.append(repo.reserve_agent("agent_1", call_id, call_id, 0, 0))

            threads = [threading.Thread(target=race_agent, args=(f"call_{n}",)) for n in range(contenders)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            if agent_results.count(True) != 1:
                raise AssertionError(f"agent race iteration {index} had winners={agent_results.count(True)}")

            repo.force_agent_state("agent_1", AgentState.AVAILABLE, 0, active_call_id=None, wrap_up_until=None)
            barrier = threading.Barrier(contenders)

            def race_borrower(call_id: str) -> None:
                barrier.wait()
                borrower_results.append(repo.reserve_borrower("borrower_1", call_id, 0))

            threads = [threading.Thread(target=race_borrower, args=(f"call_{n}",)) for n in range(contenders)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            if borrower_results.count(True) != 1:
                raise AssertionError(f"borrower race iteration {index} had winners={borrower_results.count(True)}")
    return {
        "iterations": iterations,
        "contenders": contenders,
        "wall_clock_seconds": round(time.perf_counter() - started, 3),
    }


def seed_and_run_verified_scenario(scenario: Scenario) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / f"{scenario.name.lower()}_{scenario.mode.value}_{scenario.provider_name}.sqlite3"
        app = build_app(
            db_path=db_path,
            provider_a_kwargs=scenario.provider_a_kwargs,
            provider_b_kwargs=scenario.provider_b_kwargs,
        )
        repo = app.repository
        campaign_id = f"campaign_{scenario.name.lower()}"
        repo.create_campaign(
            campaign_id,
            scenario.mode,
            scenario.provider_name,
            scenario.target_concurrency,
            created_at=0,
        )
        repo.create_agents(
            [(f"agent_{index:03d}", AgentState.AVAILABLE, None, 0) for index in range(scenario.agent_count)]
        )
        repo.create_borrowers(
            [(f"borrower_{index:04d}", campaign_id, f"+155500{index:04d}", 0) for index in range(scenario.borrower_count)]
        )
        decision_counts: dict[str, int] = {}
        safety_events: list[str] = []
        for tick in range(scenario.ticks):
            apply_agent_drop(repo, scenario, tick)
            tick_result = app.runner.run_tick(campaign_id, tick, worker_id=f"worker_{tick % 4}")
            action = tick_result["decision"].action
            decision_counts[action] = decision_counts.get(action, 0) + 1
            if action != "approve":
                safety_events.append(f"tick={tick}:{action}")
            violations = collect_invariant_violations(
                db_path,
                campaign_id=campaign_id,
                expected_agent_count=scenario.agent_count,
            )
            if violations:
                raise AssertionError(
                    f"invariant violations during {scenario.name}/{scenario.mode.value}/{scenario.provider_name} at tick {tick}: {violations}"
                )
        for tick in range(scenario.ticks, scenario.ticks + 10):
            app.runner.run_tick(campaign_id, tick, worker_id="drain_worker")
            violations = collect_invariant_violations(
                db_path,
                campaign_id=campaign_id,
                expected_agent_count=scenario.agent_count,
            )
            if violations:
                raise AssertionError(
                    f"invariant violations during drain of {scenario.name}/{scenario.mode.value}/{scenario.provider_name} at tick {tick}: {violations}"
                )
        summary = repo.summary_counts(campaign_id)
        final_violations = collect_invariant_violations(
            db_path,
            campaign_id=campaign_id,
            expected_agent_count=scenario.agent_count,
        )
        if final_violations:
            raise AssertionError(
                f"final invariant violations for {scenario.name}/{scenario.mode.value}/{scenario.provider_name}: {final_violations}"
            )
        return {
            "scenario": scenario.name,
            "mode": scenario.mode.value,
            "provider": scenario.provider_name,
            "ticks": scenario.ticks,
            "calls_initiated": summary["calls_initiated"],
            "calls_connected": summary["calls_connected"],
            "calls_completed": summary["calls_completed"],
            "calls_failed": summary["calls_failed"],
            "decision_counts": decision_counts,
            "safety_events": safety_events[:12],
        }


def run_load_verification() -> list[dict[str, object]]:
    loads = [
        Scenario(
            name="LOAD_A",
            description="Load verification with reliable provider",
            mode=CampaignMode.PREDICTIVE,
            provider_name="provider_a",
            ticks=18,
            agent_count=40,
            borrower_count=300,
            target_concurrency=40,
        ),
        Scenario(
            name="LOAD_B",
            description="Load verification with noisy provider",
            mode=CampaignMode.PREDICTIVE,
            provider_name="provider_b",
            ticks=20,
            agent_count=50,
            borrower_count=500,
            target_concurrency=50,
        ),
    ]
    return [seed_and_run_verified_scenario(scenario) for scenario in loads]


def apply_agent_drop(repo, scenario: Scenario, tick: int) -> None:
    for event_tick, count in scenario.agent_drop_events:
        if event_tick != tick:
            continue
        with repo.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM agents WHERE state = ? ORDER BY id LIMIT ?",
                (AgentState.AVAILABLE.value, count),
            ).fetchall()
        for row in rows:
            repo.force_agent_state(row["id"], AgentState.OFFLINE, tick, active_call_id=None, wrap_up_until=None)


def main() -> None:
    started = time.perf_counter()
    report: dict[str, object] = {}
    print("Running unittest suite...", flush=True)
    report["unittest"] = run_unittest_suite()
    if not report["unittest"]["successful"]:
        print(json.dumps(report, indent=2))
        raise SystemExit(1)

    print("Running concurrency stress...", flush=True)
    report["concurrency_stress"] = run_concurrency_stress()

    print("Running scenario matrix...", flush=True)
    scenarios = [
        get_named_scenario("A", mode=CampaignMode.PROGRESSIVE, provider_name="provider_a"),
        get_named_scenario("A", mode=CampaignMode.PREDICTIVE, provider_name="provider_a"),
        get_named_scenario("B", mode=CampaignMode.PREDICTIVE, provider_name="provider_a"),
        get_named_scenario("C", mode=CampaignMode.PREDICTIVE, provider_name="provider_a"),
        get_named_scenario("D", mode=CampaignMode.PREDICTIVE, provider_name="provider_b"),
    ]
    report["scenario_matrix"] = [seed_and_run_verified_scenario(scenario) for scenario in scenarios]

    print("Running load verification...", flush=True)
    report["load_verification"] = run_load_verification()
    report["wall_clock_seconds"] = round(time.perf_counter() - started, 3)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
