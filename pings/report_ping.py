#!/usr/bin/env python3
"""
report_ping.py
End-to-end smoke:
- Build a complete, schema-valid ReportState from test context
- Seed all sections via model_merge_updates(...) to emit provenance
- Run ReportAgent initial draft (Prompt A)
- Print tokens + full Markdown draft
"""

import os

# --- repo path bootstrap (keep at top of file) ---
from pathlib import Path
import sys

# Resolve repo root as the parent of the `pings` folder
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# --- end bootstrap ---

import json
from datetime import datetime

import dotenv
dotenv.load_dotenv()

from report_state import ReportState, NOT_PROVIDED
from report_context import _build_context_from_testdata
from report_agent import ReportAgent


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def seed_sections(state: ReportState) -> ReportState:
    """
    Populate every report section with plausible values (schema-compliant).
    We use model_merge_updates so provenance rows are recorded.
    """
    turn = "seed"
    ts = now_iso()
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    # ---- Area Description ----
    area_updates = {
        "updates": {
            "area_description": {
                "context": "suburban residential block",
                "other_context_note": "adjacent to schoolyard and community garden",
                "site_use": "single-family residence; front yard near sidewalk",
                "foot_traffic_level": "moderate",
                "narratives": [
                    "Seasonal festivals increase foot traffic in spring and fall."
                ],
            }
        }
    }
    state = state.model_merge_updates(
        area_updates,
        policy="last_write",
        turn_id=turn,
        timestamp=ts,
        domain="area_description",
        extractor="seed",
        model_name=model_name,
        segment_text="Seed: area description",
    )

    # ---- Tree Description ----
    tree_updates = {
        "updates": {
            "tree_description": {
                "type_common": "American elm",
                "type_scientific": "Ulmus americana",
                "height_ft": "65",
                "canopy_width_ft": "55",
                "crown_shape": "broad vase-shaped crown",
                "dbh_in": "28",
                "trunk_notes": [
                    "Historic pruning wounds present; well compartmentalized",
                    "Basal flare normal with minor bark inclusion at root collar",
                ],
                "roots": [
                    "Surface roots visible on sidewalk edge; minor displacement",
                ],
                "defects": [
                    "Small seam along west scaffold branch, no active cracking",
                ],
                "general_observations": [
                    "Canopy provides significant shade to the front facade",
                    "Epicormic sprouts minimal this season",
                ],
                "health_overview": "generally fair to good vigor; mild upper-canopy dieback",
                "pests_pathogens_observed": ["suspected Dutch elm disease pressure in region"],
                "physiological_stress_signs": ["chlorosis on south aspect leaves"],
                "narratives": [
                    "Recent drought conditions may contribute to leaf scorch late season."
                ],
            }
        }
    }
    state = state.model_merge_updates(
        tree_updates,
        policy="last_write",
        turn_id=turn,
        timestamp=ts,
        domain="tree_description",
        extractor="seed",
        model_name=model_name,
        segment_text="Seed: tree description",
    )

    # ---- Targets ----
    targets_updates = {
        "updates": {
            "targets": {
                "items": [
                    {
                        "label": "public sidewalk",
                        "damage_modes": ["limb fall", "trip hazard from roots"],
                        "proximity_note": "canopy extends over walk by ~6 ft",
                        "occupied_frequency": "daily",
                        "narratives": ["Heavy school-day usage during morning and afternoon."],
                    },
                    {
                        "label": "driveway and parked vehicles",
                        "damage_modes": ["limb fall"],
                        "proximity_note": "east limbs overhang drive",
                        "occupied_frequency": "daily",
                        "narratives": [],
                    },
                ],
                "narratives": ["No overhead utility conflicts observed."],
            }
        }
    }
    state = state.model_merge_updates(
        targets_updates,
        policy="last_write",
        turn_id=turn,
        timestamp=ts,
        domain="targets",
        extractor="seed",
        model_name=model_name,
        segment_text="Seed: targets",
    )

    # ---- Risks ----
    risks_updates = {
        "updates": {
            "risks": {
                "items": [
                    {
                        "description": "Deadwood in upper canopy",
                        "likelihood": "possible",
                        "severity": "moderate",
                        "rationale": "several small dead branch tips observed; limited target occupancy.",
                    },
                    {
                        "description": "Branch union with minor included bark (west scaffold)",
                        "likelihood": "unlikely",
                        "severity": "moderate",
                        "rationale": "no active crack; seam appears old and stable; monitor during storms.",
                    },
                ],
                "narratives": ["Overall risk profile is low-to-moderate under normal weather."],
            }
        }
    }
    state = state.model_merge_updates(
        risks_updates,
        policy="last_write",
        turn_id=turn,
        timestamp=ts,
        domain="risks",
        extractor="seed",
        model_name=model_name,
        segment_text="Seed: risks",
    )

    # ---- Recommendations ----
    rec_updates = {
        "updates": {
            "recommendations": {
                "pruning": {
                    "narrative": "Deadwood removal in upper canopy; selective clearance over sidewalk.",
                    "scope": "prune branches ≤ 3 in. diameter; maintain natural form",
                    "limitations": "no climbing spurs on live tissue; traffic control as needed",
                    "notes": "schedule during dormant season if feasible",
                },
                "removal": {
                    "narrative": NOT_PROVIDED,
                    "scope": NOT_PROVIDED,
                    "limitations": NOT_PROVIDED,
                    "notes": NOT_PROVIDED,
                },
                "continued_maintenance": {
                    "narrative": "Re-inspect annually; soil test and supplement as indicated.",
                    "scope": "monitor west scaffold union; monitor chlorosis progression",
                    "limitations": "access constraints during school drop-off hours",
                    "notes": "consider structural pruning in 2–3 years",
                },
                "narratives": [
                    "Recommend mulching the root zone (2–3 inches depth, away from trunk)."
                ],
            }
        }
    }
    state = state.model_merge_updates(
        rec_updates,
        policy="last_write",
        turn_id=turn,
        timestamp=ts,
        domain="recommendations",
        extractor="seed",
        model_name=model_name,
        segment_text="Seed: recommendations",
    )

    return state


def main():
    os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")

    # 1) Construct ReportState with context from testdata (arborist/customer/location)
    state = ReportState(context=_build_context_from_testdata())

    # 2) Seed all sections (emits provenance)
    state = seed_sections(state)

    # 3) Run ReportAgent initial draft (Prompt A)
    agent = ReportAgent()
    out = agent.run(mode="draft", state=state, provenance=state.provenance, temperature=0.35)
    draft = out["draft_text"]
    hdrs = ["## Area Description", "## Tree Description", "## Targets", "## Risks", "## Recommendations"]
    has_all_h2s = all(h in draft for h in hdrs)
    has_para_ids = "[area_description-p1]" in draft or "[tree_description-p1]" in draft
    if hasattr(state, "add_tokens"):
        state = state.add_tokens("report_agent", out.get("tokens", {"in": 0, "out": 0}))
        print("has attribute")
    else:
        print("no attribute")
    header = {
        "model": out.get("model"),
        "tokens": out.get("tokens"),  # {"in": int, "out": int}
        "provenance_rows": len(state.provenance),
        "structure_ok": bool(has_all_h2s and has_para_ids),
    }
    print(json.dumps(header, ensure_ascii=False, indent=2))
    print("\n----- DRAFT (Markdown) -----\n")
    print(draft)


if __name__ == "__main__":
    main()
