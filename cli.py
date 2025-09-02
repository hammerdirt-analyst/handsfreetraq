#!/usr/bin/env python3
"""
Project: Arborist Agent
File: cli.py
Author: roger erismann

Minimal interactive CLI (spy-only) for driving the Coordinator locally:
sets up a dev ReportContext, loops on user input, exposes inspector commands,
and prints trimmed results from Coordinator.handle_turn.

Methods & Classes
- pretty(obj: Any) -> str: JSON pretty-printer for terminal.
- main() -> None:
  - parse args (spy mode, model label, initial section),
  - seed env (OPENAI_MODEL/EXTRACTOR_MODE) for non-networked runs,
  - construct Coordinator with _build_context_from_testdata(),
  - REPL with commands:
    :section, :set <section>, :whatsleft, :state, :prov [n], :reset, :quit/:q,
    else → send line to Coordinator.handle_turn and pretty-print payload.

Dependencies
- Internal: report_agent.Coordinator, report_state.ReportState/compute_whats_left,
            report_context.ReportContext/_build_context_from_testdata
- External: python-dotenv (load_dotenv)
- Stdlib: argparse, json, os, typing
"""

import os
import json
import argparse
from typing import Any

# --- Import your project modules
from coordinator_agent import Coordinator
from report_state import ReportState, compute_whats_left
from report_context import ReportContext, _build_context_from_testdata # assumes defaultable fields exist
from dotenv import load_dotenv
load_dotenv()
def pretty(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)

def main():
    ap = argparse.ArgumentParser(description="Arborist agent CLI (spy-only)")
    ap.add_argument("--spy", action="store_true", default=True,
                    help="Force spy mode via environment (default: on)")
    ap.add_argument("--model", default="spy",
                    help="Model name for logging/telemetry (default: spy)")
    ap.add_argument("--section", default="tree_description",
                    choices=["area_description","tree_description","targets","risks","recommendations"],
                    help="Initial cursor/section (default: tree_description)")
    args = ap.parse_args()

    if args.spy:
        # Many setups key off env; this won’t call the network but helps the logs stay consistent.
        os.environ.setdefault("OPENAI_MODEL", args.model)
        os.environ.setdefault("EXTRACTOR_MODE", "spy")

    # Minimal context; if your ReportContext needs args, adjust as needed.
    #ctx = ReportContext()
    coord = Coordinator(_build_context_from_testdata())
    coord.state.current_section = args.section

    print("\nArborist Agent CLI (spy)")
    print("Type a statement, or use commands starting with ':'")
    print("Commands:")
    print("  :section               -> show current section")
    print("  :set <section>         -> set current section (tree_description|risks|targets|area_description|recommendations)")
    print("  :whatsleft             -> show missing fields summary")
    print("  :state                 -> dump full state (JSON)")
    print("  :prov [n]              -> show last n provenance rows (default 10)")
    print("  :reset                 -> reset state (keeps context)")
    print("  :quit / :q             -> exit\n")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line in (":quit", ":q"):
            break

        # Inspector commands
        if line == ":section":
            print(coord.state.current_section)
            continue

        if line.startswith(":set "):
            _, sec = line.split(" ", 1)
            sec = sec.strip()
            if sec in {"area_description","tree_description","targets","risks","recommendations"}:
                coord.state.current_section = sec
                print(f"section → {sec}")
            else:
                print("unknown section")
            continue

        if line == ":whatsleft":
            wl = compute_whats_left(coord.state)
            print(pretty(wl))
            continue

        if line == ":state":
            # Avoid dumping internal provenance noise by default; but this is the full state as JSON
            print(pretty(coord.state.model_dump(exclude_none=False)))
            continue

        if line.startswith(":prov"):
            parts = line.split()
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
            prov = coord.state.provenance[-n:]
            # Show the essentials we agreed on:
            distilled = [
                {
                    "turnid": p.turnid if hasattr(p, "turnid") else p.get("turnid"),
                    "section": p.section if hasattr(p, "section") else p.get("section"),
                    "path": p.path if hasattr(p, "path") else p.get("path"),
                    "value": p.value if hasattr(p, "value") else p.get("value"),
                    "text": p.text if hasattr(p, "text") else p.get("text"),
                }
                for p in prov
            ]
            print(pretty(distilled))
            continue

        if line == ":reset":
            # Keep context; create a fresh state
            coord.state = ReportState()
            coord.state.current_section = args.section
            print("state reset")
            continue

        # Normal turn → Coordinator
        out = coord.handle_turn(line)

        # Print the key bits the way we like to inspect them in terminal
        result = out.get("result") or {}
        payload = {
            "intent": out.get("intent"),
            "final_section": result.get("final_section"),
            "segments": result.get("segments"),
            "note": result.get("note"),
            "updates": result.get("updates"),  # echo of extractor envelopes
        }
        print(pretty(payload))

if __name__ == "__main__":
    main()
