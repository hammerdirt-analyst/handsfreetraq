#!/usr/bin/env python3
"""
Project: Arborist Agent
File: coordinator_agent.py (Coordinator)
Author: roger erismann

Coordinator v2 for the arborist report assistant. Orchestrates a single user turn:
1) classify intent, 2) deflect context edits, 3) route to Provide Statement
   (cursor-first with explicit multi-scope parsing) or Request Service
   (deterministic router then LLM backstop), 4) merge extractor outputs
   into canonical ReportState with provenance, and 5) log a stable TURN block.

Methods & Classes
- _now_iso() -> str: UTC timestamp helper used in logs.  # logging helper
- _write_log(block_header: str, payload: dict) -> None: append structured TURN blocks to coordinator log.  # logging
- _is_context_edit(text: str) -> bool: regex gate that blocks edits to arborist/customer/location/lat-lon.  # safety
- _blocked_context_response(utterance: str) -> dict: standard envelope returned when a context edit is attempted.  # safety
- _handle_not_implemented(intent: str) -> (str, dict): stub router for unimplemented intents.  # stubs
- _find_all_scopes(text: str) -> list[tuple[int,int,str]]: locate explicit section scopes in the utterance.  # parsing
- _is_throwaway_lead_in(s: str) -> bool: drop trivial lead-ins (“please”, “update”, …) before first scope.  # parsing
- _parse_scoped_segments(user_text: str, current_section: str) -> list[(section, payload)]: split utterance into ordered, scoped segments (supports multi-scope turns).  # parsing
- class Coordinator(context: ReportContext)
    - __init__(context): construct with read-only context; create state; init extractor registry; log context presence.
    - _filter_missing_with_context(missing: dict) -> dict: hide context-managed sections from “what’s left”.
    - _envelope_has_provided(updates_envelope: dict) -> bool: detect if any provided (non-sentinel) values exist.
    - handle_turn(user_text: str) -> dict: full turn pipeline (intent → route → extract/merge → result envelope + logging).

Dependencies
- Internal: extractor_registry.default_registry, intent_model.classify_intent_llm,
            report_state.ReportState/NOT_PROVIDED, report_context.ReportContext,
            service_router.classify_service, service_classifier.ServiceRouterClassifier
- Stdlib: json, os, re, datetime, typing
- Notes: writes to COORD_LOG ("coordinator_logs/coordinator-tests.txt")
"""

from __future__ import annotations
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Literal
import service_classifier
from extractor_registry import default_registry
from intent_model import classify_intent_llm
from report_state import ReportState, NOT_PROVIDED
from report_context import ReportContext
from service_router import classify_service
from report_state import SectionSummaryInputs, SectionSummaryState  # add to imports

# --------------------------- coordinator logging ---------------------------

COORD_LOG = "coordinator_logs/coordinator-tests.txt"

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

# --------------------------- context-edit deflection ------------------------

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

# --------------------------- explicit scope parsing -------------------------

_CANON = {
    "area description": "area_description",
    "tree description": "tree_description",
    "targets": "targets",
    "risks": "risks",
    "recommendations": "recommendations",
}

_SCOPE_ANY_RX = re.compile(
    # 1) Explicit section with colon: "<section> :"
    r"(area description|tree description|targets|risks|recommendations)\s*:\s*|"
    # 2) Preposition style: "(in|for|under|to) <section>" BUT NOT when the section is immediately followed by a colon.
    #    This avoids eating the unit "in" before "targets:" (e.g., "... 30 in targets: ...").
    r"(?:\b(?:in|for|under|to)\s+)"
    r"(area description|tree description|targets|risks|recommendations)"
    r"\b(?!\s*:)\s*",
    re.IGNORECASE,
)

def _find_all_scopes(text: str) -> List[Tuple[int, int, str]]:
    scopes: List[Tuple[int, int, str]] = []
    for m in _SCOPE_ANY_RX.finditer(text or ""):
        label = m.group(1) or m.group(2)
        if label:
            scopes.append((m.start(), m.end(), _CANON[label.lower()]))
    return scopes

# Tiny boilerplate set for suppressing throwaway lead-ins like "please", "please note", "update", etc.
_BOILERPLATE_LEAD_INS = {
    "please",
    "please note",
    "please note that",
    "note",
    "update",
    "adjust",
    "set",
    "change",
    "edit",
    "modify",
}

def _is_throwaway_lead_in(s: str) -> bool:
    t = " ".join(s.lower().strip().split())
    return t in _BOILERPLATE_LEAD_INS

def _parse_scoped_segments(user_text: str, current_section: str) -> List[Tuple[str, str]]:
    """
    Split an utterance into ordered (section, payload) segments.

    Rules:
      - If explicit scopes exist, each scope 'owns' text until the next scope or end-of-text.
      - Unscoped lead-in (text before the first scope) is a segment for current_section.
        * But we drop trivial boilerplate like "please", "please note", "update", etc.
        * And we trim trailing separators from the lead-in (e.g., remove a ';' before the first scope).
      - A scope with no trailing content is a navigation-only segment (empty payload).
      - If no scopes exist, return [] and caller will run cursor-first.
    """
    text = user_text or ""
    scopes = _find_all_scopes(text)
    if not scopes:
        return []

    segments: List[Tuple[str, str]] = []

    # Lead-in before the first scope → current_section (with cleanup)
    first_start, _, _ = scopes[0]
    if first_start > 0:
        lead = text[:first_start].strip()
        # Trim trailing separators ONLY on lead-in to match tests (e.g., drop semicolon before first scope)
        lead = lead.rstrip(" ;,")
        if lead and not _is_throwaway_lead_in(lead):
            segments.append((current_section, lead))

    # Scoped segments
    for idx, (start, end, sec) in enumerate(scopes):
        next_start = scopes[idx + 1][0] if idx + 1 < len(scopes) else len(text)
        payload = text[end:next_start].strip()
        # NOTE: do NOT strip trailing separators on scoped payloads — tests expect them preserved in some cases.
        segments.append((sec, payload))

    return segments


def _summary_inputs_for(self, section: str, reference_text: str) -> SectionSummaryInputs:
    # Pull the section slice from state (each is a Pydantic model)
    section_state = getattr(self.state, section)
    # Collect provided dotted paths from this section only (reuse existing walk)
    flat: Dict[str, Any] = {}
    self.state._walk_and_collect(section, section_state, flat)
    provided = [p for p, v in flat.items() if self.state._is_provided(v)]
    return SectionSummaryInputs.make(section, section_state, reference_text, provided)


# ------------------------------- Coordinator --------------------------------
class Coordinator:
    """
    Coordinator v2:
      * Requires ReportContext at construction (read-only)
      * Deflects attempted context edits
      * Cursor-first routing with explicit-scope override, including multi-scope per turn
    """

    def __init__(self, context: ReportContext):
        if context is None:
            raise ValueError("ReportContext is required")
        self.context = context
        self.state = ReportState()
        self.registry = default_registry()

        # Log context presence at startup
        _write_log("CONTEXT_LOADED", {
            "arborist_loaded": self.context.arborist is not None,
            "customer_loaded": self.context.customer is not None,
            "location_loaded": self.context.location is not None,
        })

    # --- internal: filter “what’s left” with context-managed keys ----------
    def _filter_missing_with_context(self, missing: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """
        Remove context-managed sections/paths from the missing map so the agent
        never asks the user to supply them via chat.
        """
        if not isinstance(missing, dict):
            return missing

        filtered = dict(missing)
        for sec in ["arborist_info", "customer_info", "location"]:
            filtered.pop(sec, None)
        return filtered

    # --- internal: did this updates envelope contain any provided values? ---
    def _envelope_has_provided(self, updates_envelope: Dict[str, Any]) -> bool:
        """
        Walk the envelope { "updates": { "<section>": {...} } } and return True
        if any leaf value is actually provided (not the sentinel "Not provided"
        and not an empty list).
        """
        if not updates_envelope:
            return False
        root = updates_envelope.get("updates") if "updates" in updates_envelope else updates_envelope
        if not isinstance(root, dict):
            return False

        def walk(v: Any) -> bool:
            if isinstance(v, dict):
                return any(walk(x) for x in v.values())
            if isinstance(v, list):
                return len(v) > 0
            if isinstance(v, str):
                return v != NOT_PROVIDED
            return v is not None

        return walk(root)

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

        # 2) Context-edit deflection
        if intent == "PROVIDE_STATEMENT" and _is_context_edit(user_text):
            out = _blocked_context_response(user_text)
            _write_log("TURN", out)
            return out

        routed_to: Optional[str] = None
        ok = False
        result_payload: Optional[Dict[str, Any]] = None
        error: Optional[str] = None

        # 3) Provide-statement path: cursor-first with explicit-scope (multi-scope) handling
        if intent == "PROVIDE_STATEMENT":
            routed_to = "cursor → extractor (with explicit-scope segments)"
            try:
                # Build segments; if none found, do a single cursor-first segment
                segments = _parse_scoped_segments(user_text, self.state.current_section)
                if not segments:
                    segments = [(self.state.current_section, user_text or "")]

                updates_aggregate: Dict[str, Any] = {}
                any_captured = False
                segment_results: List[Dict[str, Any]] = []

                for seg_section, payload in segments:
                    # Update conversational context to this segment's section
                    self.state.current_section = seg_section

                    # Navigation-only segment: skip extractor, but record it for transparency
                    if not payload.strip():
                        segment_results.append({
                            "section": seg_section,
                            "note": "navigation_only",
                        })
                        continue

                    # Run the single extractor for this segment
                    ex = self.registry.get(seg_section)
                    out = ex.extract_dict(payload, temperature=0.0, max_tokens=300)

                    result_obj = out.get("result") or out
                    updates = (result_obj.get("updates") or {})

                    # Merge into state (prefer existing) with provenance
                    # Important: pass the scoped payload as segment_text
                    self.state = self.state.model_merge_updates(
                        updates,
                        policy="prefer_existing",
                        turn_id=_now_iso(),
                        timestamp=_now_iso(),
                        domain=seg_section,
                        extractor=ex.__class__.__name__,
                        model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                        segment_text=payload,
                    )

                    # Track whether anything was actually provided in this segment
                    captured_this_segment = self._envelope_has_provided(updates)
                    if captured_this_segment:
                        any_captured = True

                    # Aggregate a shallow echo of produced updates for the turn result
                    for section_key, payload_block in updates.items():
                        if section_key not in updates_aggregate:
                            updates_aggregate[section_key] = payload_block
                        else:
                            def _merge(dst, src):
                                if isinstance(dst, dict) and isinstance(src, dict):
                                    for k, v in src.items():
                                        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                                            _merge(dst[k], v)
                                        else:
                                            dst[k] = v
                            _merge(updates_aggregate[section_key], payload_block)

                    # Segment-level telemetry (no provided_fields anymore)
                    segment_results.append({
                        "section": seg_section,
                        "note": "captured" if captured_this_segment else "no_capture",
                    })

                # Build turn result
                if any_captured:
                    result_payload = {
                        "updates": updates_aggregate,
                        "segments": segment_results,
                        "final_section": self.state.current_section,
                        "note": "captured",
                    }
                    ok = True
                else:
                    result_payload = {
                        "updates": {},
                        "segments": segment_results,
                        "final_section": self.state.current_section,
                        "note": "no_capture",
                        "clarify": (
                            f"I didn't capture anything for {self.state.current_section.replace('_',' ')} from that. "
                            "You can rephrase, or say e.g. 'Tree Description: DBH is 24 in'."
                        ),
                    }
                    ok = True

            except Exception as e:
                error = f"ProvideData error: {e}"
                ok = False

        # 4) Other intents → stub handoff (no extractor calls here)
        elif intent == "REQUEST_SERVICE":
            routed_to = "RequestService"
            try:
                service, section = classify_service(user_text)  # deterministic first
                used_backstop = False
                if service == "NONE":
                    try:
                        clf = service_classifier.ServiceRouterClassifier.get()
                        pred = clf.classify(user_text)  # object with .service, .section, .confidence
                        if getattr(pred, "confidence", 0.0) >= 0.6 and getattr(pred, "service", "NONE") != "NONE":
                            service = pred.service
                            section = getattr(pred, "section", None)
                        else:
                            service = "CLARIFY"
                            section = None
                        used_backstop = True
                    except Exception as e:
                        return {
                            "utterance": user_text,
                            "intent": intent,
                            "routed_to": "RequestService",
                            "ok": False,
                            "result": None,
                            "error": f"Service routing error: {e}",
                        }

                # If a decision was made (either deterministic or LLM backstop):
                if not ok:
                    if service == "SECTION_SUMMARY" and section:
                        # 1) Gather inputs snapshot (what the agent will base the summary on)
                        inputs = self._summary_inputs_for(section, user_text)

                        # 2) Call the section agent (placeholder call for now)
                        #    text = SectionReportAgent.get().run(section, self.state, self.context, user_text)
                        text = f"[placeholder summary for {section.replace('_', ' ')}]"  # stub until agent is implemented

                        # 3) Replace the summary in state (replace-on-write + provenance)
                        now = _now_iso()
                        summary = SectionSummaryState(
                            text=text,
                            updated_at=now,
                            updated_by="llm",
                            based_on_turnid=now,  # You can pass a real turn-id if you track one
                            inputs=inputs,
                        )
                        self.state = self.state.set_section_summary(
                            section,
                            summary=summary,
                            turn_id=now,
                            timestamp=now,
                            model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                        )

                        result_payload = {
                            "service": service,
                            "section": section,
                            "preview": text[:280],
                            "note": "section_summary_replaced",
                        }
                        ok = True
                    else:
                        # default payload for other services (existing behavior)
                        result_payload = {
                            "service": service,
                            "section": section,
                            "utterance": user_text,
                        }
                        ok = True

            except Exception as e:
                error = f"Service routing error: {e}"
                ok = False


        else:
            routed_to, result_payload = _handle_not_implemented(intent)
            ok = False

        output = {
            "utterance": user_text,
            "intent": intent,
            "routed_to": routed_to,
            "ok": ok,
            "result": result_payload,
            "error": error,
        }

        # Safer logging (no dict-unpack). Keep logging from breaking the turn.
        _write_log("TURN", output)

        return output
