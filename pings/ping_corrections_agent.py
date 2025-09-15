#!/usr/bin/env python3
from __future__ import annotations
# --- repo path bootstrap (keep at top of file) ---
from pathlib import Path
import sys

# Resolve repo root as the parent of the `pings` folder
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# --- end bootstrap ---

import json
import os

from report_state import ReportState
from corrections_agent import CorrectionsAgent

def seed_state() -> ReportState:
    s = ReportState()
    s.current_section = "tree_description"
    # seed a few values; leave others as "Not provided"
    s.tree_description.type_common = "London plane"
    s.tree_description.dbh_in = "24 in"
    s.tree_description.defects = ["minor deadwood"]
    return s

def print_state(label: str, st: ReportState) -> None:
    d = st.model_dump(exclude_none=False)
    print(f"\n=== {label} ===")
    print(json.dumps({
        "tree_description": d["tree_description"],
        "provenance_tail": d["provenance"][-3:],  # last few rows only
    }, indent=2, ensure_ascii=False))

def main() -> None:
    state = seed_state()
    agent = CorrectionsAgent()

    # A correction utterance with both scalar overwrite and list append
    text = "Tree Description: set dbh to 30 in; add defects: fresh crack near union"

    out = agent.run(section="tree_description", text=text, state=state, policy="last_write")
    print("\n[CorrectionsAgent] applied:", out["applied"])
    print(json.dumps(out["updates"], indent=2, ensure_ascii=False))

    # Merge if anything applied
    if out["applied"]:
        state = state.model_merge_updates(
            out["updates"],
            policy="last_write",
            turn_id="T-123",
            timestamp="2025-09-03T12:00:00Z",
            domain="tree_description",
            extractor="CorrectionsAgent",
            model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            segment_text=text,
        )

    print_state("POST-MERGE", state)

if __name__ == "__main__":
    main()
