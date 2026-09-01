from __future__ import annotations

import argparse
import json
from pathlib import Path

from .enums import CampaignMode
from .simulation.runner import SimulationRunner, run_load_test
from .simulation.scenarios import get_named_scenario


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartDialer prototype CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulate = subparsers.add_parser("simulate", help="Run a named simulator scenario")
    simulate.add_argument("--scenario", default="A", choices=["A", "B", "C", "D"])
    simulate.add_argument("--mode", choices=[mode.value for mode in CampaignMode], default=None)
    simulate.add_argument("--provider", choices=["provider_a", "provider_b"], default=None)

    load = subparsers.add_parser("load-test", help="Run the basic load-test harness")
    load.add_argument("--agents", type=int, default=100)
    load.add_argument("--borrowers", type=int, default=1000)
    load.add_argument("--ticks", type=int, default=40)
    load.add_argument("--mode", choices=[mode.value for mode in CampaignMode], default=CampaignMode.PREDICTIVE.value)
    load.add_argument("--provider", choices=["provider_a", "provider_b"], default="provider_b")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.command == "simulate":
        mode = CampaignMode(args.mode) if args.mode else None
        scenario = get_named_scenario(args.scenario, mode=mode, provider_name=args.provider)
        result = SimulationRunner(root).run(scenario)
    else:
        result = run_load_test(
            root=root,
            agent_count=args.agents,
            borrower_count=args.borrowers,
            ticks=args.ticks,
            mode=CampaignMode(args.mode),
            provider_name=args.provider,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
