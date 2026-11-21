"""Local command entry points for the Prahari demo."""

from __future__ import annotations

import argparse
import json

import uvicorn

from agent.loop import run as investigate
from faults.scenarios import heal, inject
from target_app.state import read_state
from verifier.report import verify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prahari AI on-call engineer")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("up", help="Prepare the local Prahari environment")
    break_parser = commands.add_parser("break", help="Select an incident scenario")
    break_parser.add_argument("--scenario", required=True, help="Scenario to inject")
    commands.add_parser("heal", help="Clear the selected incident scenario")
    commands.add_parser("test", help="Run the currently available checks")
    commands.add_parser("investigate", help="Run the safe on-call investigation loop")
    commands.add_parser("verify", help="Run three-part verification status")
    commands.add_parser("serve", help="Start the target API on port 8000")
    commands.add_parser("dashboard", help="Start the dashboard on port 8080")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "break":
        print(json.dumps(inject(args.scenario)))
    elif args.command == "heal":
        print(json.dumps(heal()))
    elif args.command == "investigate":
        print(json.dumps(investigate(), indent=2))
    elif args.command == "verify":
        print(json.dumps(verify().to_dict(), indent=2))
    elif args.command == "serve":
        uvicorn.run("target_app.app:app", host="0.0.0.0", port=8000, reload=False)
    elif args.command == "dashboard":
        uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8080, reload=False)
    elif args.command == "up":
        print("Prahari is initialized. Start `python main.py serve` and `python main.py dashboard`.")
    else:
        print(json.dumps(verify().to_dict(), indent=2))
    return 0
