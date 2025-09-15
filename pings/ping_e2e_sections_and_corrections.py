#!/usr/bin/env python3
"""
End-to-end ping for section paths + corrections + outline/prose.

What it covers
--------------
1) Seeds ReportState with realistic defaults + a few provided values.
2) Runs a multi-scope PROVIDE_STATEMENT through Coordinator:
   - "Tree Description: ..." (scalar overwrite + list append)
   - "Targets: ..." (string-list append)
3) Verifies state & provenance changes (scalar last-write, list append).
4) Runs OUTLINE (deterministic) and checks for updated values.
5) Runs PROSE with SectionReportAgent:
   - Fake model by default (no network), optional --live.

This is a *ping*, not a formal unit test—aimed at quick confidence.
"""

from __future__ import annotations

from pathlib import Path
import sys

# Resolve repo root as the parent of the `pings` folder
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
import argparse
import json
import os
import textwrap
from typing import Any, Dict, List

# Local modules
from report_context import _build_context_from_testdata
from report_state import ReportState
from coordinator_agent import Coordinator
from section_report_agent import SectionReportAgent, FakeChatModel


# ------------------------- Seed helpers -------------------------


def seed_context():
    """Return a fully-populated, schema-valid ReportContext from bundled test data."""
    return _build_context_from_testdata()
def seed_state() -> ReportState:
    s = ReportState()
    s.current_section = "tree_description"

    # Tree: give it a few provided values
    s.tree_description.type_common = "London plane"
    s.tree_description.type_scientific = "Platanus × acerifolia"
    s.tree_description.dbh_in = "24 in"
    s.tree_description.canopy_width_ft = "40 ft"
    s.tree_description.crown_shape = "spreading"
    s.tree_description.defects = ["minor deadwood"]
    s.tree_description.general_observations.append("good structure with moderate clearance over walkway")

    # Area/Targets left mostly default; we’ll add a targets narrative later
    s.area_description.site_use = "playground"
    return s



def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def print_json(title: str, obj: Any) -> None:
    print_header(title)
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# ------------------------- Ping steps -------------------------

def run_multiscope_corrections(coord: Coordinator) -> Dict[str, Any]:
    """
    Exercise explicit-scope parsing + extractors + merges:
    - Tree Description: set dbh + add defects (string -> list append)
    - Targets: add narratives (string -> list append)
    """
    text = (
        "Tree Description: set dbh to 30 in; add defects: hairline crack near union; "
        "Targets: add narratives: parking lot used daily"
    )
    out = coord.handle_turn(text)
    print_json("TURN RESULT (multi-scope corrections)", out)

    # Pull a focused snapshot to inspect
    st = coord.state.model_dump(exclude_none=False)
    subset = {
        "tree_description": {
            "dbh_in": st["tree_description"]["dbh_in"],
            "defects": st["tree_description"]["defects"],
        },
        "targets": {
            "narratives": st["targets"]["narratives"],
        },
        "provenance_tail": st["provenance"][-4:],
    }
    print_json("STATE AFTER CORRECTIONS (focused)", subset)

    # Basic checks
    ok_dbh = st["tree_description"]["dbh_in"] == "30 in"
    ok_defects_append = "hairline crack near union" in st["tree_description"]["defects"]
    ok_targets_narr = "parking lot used daily" in st["targets"]["narratives"]
    print_header("CORRECTIONS CHECKS")
    print(f"dbh_overwrite_ok={ok_dbh}  defects_append_ok={ok_defects_append}  targets_narrative_append_ok={ok_targets_narr}")
    return {
        "ok_dbh": ok_dbh,
        "ok_defects": ok_defects_append,
        "ok_targets": ok_targets_narr,
    }


def run_outline(agent: SectionReportAgent, state: ReportState, section: str) -> Dict[str, Any]:
    out = agent.run(
        section=section,
        state=state,
        mode="outline",
        reference_text=state.current_text,
        include_payload=True,
    )
    lines: List[str] = out.get("outline", [])
    print_header(f"OUTLINE ({section}) — first 20 lines")
    for line in lines[:20]:
        print("  " + line)
    if len(lines) > 20:
        print(f"  ... ({len(lines)-20} more)")
    # show a couple of key fields
    has_dbh_line = any(line.startswith("tree_description.dbh_in: 30 in") for line in lines)
    has_defects_line = any("tree_description.defects" in line for line in lines)
    print_header("OUTLINE CHECKS")
    print(f"outline_has_dbh30={has_dbh_line}  outline_has_defects_line={has_defects_line}")
    return {"has_dbh_line": has_dbh_line, "has_defects_line": has_defects_line}


def run_prose(agent: SectionReportAgent, state: ReportState, section: str, live: bool) -> Dict[str, Any]:
    style = {"bullets": False, "length": "medium", "reading_level": "general"}
    out = agent.run(
        section=section,
        state=state,
        mode="prose",
        reference_text=state.current_text,
        temperature=0.3,
        style=style,
        include_payload=True,
    )
    text = out.get("text", "")
    print_header(f"PROSE ({section}) — {'LIVE' if live else 'FAKE'}")
    print(textwrap.fill(text, width=100))
    ok_nonempty = isinstance(text, str) and len(text.strip()) > 0
    print_header("PROSE CHECK")
    print(f"prose_nonempty={ok_nonempty}  model={out.get('model')}  tokens={out.get('tokens')}")
    return {"prose_nonempty": ok_nonempty}


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E ping for sections + corrections")
    parser.add_argument("--live", action="store_true", help="Use a live OpenAI call for PROSE (requires OPENAI_API_KEY)")
    parser.add_argument("--section", default="tree_description",
                        choices=["area_description", "tree_description", "targets", "risks", "recommendations"])
    args = parser.parse_args()

    # Build Coordinator with seeded state & context
    context = seed_context()
    coord = Coordinator(context)
    coord.state = seed_state()  # replace empty state with our seed

    # 1) Multi-scope corrections via Coordinator
    corr_ok = run_multiscope_corrections(coord)

    # 2) Outline (deterministic) on the chosen section
    section = args.section
    # Agent for outline/prose
    if args.live:
        agent = SectionReportAgent()  # uses ChatOpenAI internally; needs OPENAI_API_KEY
        if not os.getenv("OPENAI_API_KEY"):
            print_header("ERROR")
            print("OPENAI_API_KEY is required for --live", flush=True)
            return
    else:
        fake_text = (
            "The tree is a London plane with a trunk diameter of 30 in and an estimated canopy width of 40 ft. "
            "It has a spreading crown and generally good structure with moderate clearance over the walkway. "
            "Minor deadwood and a hairline crack near the union are present."
        )
        agent = SectionReportAgent(client=FakeChatModel(text=fake_text, in_tokens=128, out_tokens=96))

    outline_ok = run_outline(agent, coord.state, section)

    # 3) Prose on the same section
    prose_ok = run_prose(agent, coord.state, section, live=args.live)

    # 4) Summary verdict
    print_header("SUMMARY VERDICT")
    verdict = {
        "corrections": corr_ok,
        "outline": outline_ok,
        "prose": prose_ok,
    }
    print(json.dumps(verdict, indent=2, ensure_ascii=False))

    # Soft fail if obvious breaks
    bad = []
    if not corr_ok["ok_dbh"]: bad.append("dbh overwrite")
    if not corr_ok["ok_defects"]: bad.append("defects append")
    if not corr_ok["ok_targets"]: bad.append("targets narratives append")
    if not outline_ok["has_dbh_line"]: bad.append("outline dbh")
    if not outline_ok["has_defects_line"]: bad.append("outline defects line")
    if not prose_ok["prose_nonempty"]: bad.append("prose text")

    if bad:
        print_header("PING RESULT: ⚠️ ISSUES")
        print(", ".join(bad))
    else:
        print_header("PING RESULT: ✅ OK")


if __name__ == "__main__":
    main()
