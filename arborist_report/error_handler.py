# arborist_report/error_handler.py
"""
Unified, actionable error envelope for the Arborist Report Assistant.

This module defines a single, stable "error object" shape that travels in the
Coordinator TurnPacket at packet["error"] (or None when no error). It also
provides small helpers to construct, normalize, and log-friendly-wrap errors
consistently across Provide-Statement and Request-Service branches.

Error object contract (MUST NOT BREAK):
---------------------------------------
{
  "code": <ENUM>,              # stable, app-specific
  "origin": <str>,             # "intent" | "deterministic" | "backstop" | "extractor" | "merge" | "agent" | "io" | "unknown"
  "retryable": <bool>,         # can the user simply try again?
  "user_message": <str>,       # short, clear, user-safe message (rendered verbatim)
  "next_actions": <list[str]>, # 1–3 verbs TopAgent maps to quick replies
  "dev_message": <str|None>,   # terse technical reason, safe to log (not shown to users)
  "details": <dict>,           # diagnostics (exception type, model, thresholds…)
  "context": <dict>,           # e.g., {"section":"risks","service":"MAKE_REPORT_DRAFT"}
  "timestamp": <iso-utc>,      # when the error was produced
  "correlation_id": <str>      # ties together logs/metrics for this turn
}

Usage (Coordinator):
--------------------
from arborist_report.error_handler import (
    ErrorCode, ErrorOrigin, NextAction, make_error, wrap_legacy_error
)

# Hard failure example
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

# Soft clarify example (ok=True, service='CLARIFY', but still provide guidance)
soft = make_error(
    code=ErrorCode.ROUTER_BACKSTOP_AMBIGUOUS,
    origin=ErrorOrigin.BACKSTOP,
    retryable=True,
    user_message="Should I summarize a section, create an outline, make a draft, or apply a correction?",
    next_actions=[NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT, NextAction.MAKE_CORRECTION],
    details={"confidence": conf, "threshold": threshold},
)

# Backward compatibility for legacy string errors
err = wrap_legacy_error("Something went wrong.")
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union
from datetime import datetime, timezone
import uuid


# ----------------------------- Enums & constants -----------------------------

class ErrorCode(str, Enum):
    INTENT_UNAVAILABLE = "INTENT_UNAVAILABLE"
    ROUTER_DETERMINISTIC_ERROR = "ROUTER_DETERMINISTIC_ERROR"
    ROUTER_BACKSTOP_UNAVAILABLE = "ROUTER_BACKSTOP_UNAVAILABLE"
    ROUTER_BACKSTOP_AMBIGUOUS = "ROUTER_BACKSTOP_AMBIGUOUS"  # soft clarify (often ok=True)
    EXTRACTOR_FAILURE = "EXTRACTOR_FAILURE"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    AGENT_RENDER_FAILURE = "AGENT_RENDER_FAILURE"
    IO_PERSISTENCE_FAILURE = "IO_PERSISTENCE_FAILURE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"  # compatibility for legacy string errors


class ErrorOrigin(str, Enum):
    INTENT = "intent"
    DETERMINISTIC = "deterministic"
    BACKSTOP = "backstop"
    EXTRACTOR = "extractor"
    MERGE = "merge"
    AGENT = "agent"
    IO = "io"
    UNKNOWN = "unknown"


class NextAction(str, Enum):
    TRY_REPHRASE = "TRY_REPHRASE"
    ASK_SECTION = "ASK_SECTION"
    REQUEST_DRAFT = "REQUEST_DRAFT"
    MAKE_CORRECTION = "MAKE_CORRECTION"
    SWITCH_SECTION = "SWITCH_SECTION"
    RETRY_LATER = "RETRY_LATER"


# Canonical, operator-approved default user messages per code.
_DEFAULT_USER_MESSAGES: Mapping[ErrorCode, str] = {
    ErrorCode.INTENT_UNAVAILABLE: "I couldn’t detect intent just now. Try rephrasing or ask for a section summary.",
    ErrorCode.ROUTER_DETERMINISTIC_ERROR: "I couldn’t route that request. Which section do you want to work on?",
    ErrorCode.ROUTER_BACKSTOP_UNAVAILABLE: "I couldn’t resolve the request right now. Do you want a section summary, an outline, or a full draft?",
    ErrorCode.ROUTER_BACKSTOP_AMBIGUOUS: "Should I summarize a section, create an outline, make a draft, or apply a correction?",
    ErrorCode.EXTRACTOR_FAILURE: "I couldn’t pull structured details from that text. Want to try rephrasing or switch sections?",
    ErrorCode.MERGE_CONFLICT: "That update didn’t fit the report fields. I can apply a targeted correction instead.",
    ErrorCode.AGENT_RENDER_FAILURE: "I couldn’t generate that right now. Try again or request a different section.",
    ErrorCode.IO_PERSISTENCE_FAILURE: "Saved state may be delayed. You can continue; I’ll try again automatically.",
    ErrorCode.UNKNOWN_ERROR: "Something went wrong. Try rephrasing or ask for a section.",
}

# Canonical next-actions per code (used if caller doesn’t specify).
_DEFAULT_ACTIONS: Mapping[ErrorCode, Tuple[NextAction, ...]] = {
    ErrorCode.INTENT_UNAVAILABLE: (NextAction.TRY_REPHRASE, NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT),
    ErrorCode.ROUTER_DETERMINISTIC_ERROR: (NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT),
    ErrorCode.ROUTER_BACKSTOP_UNAVAILABLE: (NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT),
    ErrorCode.ROUTER_BACKSTOP_AMBIGUOUS: (NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT, NextAction.MAKE_CORRECTION),
    ErrorCode.EXTRACTOR_FAILURE: (NextAction.TRY_REPHRASE, NextAction.SWITCH_SECTION, NextAction.MAKE_CORRECTION),
    ErrorCode.MERGE_CONFLICT: (NextAction.MAKE_CORRECTION, NextAction.ASK_SECTION),
    ErrorCode.AGENT_RENDER_FAILURE: (NextAction.TRY_REPHRASE, NextAction.ASK_SECTION, NextAction.REQUEST_DRAFT),
    ErrorCode.IO_PERSISTENCE_FAILURE: (NextAction.RETRY_LATER,),
    ErrorCode.UNKNOWN_ERROR: (NextAction.TRY_REPHRASE,),
}


# ----------------------------- Utility helpers ------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_correlation_id(prefix: str = "turn") -> str:
    """
    Build a correlation id that can be grepped across coordinator logs and turn logs.
    The Coordinator can pass its own per-turn id here; otherwise we generate one.
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _ensure_actions(values: Optional[Sequence[Union[str, NextAction]]]) -> List[str]:
    if not values:
        return []
    out: List[str] = []
    for v in values:
        s = v.value if isinstance(v, NextAction) else str(v)
        if s and s not in out:
            out.append(s)
    # keep at most 3 per the UI guidance
    return out[:3]


# ------------------------------- Main factory --------------------------------

def make_error(
    *,
    code: Union[ErrorCode, str],
    origin: Union[ErrorOrigin, str] = ErrorOrigin.UNKNOWN,
    retryable: bool,
    user_message: Optional[str] = None,
    next_actions: Optional[Sequence[Union[str, NextAction]]] = None,
    dev_message: Optional[str] = None,
    details: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
    correlation_id: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Construct a fully-formed error object (dict) consistent with the app-wide contract.

    - `user_message` and `next_actions` are optional; if omitted, defaults are derived
      from the `code` using operator-approved copy.
    - `details` and `context` are pass-through diagnostics; avoid putting PII here.
    - `correlation_id`: pass the per-turn id if you have it; else a new id is generated.

    Returns:
        dict conforming to the error contract (see module docstring).
    """
    try:
        code_enum = ErrorCode(code)
    except Exception:
        code_enum = ErrorCode.UNKNOWN_ERROR

    try:
        origin_enum = ErrorOrigin(origin)
    except Exception:
        origin_enum = ErrorOrigin.UNKNOWN

    msg = (user_message or _DEFAULT_USER_MESSAGES.get(code_enum) or _DEFAULT_USER_MESSAGES[ErrorCode.UNKNOWN_ERROR]).strip()
    actions = _ensure_actions(next_actions) or list(_DEFAULT_ACTIONS.get(code_enum, (NextAction.TRY_REPHRASE,)))
    cid = correlation_id or new_correlation_id()
    ts = (now or _now_iso())

    # Ensure plain dicts (not MappingProxy) for JSON-ability
    det = dict(details or {})
    ctx = dict(context or {})

    return {
        "code": code_enum.value,
        "origin": origin_enum.value,
        "retryable": bool(retryable),
        "user_message": msg,
        "next_actions": actions,
        "dev_message": (dev_message or None),
        "details": det,
        "context": ctx,
        "timestamp": ts,
        "correlation_id": cid,
    }


# ------------------------- Backward compatibility ----------------------------

def wrap_legacy_error(message: str, *, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Wrap a legacy string error into the unified envelope with UNKNOWN_ERROR.
    Keeps UX consistent while older call sites are migrated.

    TopAgent will: show `user_message`, render default chip(s), and log dev info.
    """
    return make_error(
        code=ErrorCode.UNKNOWN_ERROR,
        origin=ErrorOrigin.UNKNOWN,
        retryable=False,
        user_message=str(message or "Unknown error."),
        next_actions=None,  # will fall back to TRY_REPHRASE
        dev_message=None,
        details={},
        context={},
        correlation_id=correlation_id,
    )


# ------------------------------- Introspection --------------------------------

def is_soft_ambiguous(error_obj: Optional[Mapping[str, Any]]) -> bool:
    """
    Return True if the error denotes a "soft" clarify case (often ok=True),
    which the UI should handle by offering choices rather than showing a failure state.
    """
    if not error_obj:
        return False
    return error_obj.get("code") == ErrorCode.ROUTER_BACKSTOP_AMBIGUOUS.value


def summarize_for_log(error_obj: Optional[Mapping[str, Any]]) -> str:
    """
    Produce a compact single-line summary suitable for coordinator_logs.
    """
    if not error_obj:
        return ""
    code = error_obj.get("code", "UNKNOWN")
    origin = error_obj.get("origin", "unknown")
    retryable = error_obj.get("retryable", False)
    cid = error_obj.get("correlation_id", "")
    return f"{code} origin={origin} retryable={retryable} cid={cid}"
