#!/usr/bin/env python3
# report_agent.py — Coordinator v2: cursor-first routing with explicit-scope (multi-scope) handling

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Literal

from extractor_registry import default_registry
from intent_llm import classify_intent_llm
from report_state import ReportState, NOT_PROVIDED
from report_context import ReportContext
from one_turn_parser import parse_turn
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

# Any scope label anywhere in the utterance:
#   "<Section>:"  OR  "(in|for|under|to) <Section> ..."
_SCOPE_ANY_RX = re.compile(
    r"(area description|tree description|targets|risks|recommendations)\s*:\s*|"
    r"(?:\b(?:in|for|under|to)\s+)(area description|tree description|targets|risks|recommendations)\b[:\s]*",
    re.I,
)

def _find_all_scopes(text: str) -> List[Tuple[int, int, str]]:
    scopes: List[Tuple[int, int, str]] = []
    for m in _SCOPE_ANY_RX.finditer(text or ""):
        label = m.group(1) or m.group(2)
        if label:
            scopes.append((m.start(), m.end(), _CANON[label.lower()]))
    return scopes

def _parse_scoped_segments(user_text: str, current_section: str) -> List[Tuple[str, str]]:
    """
    Split an utterance into ordered (section, payload) segments.

    Rules:
      - If explicit scopes exist, each scope 'owns' text until the next scope or end-of-text.
      - Unscoped lead-in (text before the first scope) is a segment for current_section.
      - A scope with no trailing content is a navigation-only segment (empty payload).
      - If no scopes exist, return [] and caller will run cursor-first.
    """
    text = user_text or ""
    scopes = _find_all_scopes(text)
    if not scopes:
        return []

    segments: List[Tuple[str, str]] = []

    # Lead-in before the first scope → current_section
    first_start, _, _ = scopes[0]
    if first_start > 0:
        lead = text[:first_start].strip()
        if lead:
            segments.append((current_section, lead))

    # Scoped segments
    for idx, (start, end, sec) in enumerate(scopes):
        next_start = scopes[idx + 1][0] if idx + 1 < len(scopes) else len(text)
        payload = text[end:next_start].strip()
        segments.append((sec, payload))

    return segments

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
                provided_all: List[str] = []
                any_captured = False
                segment_results: List[Dict[str, Any]] = []

                for seg_section, payload in segments:
                    # Update conversational context to this segment's section
                    self.state.current_section = seg_section

                    # Navigation-only segment: skip extractor
                    if not payload.strip():
                        segment_results.append({
                            "section": seg_section, "note": "navigation_only", "provided_fields": []
                        })
                        continue

                    # Run the single extractor for this segment
                    ex = self.registry.get(seg_section)
                    out = ex.extract_dict(payload, temperature=0.0, max_tokens=300)

                    result_obj = out.get("result") or out
                    updates = (result_obj.get("updates") or {})
                    provided = out.get("provided_fields") or []

                    if provided:
                        any_captured = True
                        provided_all.extend(provided)

                        # Merge into state (prefer existing) with provenance
                        self.state = self.state.model_merge_updates(
                            updates,
                            policy="prefer_existing",
                            turn_id=_now_iso(),
                            timestamp=_now_iso(),
                            domain=seg_section,
                            extractor=ex.__class__.__name__,
                            model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                        )

                        # Aggregate a shallow echo of produced updates
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

                        segment_results.append({
                            "section": seg_section, "note": "captured",
                            "provided_fields": sorted(set(provided))
                        })
                    else:
                        segment_results.append({
                            "section": seg_section, "note": "no_capture", "provided_fields": []
                        })

                # Build turn result
                if any_captured:
                    result_payload = {
                        "updates": updates_aggregate,
                        "provided_fields": sorted(set(provided_all)),
                        "segments": segment_results,
                        "final_section": self.state.current_section,
                        "note": "captured",
                    }
                    ok = True
                else:
                    result_payload = {
                        "updates": {},
                        "provided_fields": [],
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
                result_payload = {
                    "stub": "REQUEST_FORWARDED_TO_SERVICE_AGENT",
                    "utterance": user_text
                }
                ok = True
            except Exception:
                routed_to, result_payload = _handle_not_implemented(intent)
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
        captures = parse_turn(output)
        self.state = self.state.update_provided_fields(captures)

        _write_log("TURN", {
            **output,
            "state_meta_provided_fields": self.state.meta.provided_fields,

        })
        return output

        return output
