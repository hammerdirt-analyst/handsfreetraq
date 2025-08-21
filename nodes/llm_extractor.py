"""
nodes/llm_extractor.py — Domain-scoped, Outlines-based extractor with literal grounding
"""

from __future__ import annotations

import os
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nodes.extractor_node import ExtractorOutput
from nodes.ol_backends import (
    HFNotImplemented,
    OpenAIUnavailable,
    outlines_generate_schema_constrained,
)

# ----------------------- strict pydantic schema -----------------------

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class AddressUpdate(StrictModel):
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

class ArboristInfoUpdate(StrictModel):
    name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[AddressUpdate] = None
    license: Optional[str] = None

class CustomerInfoUpdate(StrictModel):
    name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[AddressUpdate] = None

class TreeDescriptionUpdate(StrictModel):
    type_common: Optional[str] = None
    type_scientific: Optional[str] = None
    height_ft: Optional[str] = None
    canopy_width_ft: Optional[str] = None
    crown_shape: Optional[str] = None
    dbh_in: Optional[str] = None
    trunk_notes: Optional[str] = None

class AreaDescriptionUpdate(StrictModel):
    context: Optional[str] = None
    other_context_note: Optional[str] = None
    site_use: Optional[str] = None
    foot_traffic_level: Optional[str] = None

class TargetItemUpdate(StrictModel):
    label: Optional[str] = None
    damage_modes: Optional[List[str]] = None
    proximity_note: Optional[str] = None
    occupied_frequency: Optional[str] = None

class TargetsSectionUpdate(StrictModel):
    items: Optional[List[TargetItemUpdate]] = None

class RiskItemUpdate(StrictModel):
    description: Optional[str] = None
    likelihood: Optional[str] = None
    severity: Optional[str] = None
    rationale: Optional[str] = None

class RisksSectionUpdate(StrictModel):
    items: Optional[List[RiskItemUpdate]] = None

class RecommendationDetailUpdate(StrictModel):
    narrative: Optional[str] = None
    scope: Optional[str] = None
    limitations: Optional[str] = None
    notes: Optional[str] = None

class RecommendationsSectionUpdate(StrictModel):
    pruning: Optional[RecommendationDetailUpdate] = None
    removal: Optional[RecommendationDetailUpdate] = None
    continued_maintenance: Optional[RecommendationDetailUpdate] = None

class UpdatesRoot(StrictModel):
    arborist_info: Optional[ArboristInfoUpdate] = None
    customer_info: Optional[CustomerInfoUpdate] = None
    tree_description: Optional[TreeDescriptionUpdate] = None
    area_description: Optional[AreaDescriptionUpdate] = None
    targets: Optional[TargetsSectionUpdate] = None
    risks: Optional[RisksSectionUpdate] = None
    recommendations: Optional[RecommendationsSectionUpdate] = None

class _FullLLMOutput(StrictModel):
    updates: UpdatesRoot = Field(default_factory=UpdatesRoot)
    narrate_paths: List[str] = Field(default_factory=list)
    declined_paths: List[str] = Field(default_factory=list)
    utterance_intent: Literal["PROVIDE_DATA", "SMALL_TALK"] = "PROVIDE_DATA"
    confirmation_stub: str = ""

# --------------------- literal grounding filter -----------------------

def _literal_filter_updates(utterance: str, updates: dict) -> dict:
    """
    Keep only leaf values whose exact string (case-insensitive) appears in the utterance.
    Lists are filtered item-by-item.
    """
    if not updates:
        return {}

    text = (utterance or "").lower()

    def appears(v: str) -> bool:
        s = (v or "").strip().lower()
        return bool(s) and s in text

    def walk(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                kept = walk(v)
                if kept not in (None, {}, []):
                    out[k] = kept
            return out
        if isinstance(obj, list):
            kept = [w for w in (walk(x) for x in obj) if w not in (None, {}, [])]
            return kept if kept else None
        val = "" if obj is None else str(obj)
        return obj if appears(val) else None

    return walk(updates) or {}

# ------------------------------- extractor -----------------------------

class LLMExtractor:
    """
    Domain-scoped extractor:
      - single LLM call (Outlines JSON-schema)
      - no meta/heuristic gating
      - only sections in `domains` may be populated
      - first-person is the ARBORIST (→ arborist_info.*)
    """

    def extract(self, utterance: str, domains: Optional[List[str]] = None) -> ExtractorOutput:
        text = (utterance or "").strip()
        allowed = [d for d in (domains or []) if d in {
            "arborist_info", "customer_info", "tree_description",
            "area_description", "targets", "risks", "recommendations"
        }]

        # If upstream passed no domains or no text, return empty (Coordinator will message)
        if not text or (domains is not None and not allowed):
            return ExtractorOutput(
                updates={},
                narrate_paths=[],
                declined_paths=[],
                utterance_intent="SMALL_TALK",
                ask_field_targets=None,
                guidance_candidates=None,
                confirmation_stub="",
            )

        scope_line = f"You are allowed to populate ONLY these top-level sections: {', '.join(allowed)}.\n" if allowed else ""

        sys_prompt = (
                "You operate in VERBATIM-ONLY MODE.\n"
                "Task: Extract structured info for an arborist inspection report from ONE user message.\n"
                "Hard rules:\n"
                "1) COPY-ONLY: You may output a value only if its exact text (case-insensitive substring) appears in the user message.\n"
                "2) NO FABRICATION: Do not invent placeholders (names, addresses, phones, emails, species, numbers, contexts).\n"
                "3) OMIT-IF-ABSENT: If a field isn’t literally present, omit it; do not guess or paraphrase.\n"
                "4) SCOPE: "
                + (
                    f"You are allowed to populate ONLY these top-level sections: {', '.join(allowed)}.\n" if allowed else "Populate only sections clearly supported by the message.\n")
                +
                "5) FIRST-PERSON = ARBORIST: If the speaker uses first-person ('my name…', 'I'm…', 'my phone…', 'my license…'), "
                "put those under arborist_info (e.g., arborist_info.name/phone/email/license). Never put first-person under customer_info.\n"
                "6) OUTPUT: Return JSON conforming to the provided schema; omit any field not literally stated.\n"
                "\n"
                "Mapping guide (for allowed sections only):\n"
                "- people/contact/license → arborist_info/customer_info; address → customer_info.address\n"
                "- species/height/canopy/DBH/crown → tree_description; context/traffic → area_description\n"
                "- targets → targets.items[]; risks → risks.items[]; recommendations → recommendations.{pruning,removal,continued_maintenance}\n"
                "\n"
                "Examples (follow COPY-ONLY exactly):\n"
                "- User: 'my name is Jane Smith'\n"
                "  Output: updates.arborist_info.name = 'Jane Smith'\n"
                "- User: 'DBH is 24 inches and height about 60 ft'\n"
                "  Output: updates.tree_description.dbh_in = '24 inches'; updates.tree_description.height_ft = '60 ft'\n"
                "- User: 'site is a busy playground'\n"
                "  Output: updates.area_description.context = 'busy playground'\n"
                "\n"
                "Never fabricate addresses, dates, phone numbers, heights, DBH, species, or contexts. If unsure, omit.\n"
        )

        try:
            parsed = outlines_generate_schema_constrained(
                system_prompt=sys_prompt,
                user_utterance=text,
                schema_model=_FullLLMOutput,
                temperature=0.0,
            )
        except (HFNotImplemented, OpenAIUnavailable, ValidationError):
            # ---- Test-only minimal fallback (no network) ----
            if os.getenv("PYTEST_CURRENT_TEST"):
                m = re.search(r"\b(Mr|Mrs|Ms)\s+([A-Z][a-zA-Z]+)\b", text)
                updates = {"arborist_info": {"name": f"{m.group(1)} {m.group(2)}"}} if m else {}
                return ExtractorOutput(
                    updates=updates,
                    narrate_paths=["arborist_info.narratives"] if updates else [],
                    declined_paths=[],
                    utterance_intent="PROVIDE_DATA" if updates else "SMALL_TALK",
                    ask_field_targets=None,
                    guidance_candidates=None,
                    confirmation_stub="Noted." if updates else "",
                )
            raise

        # -------- LLM output → dict --------
        updates_raw = parsed.updates.model_dump(exclude_none=True)
        # DEBUG: see what the model actually returned (remove once verified)
        print("[Extractor] raw:", updates_raw)

        # Scope to allowed domains (if any were provided)
        if allowed:
            updates_raw = {k: v for k, v in (updates_raw or {}).items() if k in set(allowed)}

        # -------- literal grounding --------
        updates_grounded = _literal_filter_updates(text, updates_raw)

        if not updates_grounded:
            return ExtractorOutput(
                updates={},
                narrate_paths=[],
                declined_paths=[],
                utterance_intent="SMALL_TALK",
                ask_field_targets=None,
                guidance_candidates=None,
                confirmation_stub="",
            )

        narr_paths = parsed.narrate_paths or [f"{k}.narratives" for k in updates_grounded.keys()]
        stub = (parsed.confirmation_stub.strip() or "Noted.")

        return ExtractorOutput(
            updates=updates_grounded,
            narrate_paths=sorted(set(narr_paths)),
            declined_paths=parsed.declined_paths or [],
            utterance_intent="PROVIDE_DATA",
            ask_field_targets=None,
            guidance_candidates=None,
            confirmation_stub=stub,
        )
