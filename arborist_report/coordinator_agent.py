"""
arborist_report.coordinator_agent
arborist_report/coordinator_agent.py
=================================

Coordinator for a single user turn of the Arborist Report Assistant.

This module exposes the `Coordinator` class plus a few small helpers. The
Coordinator is the **orchestrator** that takes raw user text, classifies intent,
routes to the appropriate extraction or service path, merges any structured
updates into the canonical `ReportState` with provenance, and returns a stable
**TurnPacket** for the top-level agent to render and persist.

High-level responsibilities
---------------------------
1) **Guard context** — `ReportContext` (arborist/customer/location) is required at
   construction time and is *read-only*. Any attempt to edit context via chat is
   deflected and reported as `routed_to="blocked_context_edit"`.

2) **Classify intent** — Calls `intent_model.classify_intent_llm` to decide between:
   - `PROVIDE_STATEMENT`  → extract structured facts into the state
   - `REQUEST_SERVICE`    → route to summaries, outline, draft, or corrections

3) **Provide-Statement path** — Parses the user text for **explicit scopes** using a
   light `scope: text` syntax (e.g., `"Risks: ...\nTargets: ..."`) with a
   **cursor-first fallback** (current section on state). For each (section, text)
   segment, it:
   - Retrieves the section extractor from `extractor_registry.default_registry()`
   - Invokes `extract_dict(...)` and **normalizes** the output to `{"updates": {...}}`
     without re-parsing JSON
   - Merges the updates into `ReportState` using **prefer-existing** semantics for
     scalars and **append** semantics for lists, emitting provenance rows
   - Aggregates per-segment notes (`captured` / `no_capture` / `navigation_only`)

4) **Request-Service path** — First uses the **deterministic** router
   (`service_router.classify_service`). If it returns `NONE`, runs the LLM
   backstop **as an extractor** (`models.ServiceRouterExtractor.extract_dict`),
   applying a configurable **confidence threshold** to accept or downgrade to
   `CLARIFY`. Supported services:
   - `SECTION_SUMMARY` (prose summary of one section)
   - `OUTLINE`         (explicit keyword "outline"; can be sectionless)
   - `MAKE_REPORT_DRAFT` (full report draft)
   - `MAKE_CORRECTION` (single-section corrections with overwrite semantics)
   - `CLARIFY` (insufficient signal to choose)

5) **Telemetry & logging** — Emits a compact, stable TurnPacket with router
   transparency (deterministic/backstop usage and confidence). Also writes a
   one-line JSON log via app_logger with the same payload.

TurnPacket contract (stable output shape)
-----------------------------------------
The return value of `Coordinator.handle_turn(user_text)` is a dict with keys:

    {
      "utterance": <str>,            # original user text
      "intent": "PROVIDE_STATEMENT" | "REQUEST_SERVICE" | "INTENT_ERROR",
      "routed_to": <str|None>,       # human-readable route summary
      "ok": <bool>,                  # execution success
      "result": {                    # "TurnPacket" for the top agent
        "service": <str|None>,       # e.g., "SECTION_SUMMARY", "OUTLINE", ...
        "section": <str|None>,       # e.g., "risks"
        "note": <str|None>,          # e.g., "captured" | "no_capture" | clarify msg
        "preview": {                 # used by top_agent for canvas hints
          "summary_text": <str|None>,
          "draft_excerpt": <str|None>
        },
        # (when Provide-Statement or Corrections apply)
        "updates": {"updates": {...}},    # normalized envelope applied (or empty)
        "applied": <bool>,                # True when updates were applied
        "applied_paths": [<str>, ...],    # dotted paths that changed
        "segments": [                     # per-segment capture notes
          {"section": <str>, "note": "captured"|"no_capture"|"navigation_only"},
          ...
        ],
        # (when Report Draft is generated)
        "draft": { ... }                  # full draft object from ReportAgent (optional)
      },
      "router": {
        "deterministic_hit": <bool|None>, # True if deterministic classifier chose a service
        "backstop_used": <bool|None>,     # True if LLM backstop was invoked
        "backstop_confidence": <float|None>, # numeric confidence from backstop
        "backstop_threshold": <float|None>,  # threshold used for accept/clarify decision
        "backstop_accept": <bool|None>       # True if backstop prediction was accepted
      },
      "error": <str|dict|None>,        # error (string legacy or structured object) when ok=False
      "correlation_id": <str>
    }

Notes on fields
---------------
- `result.preview.*` exists to support the UI and canvas writers in `top_agent`.
  Do not rename these keys without updating `packet_to_template(...)` and
  `TopChatAgent.handle(...)`.
- `result.draft` may contain the full draft payload (for persistence elsewhere);
  to keep logs small, prefer storing the full text in canvas (report.md) and
  only a short excerpt in `preview.draft_excerpt`.
- The `router` block is **safe to extend** with additional diagnostics; the
  top-level agent treats it as opaque and simply persists it via `LocalStore`.

Environment variables
---------------------
- `OPENAI_MODEL` — the model name to record in provenance for extractor/service
  calls (default `"gpt-4o-mini"` if not set).
- `ROUTING_BACKSTOP_MIN_CONF` — acceptance threshold for the LLM backstop
  classifier (default `"0.60"`). If the backstop’s `confidence` is lower than
  this value, the Coordinator returns `CLARIFY`.

Side effects
------------
- **State mutation**: On Provide-Statement captures and accepted Corrections, the
  Coordinator calls `ReportState.model_merge_updates(...)` to update the
  canonical state and write provenance rows. Section summaries and report drafts
  may also be persisted via dedicated helpers (`_persist_section_summary`).
- **Token accounting**: The Coordinator adds token usage reported by extractors
  and service agents into `ReportState` via `ReportState.add_tokens(...)`.

Error handling
--------------
Errors are handled through the error_handler module. Errors from all components produce an error object
such as:

Hard failure example

err = make_error(
    code=ErrorCode.AGENT_RENDER_FAILURE,
    origin=ErrorOrigin.AGENT,
    retryable=True,
    user_message="I couldn’t generate that right now. Try again or request a different section.",
    next_actions=[NextAction.TRY_REPHRASE, NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT],
    dev_message=str(exc),
    details={"component": "ReportAgent", "model": model_name},
    context={"service": "MAKE_REPORT_DRAFT"},
    correlation_id=turn_id,  # pass through the turn's id if you have it
)
Extensibility points
--------------------
- **Section extractors**: Provided by `extractor_registry.default_registry()`;
  to add/replace an extractor, modify the registry to return an object exposing
  `extract_dict(text, **kwargs)` that conforms to the normalized envelope.
- **Service agents**: `_render_section_report(...)` and `_render_report_draft(...)`
  encapsulate calls to `SectionReportAgent` and `ReportAgent`. These thin wrappers
  allow prompt/style/temperature tuning without changing Coordinator logic.
- **Routing policy**: Deterministic first via `service_router.classify_service`,
  then LLM backstop via `models.ServiceRouterExtractor`. Replace, adjust threshold,
  or add few-shots in the extractor without touching Coordinator.

Minimal usage example
---------------------
    >>> ctx = ReportContext(...)              # read-only job context
    >>> coord = Coordinator(context=ctx)
    >>> pkt = coord.handle_turn("Risks: low branch over driveway; Targets: playset nearby.")
    >>> pkt["ok"], pkt["result"]["applied_paths"]
    True, ["risks.items", "targets.items"]

    >>> pkt = coord.handle_turn("Summarize the Risks.")
    >>> pkt["result"]["service"], pkt["result"]["preview"]["summary_text"][:60]
    ("SECTION_SUMMARY", "Risks Summary: ...")

    >>> pkt = coord.handle_turn("make a full report draft")
    >>> pkt["result"]["service"], bool(pkt["result"]["preview"]["draft_excerpt"])
    ("MAKE_REPORT_DRAFT", True)

Implementation notes
--------------------
- The Coordinator normalizes extractor returns from multiple shapes:
  `{"parsed": <Model>}`, `{"result": {...}}`, `<Model>`, `<dict>` → unified
  `{"updates": {...}}`. This keeps the merge logic simple and stable.
- Provide-Statement aggregation merges **multiple scoped segments** in a single
  turn; when nothing is provided, the packet carries `note="no_capture"` to
  trigger a gentle clarification from the top-level agent.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from arborist_report.report_context import ReportContext
from arborist_report.report_state import (
    ReportState,
    NOT_PROVIDED,
)
from arborist_report.section_report_agent import SectionReportAgent
from arborist_report.report_agent import ReportAgent
from arborist_report.corrections_agent import CorrectionsAgent
from arborist_report.service_router import classify_service
# CHANGED: use extractor-style service router from models
from arborist_report.models import ServiceRouterExtractor
from arborist_report.intent_model import classify_intent_llm
from arborist_report.extractor_registry import default_registry
from arborist_report.error_handler import make_error, ErrorCode, ErrorOrigin, NextAction, new_correlation_id
from arborist_report.app_logger import log_event as _log_event
# from arborist_report.app_logger import log_turn_packet as _log_turn

# ----------------------------- small utils -----------------------------

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _empty_turnpacket() -> Dict[str, Any]:
    return {
        "service": None,
        "section": None,
        "note": None,
        "preview": {"summary_text": None, "draft_excerpt": None},
    }

def _is_context_edit(text: str) -> bool:
    t = (text or "").lower()
    # crude guard; your existing extractor/intent already catches most
    return any(k in t for k in ("arborist", "customer", "location", "job_id"))

def _parse_scoped_segments(user_text: str, current_section: str) -> List[Tuple[str, str]]:
    """
    Very light parser for 'scope: text' segments.
    Fallback: single tuple with current section.
    """
    lines = [ln.strip() for ln in (user_text or "").split("\n") if ln.strip()]
    out: List[Tuple[str, str]] = []
    for ln in lines:
        if ":" in ln:
            head, tail = ln.split(":", 1)
            sec = head.strip().lower().replace(" ", "_")
            txt = tail.strip()
            if sec in {"area_description","tree_description","targets","risks","recommendations"}:
                out.append((sec, txt))
                continue
        # not a scoped line → accumulate later
        out.append((current_section, ln))
    if not out:
        out.append((current_section, user_text or ""))
    return out

def _flatten_provided_paths(envelope: Dict[str, Any]) -> List[str]:
    """
    envelope: {"updates": {...}} → list of dotted paths that are provided (non-sentinel / non-empty).
    """
    def provided(v: Any) -> bool:
        if isinstance(v, str): return v != NOT_PROVIDED and bool(v.strip())
        if isinstance(v, list): return len(v) > 0
        if isinstance(v, dict): return any(provided(x) for x in v.values())
        return v is not None

    paths: List[str] = []
    def walk(prefix: str, obj: Any) -> None:
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump(exclude_none=False)
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{prefix}.{k}" if prefix else k
                walk(p, v)
        else:
            if provided(obj):
                paths.append(prefix)

    root = envelope.get("updates", envelope) if isinstance(envelope, dict) else {}
    walk("", root)
    return sorted(set(paths))

def _deep_merge_dicts(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge_dicts(dst[k], v)
        else:
            dst[k] = v

# ------------------------- context merge guards (new) -------------------------

ALLOWED_SECTIONS = {
    "area_description", "tree_description", "targets", "risks", "recommendations"
}
CONTEXT_KEYS = {"arborist_info", "customer_info", "location"}

def _strip_disallowed_roots(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keep only allowed report sections at the top-level of {"updates": {...}}.
    Drop any context-like roots if they appear.
    """
    if not isinstance(envelope, dict):
        return {"updates": {}}
    root = envelope.get("updates", envelope)
    if hasattr(root, "model_dump"):
        root = root.model_dump(exclude_none=False)
    if not isinstance(root, dict):
        return {"updates": {}}

    cleaned: Dict[str, Any] = {}
    for k, v in root.items():
        if k in ALLOWED_SECTIONS:
            cleaned[k] = v
        elif k in CONTEXT_KEYS:
            # Block writes to context; comment left for traceability.
            # (Previously, context extractors could surface these; now ignored.)
            continue
        else:
            # Unknown top-level keys are ignored to prevent schema drift.
            continue
    return {"updates": cleaned}

def _strip_context_paths(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """
    Defensive scrub: if any nested object contains context-named keys, remove them.
    This is belt-and-suspenders in case an extractor nests context blocks.
    """
    def walk(obj: Any) -> Any:
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump(exclude_none=False)
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k in CONTEXT_KEYS:
                    # Drop nested context blocks
                    continue
                out[k] = walk(v)
            return out
        if isinstance(obj, list):
            return [walk(x) for x in obj]
        return obj

    if not isinstance(envelope, dict):
        return {"updates": {}}
    root = envelope.get("updates", envelope)
    cleaned = walk(root)
    return {"updates": cleaned if isinstance(cleaned, dict) else {}}


# --- noise pruning: drop default-y filler and unchanged values before merge/packet ---

NOISE_STRINGS = {"not provided", "n/a", "na", "none", "none provided"}

def _is_noise_scalar(v: Any) -> bool:
    """
    Treat common extractor defaults as 'not provided' so they don't pollute updates.
    """
    if v is None:
        return True
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return True
        return s.lower() in NOISE_STRINGS
    if isinstance(v, list):
        return len(v) == 0
    return False

def _prune_noise_and_unchanged(envelope: Dict[str, Any], *, state: "ReportState") -> Dict[str, Any]:
    """
    Given {"updates": {...}}, drop keys that are:
      - clearly noise (e.g., 'Not provided', empty string/list), or
      - equal to the current state's value at the same dotted path.
    Returns a new {"updates": pruned_dict}.
    """
    root = envelope.get("updates", {}) if isinstance(envelope, dict) else {}

    # Snapshot current state as a plain dict for diff checks
    try:
        state_dict = state.model_dump(exclude_none=False)
    except Exception:
        state_dict = {}

    def get_state_at_path(path: str) -> Any:
        cur = state_dict
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    def walk(obj: Any, prefix: str) -> Optional[Any]:
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump(exclude_none=False)

        if isinstance(obj, dict):
            acc: Dict[str, Any] = {}
            for k, v in obj.items():
                path = f"{prefix}.{k}" if prefix else k
                kept = walk(v, path)
                if kept is not None:
                    acc[k] = kept
            return acc or None

        # Scalar/list: drop if noise or unchanged vs state
        if _is_noise_scalar(obj):
            return None
        current = get_state_at_path(prefix)
        try:
            if obj == current:
                return None
        except Exception:
            pass
        return obj

    kept = walk(root, "")
    return {"updates": kept or {}}

# --- shape normalizer: make extractor output look like {"updates": {...}} and match ReportState shapes

def _normalize_updates_to_state_shapes(*, updates_envelope: Dict[str, Any], state: ReportState) -> Dict[str, Any]:
    """
    Accepts loose extractor output, returns {"updates": <dict>} with shapes aligned to ReportState.
    - Leaves scalar vs list fields sensible (never append NOT_PROVIDED into lists).
    - Never raises if given dicts; returns empty updates if unusable.
    """
    if not isinstance(updates_envelope, dict):
        return {"updates": {}}
    root = updates_envelope.get("updates", updates_envelope)
    if hasattr(root, "model_dump"):
        root = root.model_dump(exclude_none=False)
    if not isinstance(root, dict):
        return {"updates": {}}

    # Light pass: coerce empty strings → NOT_PROVIDED; keep lists/lists; drop Nones.
    def clean(v: Any) -> Any:
        if v is None:
            return NOT_PROVIDED
        if isinstance(v, str):
            s = v.strip()
            return s if s else NOT_PROVIDED
        if isinstance(v, list):
            return [clean(x) for x in v if clean(x) != NOT_PROVIDED]
        if hasattr(v, "model_dump"):
            return clean(v.model_dump(exclude_none=False))
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        return v

    cleaned = clean(root)

    # Nothing fancy: we rely on model_merge_updates to apply list-append vs scalar semantics.
    return {"updates": cleaned if isinstance(cleaned, dict) else {}}

def _blocked_context_response(user_text: str) -> Dict[str, Any]:
    return {
        "utterance": user_text,
        "intent": "PROVIDE_STATEMENT",
        "routed_to": "blocked_context_edit",
        "ok": True,
        "result": _empty_turnpacket(),
        "router": {"deterministic_hit": None, "backstop_used": None, "backstop_confidence": None},
        "error": None,
    }

# ------------------------------ Coordinator ------------------------------

class Coordinator:
    """
    Coordinator v2:
      * Requires ReportContext at construction (read-only).
      * Deflects attempted context edits.
      * Cursor-first routing with explicit-scope override, including multi-scope.
      * Extractors run through ModelFactory (inside each extractor) and can return:
            - {"parsed": <BaseModel>, "raw": <str>, "tokens": {...}, "model": "..."}
            - {"result": {...}}  (dict or BaseModel)
            - <BaseModel>
            - <dict>
        All shapes are normalized to {"updates": {...}} without JSON re-parsing.
    """

    def __init__(self, context: ReportContext):
        if context is None:
            raise ValueError("ReportContext is required")
        self.context = context
        self.state = ReportState()
        self.registry = default_registry()

        # System log: context presence snapshot (non-turn)
        _log_event(
            "Coordinator.CONTEXT_LOADED",
            {
                "arborist_loaded": self.context.arborist is not None,
                "customer_loaded": self.context.customer is not None,
                "location_loaded": self.context.location is not None,
            },
        )

    # ------------------------------- Internals --------------------------------

    def _filter_missing_with_context(self, missing: Dict[str, List[str]]) -> Dict[str, List[str]]:
        if not isinstance(missing, dict):
            return missing
        filtered = dict(missing)
        for sec in ["arborist_info", "customer_info", "location"]:
            filtered.pop(sec, None)
        return filtered

    def _envelope_has_provided(self, updates_envelope: Dict[str, Any]) -> bool:
        if not updates_envelope:
            return False
        root = updates_envelope.get("updates", updates_envelope)
        if not isinstance(root, dict):
            return False

        def walk(v: Any) -> bool:
            if isinstance(v, dict):
                return any(walk(x) for x in v.values())
            if isinstance(v, list):
                return len(v) > 0
            if isinstance(v, str):
                return v != NOT_PROVIDED and bool(v.strip())
            return v is not None

        return walk(root)

    # Normalize any extractor return into {"updates": {...}}
    def _normalize_extractor_return(self, ex_out: Any) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """
        Returns (updates_envelope, tokens)
        """
        tokens = {"in": 0, "out": 0}
        payload = ex_out

        # Try to capture tokens if present
        if isinstance(payload, dict) and "tokens" in payload and isinstance(payload["tokens"], dict):
            t = payload["tokens"]
            tokens = {"in": int(t.get("in", 0) or 0), "out": int(t.get("out", 0) or 0)}

        # Unwrap to the object/dict containing fields
        candidate = None
        if isinstance(payload, dict):
            candidate = payload.get("parsed") or payload.get("result") or payload
        else:
            candidate = payload

        # Convert candidate → plain dict
        if hasattr(candidate, "model_dump"):
            try:
                candidate = candidate.model_dump(exclude_none=False)
            except Exception:
                pass

        if not isinstance(candidate, dict):
            return {"updates": {}}, tokens

        # If it already looks like {"updates": {...}} keep it; else treat dict as updates root
        env = candidate if "updates" in candidate else {"updates": candidate}
        env = _normalize_updates_to_state_shapes(updates_envelope=env, state=self.state)
        return env, tokens

    # ------------------------------- Main API ---------------------------------

    def handle_turn(self, user_text: str) -> Dict[str, Any]:
        """
        Returns a payload with stable keys:
          { utterance, intent, routed_to, ok, result (TurnPacket), router, error }
        """
        _cid = new_correlation_id("turn")
        self.state.current_text = user_text
        backstop_accept: Optional[bool] = None  # ensure defined for final router block

        # Router transparency defaults
        deterministic_hit: Optional[bool] = None
        backstop_used: Optional[bool] = None
        backstop_confidence: Optional[float] = None
        backstop_threshold: Optional[float] = None

        # 1) Intent
        try:
            ires = classify_intent_llm(user_text)  # returns IntentCallResult
            intent = ires.intent
            self.state = self.state.add_tokens("intent_llm", ires.tokens)
        except Exception as e:
            err = make_error(
                code=ErrorCode.INTENT_UNAVAILABLE,
                origin=ErrorOrigin.INTENT,
                retryable=True,
                user_message="I couldn’t detect what you wanted to do. Try rephrasing or ask for a section summary.",
                next_actions=[NextAction.TRY_REPHRASE, NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT],
                dev_message=f"{type(e).__name__}: {e}",
                details={"component": "classify_intent_llm"},
                context={},
                correlation_id=_cid,
            )
            payload = {
                "utterance": user_text,
                "intent": "INTENT_ERROR",
                "routed_to": None,
                "ok": False,
                "result": _empty_turnpacket(),
                "router": {
                    "deterministic_hit": None,
                    "backstop_used": None,
                    "backstop_confidence": None,
                },
                "error": err,
                "correlation_id": _cid,
            }
            # _log_turn(payload, correlation_id=_cid)
            return payload

        # 2) Context-edit deflection
        if intent == "PROVIDE_STATEMENT" and _is_context_edit(user_text):
            out = _blocked_context_response(user_text)
            out["correlation_id"] = _cid
            # _log_turn(out, correlation_id=_cid)
            return out

        routed_to: Optional[str] = None
        ok = False
        result_payload: Optional[Dict[str, Any]] = None
        error: Optional[str] = None

        # 3) Provide-Statement path
        if intent == "PROVIDE_STATEMENT":
            routed_to = "cursor → extractor (with explicit-scope segments)"
            try:
                segments = _parse_scoped_segments(user_text, self.state.current_section)
                if not segments:
                    segments = [(self.state.current_section, user_text or "")]

                updates_aggregate: Dict[str, Any] = {}
                any_captured = False
                segment_results: List[Dict[str, Any]] = []

                for seg_section, payload_text in segments:
                    self.state.current_section = seg_section

                    if not payload_text.strip():
                        segment_results.append({"section": seg_section, "note": "navigation_only"})
                        continue

                    # Run extractor (LLM/Outlines under the hood)
                    ex = self.registry.get(seg_section)
                    ex_out = ex.extract_dict(payload_text, temperature=0.0, max_tokens=300)

                    # Normalize shapes (support dict or BaseModel returns)
                    env, tok = self._normalize_extractor_return(ex_out)
                    self.state = self.state.add_tokens(f"extractor:{seg_section}", tok)
                    # Prune noise/unchanged before merging
                    env = _prune_noise_and_unchanged(env, state=self.state)

                    # NEW: hard-block context writes and unknown roots
                    env = _strip_disallowed_roots(env)
                    env = _strip_context_paths(env)

                    # Apply into state
                    self.state = self.state.model_merge_updates(
                        env,
                        policy="prefer_existing",
                        turn_id=_now_iso(),
                        timestamp=_now_iso(),
                        domain=seg_section,
                        extractor=ex.__class__.__name__,
                        model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                        segment_text=payload_text,
                    )

                    captured_this_segment = self._envelope_has_provided(env)
                    any_captured = any_captured or captured_this_segment

                    inner = env.get("updates", {})
                    if inner:
                        if not updates_aggregate:
                            updates_aggregate = dict(inner)
                        else:
                            _deep_merge_dicts(updates_aggregate, inner)

                    segment_results.append(
                        {"section": seg_section, "note": "captured" if captured_this_segment else "no_capture"}
                    )

                if any_captured:
                    applied_paths = _flatten_provided_paths({"updates": updates_aggregate})
                    result_payload = {
                        **_empty_turnpacket(),
                        "service": None,
                        "section": self.state.current_section,
                        "note": "captured",
                        "updates": {"updates": updates_aggregate} if updates_aggregate else {},
                        "applied": True,
                        "applied_paths": applied_paths or [],
                        "segments": segment_results,
                    }
                    ok = True
                else:
                    result_payload = {
                        **_empty_turnpacket(),
                        "service": None,
                        "section": self.state.current_section,
                        "note": "no_capture",
                        "updates": {},
                        "applied": False,
                        "applied_paths": [],
                        "segments": segment_results,
                    }
                    ok = True

            except Exception as e:
                # Treat unexpected failures during extraction/merge as extractor failures by default.
                err_obj = make_error(
                    code=ErrorCode.EXTRACTOR_FAILURE,
                    origin=ErrorOrigin.EXTRACTOR,
                    retryable=True,
                    user_message="I couldn’t pull structured details from that text. Want to try rephrasing or switch sections?",
                    next_actions=[NextAction.TRY_REPHRASE, NextAction.SWITCH_SECTION, NextAction.MAKE_CORRECTION],
                    dev_message=f"{type(e).__name__}: {e}",
                    details={"section": getattr(self.state, 'current_section', None)},
                    context={"section": getattr(self.state, 'current_section', None)},
                    correlation_id=_cid,
                )
                error = err_obj["user_message"]
                result_payload = _empty_turnpacket()
                ok = False
                payload = {
                    "utterance": user_text, "intent": intent, "routed_to": routed_to, "ok": ok,
                    "result": result_payload,
                    "router": {"deterministic_hit": None, "backstop_used": None, "backstop_confidence": None},
                    "error": err_obj,
                    "correlation_id": _cid,
                }
                # _log_turn(payload, correlation_id=_cid)
                return payload

        # 4) Request-Service path
        elif intent == "REQUEST_SERVICE":
            routed_to = "RequestService"
            try:
                # deterministic first
                service, section = classify_service(user_text)
                deterministic_hit = (service != "NONE")

                # LLM backstop if NONE
                if service == "NONE":
                    try:
                        # Resolve threshold (default 0.60)
                        backstop_threshold = float(os.getenv("ROUTING_BACKSTOP_MIN_CONF", "0.60"))

                        # Run extractor-style service router
                        srx = ServiceRouterExtractor()
                        out = srx.extract_dict(user_text, temperature=0.0, max_tokens=256)
                        # Token accounting
                        self.state = self.state.add_tokens("service_backstop",
                                                           out.get("tokens", {"in": 0, "out": 0}))
                        backstop_used = True
                        route = out.get("result", {})  # {"service","section","confidence"}
                        confidence = float(route.get("confidence", 0.0) or 0.0)
                        backstop_confidence = confidence  # for router telemetry

                        # Accept only if confidence >= threshold AND not NONE
                        pred_service = route.get("service", "NONE")
                        pred_section = route.get("section")
                        backstop_accept = bool(confidence >= backstop_threshold and pred_service != "NONE")

                        if backstop_accept:
                            service = pred_service
                            section = pred_section
                        else:
                            service = "CLARIFY"
                            section = None

                    except Exception as e:
                        # Hard backstop failure: return structured error, keep router telemetry
                        err_obj = make_error(
                            code=ErrorCode.ROUTER_BACKSTOP_UNAVAILABLE,
                            origin=ErrorOrigin.BACKSTOP,
                            retryable=True,
                            user_message="I couldn’t resolve that request right now. Do you want a section summary, an outline, or a full draft?",
                            next_actions=[NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT],
                            dev_message=f"{type(e).__name__}: {e}",
                            details={"component": "ServiceRouterExtractor"},
                            correlation_id=_cid,
                        )
                        payload = {
                            "utterance": user_text,
                            "intent": intent,
                            "routed_to": "RequestService",
                            "ok": False,
                            "result": _empty_turnpacket(),
                            "router": {
                                "deterministic_hit": deterministic_hit,
                                "backstop_used": True,
                                "backstop_confidence": None,
                                "backstop_threshold": backstop_threshold,
                                "backstop_accept": None,
                            },
                            "error": err_obj,
                            "correlation_id": _cid,
                        }
                        # _log_turn(payload, correlation_id=_cid)
                        return payload

                routed_to = "RequestService → deterministic → llm_backstop" if backstop_used else "RequestService"

                # Execute service
                if service == "SECTION_SUMMARY":
                    if not section:
                        result_payload = {
                            **_empty_turnpacket(),
                            "service": "CLARIFY",
                            "section": None,
                            "note": "Which section should I summarize?",
                        }
                        ok = True
                    else:
                        render = self._render_section_report(
                            section=section,
                            mode="prose",
                            reference_text=self.state.current_text,
                            temperature=0.3,
                            include_payload=True,
                        )
                        self.state = self.state.add_tokens(
                            f"section_agent:{section}", render.get("tokens", {"in": 0, "out": 0})
                        )

                        text = str(render.get("text") or "").strip()
                        payload = render.get("payload") or {}
                        turn_id = _now_iso()
                        self.state = _persist_section_summary(
                            state=self.state,
                            section=section,
                            text=text,
                            payload=payload,
                            turn_id=turn_id,
                            model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                        )
                        result_payload = {
                            **_empty_turnpacket(),
                            "service": "SECTION_SUMMARY",
                            "section": section,
                            "note": None,
                            "preview": {"summary_text": text, "draft_excerpt": None},
                            "render": render,
                        }
                        ok = True

                elif service == "OUTLINE":
                    sec = section or getattr(self.state, "current_section", None)
                    if not sec:
                        result_payload = {
                            **_empty_turnpacket(),
                            "service": "CLARIFY",
                            "section": None,
                            "note": "No section selected. Which section should I outline?",
                        }
                        ok = True
                    else:
                        render = self._render_section_report(
                            section=sec,
                            mode="outline",
                            reference_text=self.state.current_text,
                            include_payload=True,
                        )
                        self.state = self.state.add_tokens(
                            f"section_agent:{sec}", render.get("tokens", {"in": 0, "out": 0})
                        )

                        outline_lines = list(render.get("outline") or [])
                        text = "\n".join(outline_lines).strip()
                        payload = render.get("payload") or {}
                        turn_id = _now_iso()
                        self.state = _persist_section_summary(
                            state=self.state,
                            section=sec,
                            text=text,
                            payload=payload,
                            turn_id=turn_id,
                            model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                        )
                        result_payload = {
                            **_empty_turnpacket(),
                            "service": "OUTLINE",
                            "section": sec,
                            "note": None,
                            "preview": {"summary_text": text, "draft_excerpt": None},
                            "render": render,
                        }
                        ok = True

                elif service == "MAKE_CORRECTION":
                    if not section:
                        result_payload = {
                            **_empty_turnpacket(),
                            "service": "CLARIFY",
                            "section": None,
                            "note": "Which section should I correct?",
                        }
                        ok = True
                    else:
                        corr = CorrectionsAgent()
                        run_out = corr.run(
                            section=section,
                            text=user_text,
                            state=self.state,
                            policy="last_write",
                            temperature=0.0,
                            max_tokens=300,
                        )
                        self.state = self.state.add_tokens(
                            f"corrections_agent:{section}", run_out.get("tokens", {"in": 0, "out": 0})
                        )
                        updates_env = run_out if "updates" in run_out else {"updates": (run_out or {})}
                        # Prune before apply
                        updates_env = _prune_noise_and_unchanged(updates_env, state=self.state)
                        # NEW: hard-block context writes and unknown roots
                        updates_env = _strip_disallowed_roots(updates_env)
                        updates_env = _strip_context_paths(updates_env)


                        applied = self._envelope_has_provided(updates_env)

                        now = _now_iso()
                        if applied:
                            self.state = self.state.model_merge_updates(
                                updates_env,
                                policy="last_write",
                                turn_id=now,
                                timestamp=now,
                                domain=section,
                                extractor="CorrectionsAgent",
                                model_name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                                segment_text=user_text,
                            )

                        result_payload = {
                            **_empty_turnpacket(),
                            "service": "MAKE_CORRECTION",
                            "section": section,
                            "note": "captured" if applied else "no_capture",
                            "updates": updates_env,
                            "applied": bool(applied),
                            "applied_paths": _flatten_provided_paths(updates_env) if applied else [],
                        }
                        ok = True

                elif service == "MAKE_REPORT_DRAFT":
                    render = self._render_report_draft(temperature=0.35, style=None)
                    self.state = self.state.add_tokens("report_agent", render.get("tokens", {"in": 0, "out": 0}))
                    preview = (render.get("draft_text", "")[:280]) if isinstance(render, dict) else ""
                    result_payload = {
                        **_empty_turnpacket(),
                        "service": "MAKE_REPORT_DRAFT",
                        "section": None,
                        "note": None,
                        "draft": render,
                        "preview": {"summary_text": None, "draft_excerpt": preview},
                    }
                    ok = True

                else:
                    # CLARIFY or NONE falls through here
                    note_text = None
                    if service == "CLARIFY":
                        note_text = "Please specify: section summary (which section?), outline (which section?), full report draft, or a correction (which section?)."
                    result_payload = {
                        **_empty_turnpacket(),
                        "service": service,
                        "section": section,
                        "note": note_text,
                    }
                    ok = True

            except Exception as e:
                err_obj = make_error(
                    code=ErrorCode.ROUTER_DETERMINISTIC_ERROR,
                    origin=ErrorOrigin.DETERMINISTIC,
                    retryable=True,
                    user_message="I couldn’t route that request. Which section do you want to work on?",
                    next_actions=[NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT],
                    dev_message=f"{type(e).__name__}: {e}",
                    correlation_id=_cid,
                )
                payload = {"utterance": user_text, "intent": intent, "routed_to": routed_to, "ok": False,
                           "result": _empty_turnpacket(),
                           "router": {"deterministic_hit": deterministic_hit,
                                      "backstop_used": backstop_used,
                                      "backstop_confidence": backstop_confidence,
                                      "backstop_threshold": backstop_threshold,
                                      "backstop_accept": backstop_accept},
                           "error": err_obj, "correlation_id": _cid}
                # _log_turn(payload, correlation_id=_cid)
                return payload

        # 5) Log and return (stable TurnPacket)
        payload = {
            "utterance": user_text,
            "intent": intent,
            "routed_to": routed_to,
            "ok": ok,
            "result": result_payload or _empty_turnpacket(),
            "router": {
                "deterministic_hit": deterministic_hit if intent == "REQUEST_SERVICE" else None,
                "backstop_used": backstop_used if intent == "REQUEST_SERVICE" else None,
                "backstop_confidence": backstop_confidence if intent == "REQUEST_SERVICE" else None,
                "backstop_threshold": (
                    backstop_threshold
                    if intent == "REQUEST_SERVICE" and backstop_used
                    else None
                ),
                "backstop_accept": backstop_accept if intent == "REQUEST_SERVICE" else None,
            },
            "error": error,
            "correlation_id": _cid,
        }
        # _log_turn(payload, correlation_id=_cid)
        return payload

    # ---------------------------- Thin wrappers --------------------------------

    def _render_section_report(
        self,
        *,
        section: str,
        mode: str,  # "prose" | "outline"
        reference_text: str = "",
        style: Optional[Dict[str, Any]] = None,
        include_payload: bool = False,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        agent = SectionReportAgent()
        return agent.run(
            section=section,
            state=self.state,
            reference_text=reference_text,
            mode=mode,
            temperature=temperature,
            style=style,
            include_payload=include_payload,
        )

    def _render_report_draft(
        self,
        *,
        temperature: float = 0.35,
        style: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        agent = ReportAgent()
        provenance = self._get_provenance_events()
        return agent.run(
            mode="draft",
            state=self.state,
            provenance=provenance,
            temperature=temperature,
            style=style or {},
        )

    def _get_provenance_events(self) -> List[Any]:
        for attr in ("provenance", "provenance_events"):
            v = getattr(self.state, attr, None)
            if v:
                return list(v) if isinstance(v, (list, tuple)) else [v]
        return []

# ---------------------- summary persist helper (unchanged) ----------------------

def _persist_section_summary(
    *,
    state: ReportState,
    section: str,
    text: str,
    payload: Dict[str, Any],
    turn_id: str,
    model_name: str,
) -> ReportState:
    from arborist_report.report_state import SectionSummaryState, SectionSummaryInputs

    inputs = SectionSummaryInputs.make(
        section=section, section_state=payload.get("snapshot", {}), reference_text=payload.get("reference_text", ""), provided_paths=payload.get("provided_paths", [])
    )
    summary = SectionSummaryState(
        text=text,
        updated_at=_now_iso(),
        updated_by="llm",
        based_on_turnid=turn_id,
        inputs=inputs,
    )
    return state.set_section_summary(section, summary=summary, turn_id=turn_id, model_name=model_name)
