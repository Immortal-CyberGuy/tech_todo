from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from smartdialer.enums import CampaignMode
from smartdialer.simulation.runner import SimulationRunner, run_load_test
from smartdialer.simulation.scenarios import get_named_scenario


RESULTS_DIR = ROOT / "docs" / "results"


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    scenario_specs = [
        ("scenario-a-progressive-provider-a.json", get_named_scenario("A", mode=CampaignMode.PROGRESSIVE, provider_name="provider_a")),
        ("scenario-a-predictive-provider-a.json", get_named_scenario("A", mode=CampaignMode.PREDICTIVE, provider_name="provider_a")),
        ("scenario-b-predictive-provider-a.json", get_named_scenario("B", mode=CampaignMode.PREDICTIVE, provider_name="provider_a")),
        ("scenario-c-predictive-provider-a.json", get_named_scenario("C", mode=CampaignMode.PREDICTIVE, provider_name="provider_a")),
        ("scenario-d-predictive-provider-b.json", get_named_scenario("D", mode=CampaignMode.PREDICTIVE, provider_name="provider_b")),
    ]
    runner = SimulationRunner(ROOT)
    scenario_results: list[tuple[str, dict[str, object]]] = []
    for filename, scenario in scenario_specs:
        result = runner.run(scenario)
        result.pop("db_path", None)
        scenario_results.append((filename, result))
        (RESULTS_DIR / filename).write_text(json.dumps(result, indent=2), encoding="utf-8")

    load_result = run_load_test(
        root=ROOT,
        agent_count=100,
        borrower_count=1000,
        ticks=40,
        mode=CampaignMode.PREDICTIVE,
        provider_name="provider_b",
    )
    load_result.pop("db_path", None)
    (RESULTS_DIR / "load-basic-provider-b.json").write_text(
        json.dumps(load_result, indent=2),
        encoding="utf-8",
    )

    verification_output = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_rigorous_verification.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    verification_report = extract_json_report(verification_output.stdout)
    (RESULTS_DIR / "rigorous-verification.json").write_text(
        json.dumps(verification_report, indent=2),
        encoding="utf-8",
    )

    write_simulation_report(scenario_results)
    write_load_test_report(load_result, verification_report)


def extract_json_report(stdout: str) -> dict[str, object]:
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("{"):
            candidate = "\n".join(lines[index:])
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise ValueError("Could not find JSON report in rigorous verification output")


def format_summary_row(label: str, summary: dict[str, object]) -> str:
    decision_breakdown = summary["decision_breakdown"]
    decisions = ", ".join(f"{key}={value}" for key, value in decision_breakdown.items())
    mode = summary["mode"]
    if hasattr(mode, "value"):
        mode = mode.value
    return (
        f"| {label} | {mode} | {summary['provider_name']} | {summary['calls_initiated']} | "
        f"{summary['calls_connected']} | {summary['calls_completed']} | {summary['calls_failed']} | "
        f"{summary['peak_agent_utilization']:.2f} | {decisions} |"
    )


def write_simulation_report(scenario_results: list[tuple[str, dict[str, object]]]) -> None:
    generated_on = date.today().isoformat()
    summary_rows = []
    for filename, result in scenario_results:
        label = filename.removesuffix(".json")
        summary_rows.append(format_summary_row(label, result["summary"]))
    content = "\n".join(
        [
            "# Simulation Report",
            "",
            "This report captures committed scenario outputs for the SmartDialer prototype.",
            "",
            f"Generated on `{generated_on}`.",
            "",
            "## Scenarios",
            "",
            "| Scenario Artifact | Mode | Provider | Calls Initiated | Calls Connected | Calls Completed | Calls Failed | Peak Utilization | Safety Decisions |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
            *summary_rows,
            "",
            "## Interpretation",
            "",
            "- Scenario `A` is the low-answer-rate case. It shows that lower answer probability permits more outbound attempts without overwhelming agents.",
            "- Scenario `B` increases the answer rate and decreases talk time, which leads to materially more connected and completed calls.",
            "- Scenario `C` combines high answer rate with longer talk time. Predictive pacing becomes naturally more conservative because agent capacity is consumed longer.",
            "- Scenario `D` uses the noisy provider, outage windows, duplicates, and an agent drop. This is the main proof that the Safety Controller can reduce pacing and fall back when uncertainty rises.",
            "",
            "## What To Open",
            "",
            "- `docs/results/scenario-a-progressive-provider-a.json`",
            "- `docs/results/scenario-a-predictive-provider-a.json`",
            "- `docs/results/scenario-b-predictive-provider-a.json`",
            "- `docs/results/scenario-c-predictive-provider-a.json`",
            "- `docs/results/scenario-d-predictive-provider-b.json`",
        ]
    )
    (ROOT / "docs" / "simulation-report.md").write_text(content + "\n", encoding="utf-8")


def write_load_test_report(load_result: dict[str, object], verification_report: dict[str, object]) -> None:
    generated_on = date.today().isoformat()
    summary = load_result["summary"]
    load_meta = load_result["load_test"]
    load_verification = verification_report["load_verification"]
    verification_rows = [
        f"| {entry['scenario']} | {entry['provider']} | {entry['ticks']} | {entry['calls_initiated']} | {entry['calls_connected']} | {entry['calls_completed']} | {entry['calls_failed']} | {', '.join(f'{k}={v}' for k, v in entry['decision_counts'].items())} |"
        for entry in load_verification
    ]
    content = "\n".join(
        [
            "# Load Test Report",
            "",
            "This report captures the committed basic load-test evidence required by the assignment.",
            "",
            f"Generated on `{generated_on}`.",
            "",
            "## Primary Basic Load Test",
            "",
            f"- Command shape: `python scripts\\run_load_test.py load-test --agents {load_meta['agent_count']} --borrowers {load_meta['borrower_count']} --ticks {load_meta['ticks']} --mode predictive --provider provider_b`",
            f"- Wall-clock time: `{load_meta['wall_clock_seconds']}s`",
            f"- Calls initiated: `{summary['calls_initiated']}`",
            f"- Calls connected: `{summary['calls_connected']}`",
            f"- Calls completed: `{summary['calls_completed']}`",
            f"- Calls failed: `{summary['calls_failed']}`",
            "",
            "## Verification Load Runs",
            "",
            "| Scenario | Provider | Ticks | Calls Initiated | Calls Connected | Calls Completed | Calls Failed | Decision Counts |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
            *verification_rows,
            "",
            "## What Breaks First",
            "",
            "- At `100` agents, the prototype is still usable locally, but SQLite write contention and repeated reconciliation scans start becoming the dominant cost.",
            "- At `1,000` agents, SQLite and single-process event ingestion become the primary bottlenecks long before business logic becomes the issue.",
            "- At `10,000` agents, this prototype shape would not be appropriate without architectural changes. The first things to replace would be SQLite, full-table recovery scans, and the single-process execution model.",
            "",
            "## How To Fix It",
            "",
            "- move from SQLite to PostgreSQL",
            "- partition work by campaign",
            "- separate event ingestion from pacing workers",
            "- replace broad scans with queue-backed or lease-aware recovery jobs",
            "- add indexed work queues and stronger operational metrics",
            "",
            "## Artifacts",
            "",
            "- `docs/results/load-basic-provider-b.json`",
            "- `docs/results/rigorous-verification.json`",
        ]
    )
    (ROOT / "docs" / "load-test-report.md").write_text(content + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
