#!/usr/bin/env python3
"""
Ping test for SectionReportAgent: exercises OUTLINE and PROSE paths.

Usage:
  # Fake model (no API calls; default)
  python ping_section_agent.py

  # Live call (requires OPENAI_API_KEY; uses OPENAI_MODEL or defaults)
  python ping_section_agent.py --live

  # Choose section and style
  python ping_section_agent.py --section tree_description --bullets --length short
"""

from __future__ import annotations
# --- repo path bootstrap (keep at top of file) ---
from pathlib import Path
import sys

# Resolve repo root as the parent of the `pings` folder
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# --- end bootstrap ---


import argparse
import os
import sys
import textwrap
from typing import Dict, Any
import dotenv
# Local imports (repo modules)
from report_state import ReportState, NOT_PROVIDED
from section_report_agent import SectionReportAgent, FakeChatModel

dotenv.load_dotenv()

def seed_state() -> ReportState:
    """
    Create a small but representative ReportState snapshot with both provided and
    NOT_PROVIDED values so outline/prose have something meaningful to show.
    """
    state = ReportState()

    # Make "tree_description" interesting:
    td = state.tree_description
    td.type_common = "London plane"
    td.type_scientific = "Platanus × acerifolia"
    td.dbh_in = "24 in"                     # numeric-as-string policy
    td.height_ft = NOT_PROVIDED             # left default on purpose
    td.canopy_width_ft = "40 ft"
    td.crown_shape = "spreading"
    td.defects.extend(["minor deadwood", "old pruning wounds"])
    td.general_observations.append("good structure with moderate clearance over walkway")

    # A couple of notes elsewhere so outline isn’t empty if you switch sections:
    state.area_description.site_use = "playground"
    state.targets.items = []  # explicitly empty list
    state.risks.items = []    # explicitly empty list

    # Cursor can be whatever; tests sometimes rely on this
    state.current_section = "tree_description"
    return state


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def run_outline(agent: SectionReportAgent, state: ReportState, section: str) -> Dict[str, Any]:
    print_header(f"[OUTLINE] section={section}")
    out = agent.run(
        section=section,
        state=state,
        mode="outline",
        reference_text=state.current_text,
        include_payload=True,   # handy to inspect snapshot/provided_paths if needed
    )
    outline = out.get("outline", [])
    print(f"model: {out.get('model')}  tokens: {out.get('tokens')}")
    print(f"lines: {len(outline)}")
    # Show first N lines for quick inspection
    for line in outline[:20]:
        print("  " + line)
    if len(outline) > 20:
        print(f"  ... ({len(outline)-20} more)")
    return out


def run_prose(agent: SectionReportAgent, state: ReportState, section: str, style: Dict[str, Any]) -> Dict[str, Any]:
    print_header(f"[PROSE] section={section} style={style}")
    out = agent.run(
        section=section,
        state=state,
        mode="prose",
        reference_text=state.current_text,
        temperature=0.3,
        style=style,
        include_payload=True,   # useful for debugging
    )
    text = out.get("text", "")
    print(f"model: {out.get('model')}  tokens: {out.get('tokens')}")
    print("text:")
    print(textwrap.fill(text, width=100))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Ping SectionReportAgent")
    parser.add_argument("--section", default="tree_description",
                        choices=["area_description", "tree_description", "targets", "risks", "recommendations"])
    parser.add_argument("--live", action="store_true", help="Use a live OpenAI call instead of FakeChatModel")
    parser.add_argument("--bullets", action="store_true", help="Prose as bullets instead of a paragraph")
    parser.add_argument("--length", default="medium", choices=["short", "medium", "long"], help="Target prose length")
    args = parser.parse_args()

    # Build a representative state
    state = seed_state()

    # Choose client: Fake by default (no network), live if requested
    if args.live:
        # rely on SectionReportAgent to construct a ChatOpenAI client internally
        agent = SectionReportAgent()
        print_header("[MODE] LIVE")
        if not os.getenv("OPENAI_API_KEY"):
            print("ERROR: --live requires OPENAI_API_KEY in the environment.", file=sys.stderr)
            sys.exit(1)
    else:
        # Fake client returns deterministic text and token counters
        fake_text = (
            "The tree is a London plane with a trunk diameter of 24 in and an estimated canopy width of 40 ft. "
            "It has a spreading crown and generally good structure with moderate clearance over the walkway. "
            "Minor deadwood and old pruning wounds are present."
        )
        agent = SectionReportAgent(client=FakeChatModel(text=fake_text, in_tokens=128, out_tokens=96))
        print_header("[MODE] FAKE (no API calls)")

    # 1) OUTLINE path
    outline_out = run_outline(agent, state, section=args.section)

    # 2) PROSE path
    style = {"bullets": bool(args.bullets), "length": args.length, "reading_level": "general"}
    prose_out = run_prose(agent, state, section=args.section, style=style)

    # 3) Minimal sanity checks (non-fatal): print a conclusion line
    ok_outline = isinstance(outline_out.get("outline"), list) and len(outline_out["outline"]) >= 1
    ok_prose = isinstance(prose_out.get("text"), str) and len(prose_out["text"].strip()) > 0
    print_header("RESULT")
    print(f"outline_ok={ok_outline}  prose_ok={ok_prose}")
    if not ok_outline or not ok_prose:
        print("One or more checks failed.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
