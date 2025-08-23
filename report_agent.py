#!/usr/bin/env python3
# report_agent.py — Coordinator with read-only ReportContext and domain filtering

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Literal

from pydantic import BaseModel, Field, ConfigDict

from intent_llm import classify_intent_llm
from report_state import ReportState, NOT_PROVIDED
from report_context import ReportContext  # actively used: to filter "what's left"

# Extractors + model factory (report-editable sections only)
from models import (
    ModelFactory,
    TreeDescriptionExtractor,
    AreaDescriptionExtractor,
    RisksExtractor,
    RecommendationsExtractor,
)

# --------------------------- coordinator logging ---------------------------

COORD_LOG = "coordinator-tests.txt"

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _write_log(block_header: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(COORD_LOG) or ".", exist_ok=True)
    with open(COORD_LOG, "a", encoding="utf-8") as f:
        f.write("=" * 64 + "\n")
        f.write(f"[{_now_iso()}] {block_header}\n")
        f.write("-" * 64 + "\n")
        f.write(json.dumps(payload, indent=2, ensure_ascii=False))
        f.write("\n\n")

# --------------------------- domain classification -------------------------

# Only domains that are part of the editable report state:
ALLOWED_DOMAINS: List[str] = [
    "tree_description",
    "area_description",
    "risks",
    "recommendations", # (add "targets", "recommendations" when you have those extractors)
]

DomainLabel = Literal["tree_description", "area_description", "risks"]

class DomainSchema(BaseModel):
    domains: List[DomainLabel] = Field(...)
    model_config = ConfigDict(extra="forbid")
import json, re

def _safe_parse_domains(raw: str) -> list[str]:
    # Try direct JSON
    try:
        return (json.loads(raw) or {}).get("domains", [])
    except Exception:
        pass
    # Try to salvage the largest JSON object substring
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return (json.loads(m.group(0)) or {}).get("domains", [])
        except Exception:
            pass
    return []

def classify_data_domains_llm(text: str) -> list[str]:
    model = ModelFactory.get()
    prompt = (
        "Return ONLY strict JSON on one line: {\"domains\": [...]}.\n"
        "Choose up to TWO from exactly this set:\n"
        "[\"tree_description\",\"area_description\",\"risks\",\"recommendations\"]\n\n"
        "Rules:\n"
        "- 'risks' ONLY if tokens present: risk, hazard, likelihood, likely, unlikely, probability, severity, rationale.\n"
        "- 'recommendations' for actions/proposals: recommend, should, scope, limitation(s), maintenance, notes indicate,\n"
        "  narrative, inspect/inspection, prune/pruning, thin/thinning, elevate/clearance, remove/removal,\n"
        "  mulch, irrigation, treat/treatment.\n"
        "- If uncertain, return {\"domains\": []}.\n\n"
        f"User message:\n{text}\n"
    )
    raw = model(prompt, DomainSchema, temperature=0.0, max_tokens=64)
    domains = [d for d in _safe_parse_domains(raw) if d in ALLOWED_DOMAINS]

    # Deterministic guard rails
    lowered = text.lower()
    risk_tokens = ("risk","hazard","likelihood","likely","unlikely","probability","severity","rationale")
    rec_tokens  = ("recommend"," should ","scope","limitation","limitations","maintenance","notes indicate","narrative",
                   "inspect","inspection","prune","pruning","thin","thinning","elevate","clearance",
                   "remove","removal","mulch","irrigation","treat","treatment")
    tree_cues   = ("dbh","height","canopy","crown","trunk","roots","defects","species","observations")

    has_risk = any(t in lowered for t in risk_tokens)
    has_rec  = any(t in lowered for t in rec_tokens)

    # Ensure rec-only lines map to recommendations
    if has_rec and not has_risk and "recommendations" not in domains:
        domains.append("recommendations")

    # Don’t allow 'risks' without risk tokens
    if "risks" in domains and not has_risk:
        domains = [d for d in domains if d != "risks"]

    # Prefer tree vs area when tree cues exist
    if any(t in lowered for t in tree_cues):
        if "tree_description" not in domains:
            domains = ["tree_description"] + [d for d in domains if d != "area_description"]

    # Unique and cap at 2
    seen = set()
    domains = [d for d in domains if not (d in seen or seen.add(d))][:2]
    return domains


# --------------------------- context-edit deflection ------------------------

# If the user attempts to edit job context (arborist/customer/location), we block it.
_CTX_EDIT_RE = re.compile(
    r"\b(customer|client|arborist|my\s+(name|phone|email|license)|"
    r"(customer|client)\s+(name|phone|email|address)|"
    r"(latitude|longitude|lat|lon|coordinates?))\b",
    flags=re.IGNORECASE,
)

def _is_context_edit(text: str) -> bool:
    return bool(_CTX_EDIT_RE.search(text or ""))

def _blocked_context_response(utterance: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "intent": "PROVIDE_STATEMENT",
        "routed_to": "blocked_context_edit",
        "result": {"stub": "CONTEXT_EDIT_BLOCKED"},
        "error": None,
        "note": "Edits to arborist/customer/location are managed outside the report. Use the job setup screen.",
        "utterance": utterance,
    }

# --------------------------- not-implemented stubs -------------------------

def _handle_not_implemented(intent: str) -> Tuple[str, Dict[str, Any]]:
    mapping = {
        "REQUEST_SUMMARY": ("ReportNode", {"stub": "SUMMARY_NOT_IMPLEMENTED"}),
        "REQUEST_REPORT": ("ReportNode", {"stub": "REPORT_NOT_IMPLEMENTED"}),
        "WHAT_IS_LEFT": ("WhatsLeft", {"stub": "WHATS_LEFT_NOT_IMPLEMENTED"}),
        "ASK_FIELD": ("None", {"stub": "UNHANDLED_INTENT"}),
        "ASK_QUESTION": ("None", {"stub": "UNHANDLED_INTENT"}),
        "SMALL_TALK": ("None", {"stub": "UNHANDLED_INTENT"}),
    }
    return mapping.get(intent, ("None", {"stub": "UNHANDLED_INTENT"}))

# ------------------------------- Coordinator --------------------------------

class Coordinator:
    """
    Coordinator v2:
      * Requires ReportContext at construction (read-only)
      * Excludes arborist/customer/location from any updates
      * Filters domain router output to ALLOWED_DOMAINS
      * Deflects attempted context edits
      * Uses ReportContext to filter WHAT_IS_LEFT so context-managed fields never show as “missing”
    """

    def __init__(self, context: ReportContext):
        if context is None:
            raise ValueError("ReportContext is required")
        self.context = context  # actively used below
        self.state = ReportState()

        # Log context summary at startup (presence only)
        _write_log("CONTEXT_LOADED", {
            "arborist_loaded": self.context.arborist is not None,
            "customer_loaded": self.context.customer is not None,
            "location_loaded": self.context.location is not None,
        })

        # Instantiate only the allowed section extractors
        self._extractors: Dict[str, Any] = {
            "tree_description": TreeDescriptionExtractor(),
            "area_description": AreaDescriptionExtractor(),
            "risks": RisksExtractor(),
            "recommendation": RecommendationsExtractor()
        }

    # --- internal: filter “what’s left” with context-managed keys ----------
    def _filter_missing_with_context(self, missing: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """
        Remove context-managed sections/paths from the missing map so the agent
        never asks the user to supply them via chat.
        """
        if not isinstance(missing, dict):
            return missing

        filtered = dict(missing)  # shallow copy

        # Drop whole sections that are context-managed
        for sec in ["arborist_info", "customer_info", "location"]:
            if sec in filtered:
                filtered.pop(sec, None)

        return filtered

    def handle_turn(self, user_text: str) -> Dict[str, Any]:
        # Record the utterance (state holds only report-editable data)
        self.state.current_text = user_text

        # 1) Intent
        try:
            intent = classify_intent_llm(user_text).intent
        except Exception as e:
            payload = {
                "utterance": user_text,
                "intent": "INTENT_ERROR",
                "routed_to": None,
                "ok": False,
                "result": None,
                "error": f"Intent classifier unavailable: {e}",
            }
            _write_log("TURN (intent error)", payload)
            return payload

        # 2) Context-edit deflection (block any attempt to change job context)
        if intent == "PROVIDE_STATEMENT" and _is_context_edit(user_text):
            out = _blocked_context_response(user_text)
            _write_log("TURN", out)
            return out

        routed_to: Optional[str] = None
        ok = False
        result_payload: Optional[Dict[str, Any]] = None
        error: Optional[str] = None
        coord_domains: Optional[List[str]] = None

        # 3) Routing for report-editable domains only
        if intent == "PROVIDE_STATEMENT":
            routed_to = "LLM(domain) → extractors (report-only)"
            try:
                domains = classify_data_domains_llm(user_text)
                domains = [d for d in domains if d in self._extractors]
                coord_domains = domains[:]

                updates_aggregate: Dict[str, Any] = {}
                provided_all: List[str] = []

                for dom in domains:
                    ex = self._extractors[dom]
                    out = ex.extract_dict(user_text, temperature=0.0, max_tokens=300)
                    result = out.get("result") or out
                    updates = (result.get("updates") or {})
                    # Merge into state (shallow), preferring existing provided values
                    self.state = self.state.model_merge_updates(
                        updates,
                        policy="prefer_existing",
                        turn_id=_now_iso(),
                        timestamp=_now_iso(),
                        domain=dom,
                        extractor=ex.__class__.__name__,
                        model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    )
                    # accumulate visible “provided_fields”
                    provided = out.get("provided_fields")
                    if provided:
                        provided_all.extend(provided)

                    # Plain dict echo of what just got produced (not full state)
                    for section, payload in updates.items():
                        if section not in updates_aggregate:
                            updates_aggregate[section] = payload
                        else:
                            def _merge(dst, src):
                                if isinstance(dst, dict) and isinstance(src, dict):
                                    for k, v in src.items():
                                        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                                            _merge(dst[k], v)
                                        else:
                                            dst[k] = v
                            _merge(updates_aggregate[section], payload)

                result_payload = {
                    "updates": updates_aggregate,
                    "provided_fields": sorted(set(provided_all)),
                    "domains": list(set(coord_domains)),
                }
                ok = True

            except Exception as e:
                error = f"ProvideData error: {e}"
                ok = False


        elif intent == "REQUEST_SERVICE":
            routed_to = "RequestService"
            try:
                result_payload = {
                    "stub": "REQUEST_FORWARDED_TO_SERVICE_AGENT",
                    "service_note": "Client requested a service; handed off to service agent.",
                    "utterance": user_text,

                }
                ok = True
                coord_domains = None  # not applicable

            except Exception:
                routed_to, result_payload = _handle_not_implemented(intent)
                ok = False

        else:
            routed_to, result_payload = _handle_not_implemented(intent)
            ok = False

        output = {
            "utterance": user_text,
            "intent": intent,
            "domains": coord_domains,
            "routed_to": routed_to,
            "ok": ok,
            "result": result_payload,
            "error": error,
        }

        _write_log("TURN", output)
        return output


# # Optional CLI quick check (expects context from test_data)
# if __name__ == "__main__":
#     from test_data import ARBORIST_PROFILE, CUSTOMER_PROFILE, TREE_LOCATION
#     from report_context import ReportContext, ArboristInfoCtx, CustomerInfoCtx, AddressCtx, LocationCtx
#
#     ctx = ReportContext(
#         arborist=ArboristInfoCtx(**ARBORIST_PROFILE),
#         customer=CustomerInfoCtx(**CUSTOMER_PROFILE),
#         location=LocationCtx(**TREE_LOCATION),
#     )
#     C = Coordinator(context=ctx)
#     for p in [
#         "my name is roger erismann",
#         "dbh is 24 inches and height 60 ft",
#         "site use is playground; foot traffic is high",
#         "risk: falling branches likely; severity high; rationale over walkway",
#         "coordinates are 37.77, -122.42",
#         "what's left?",
#     ]:
#         print(json.dumps(C.handle_turn(p), indent=2, ensure_ascii=False))
