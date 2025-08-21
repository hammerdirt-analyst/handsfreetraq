#!/usr/bin/env python3
# agent_graph.py — Coordinator v1 (persistent state + logging)
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Literal

from intent_llm import classify_intent_llm

# Outlines-backed model factory (same one you use in otest / structured probe)
from models2 import ModelFactory

# Direct extractors (verbatim-only schema; each returns {"updates": {...}, "provided_fields": [...]})
from models2 import (
    ArboristInfoExtractor,
    CustomerInfoExtractor,
    TreeDescriptionExtractor,
    RisksExtractor,
)

# >>> State lives here <<<
from report_state import ReportState

# --------------------------- config / constants ------------------------------

COORD_LOG_PATH = "coordinator-tests.txt"
STATE_LOG_PATH = "state_logs.txt"
NOT_PROVIDED = "Not provided"

# --------------------------- small utils ------------------------------------

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _append_log(path: str, header: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("=" * 64 + "\n")
        f.write(f"[{_now_iso()}] {header}\n")
        f.write("-" * 64 + "\n")
        f.write(json.dumps(payload, indent=2, ensure_ascii=False))
        f.write("\n\n")


def _compute_presence(updates_envelope: Dict[str, Any]) -> List[str]:
    """A field is 'provided' if a string != NOT_PROVIDED or a list is non-empty."""
    out: List[str] = []
    upd = updates_envelope.get("updates") or {}
    if not isinstance(upd, dict):
        return out

    def walk(prefix: str, obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(obj, list):
            if len(obj) > 0:
                out.append(prefix)
        else:
            if isinstance(obj, str) and obj != NOT_PROVIDED:
                out.append(prefix)

    for section, payload in upd.items():
        if isinstance(payload, dict):
            walk(section, payload)
    return sorted(set(out))


def _deep_merge(dst: Dict[str, Any], src: Dict[str, Any]) -> None:
    """In-place deep merge (src -> dst). Dicts recurse; scalars overwrite."""
    for k, v in (src or {}).items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def _state_to_compact_echo(state: ReportState) -> Dict[str, Any]:
    """Tiny snapshot for logs; adjust as needed."""
    try:
        d = state.model_dump()
    except Exception:
        # best-effort
        try:
            d = state.__dict__
        except Exception:
            d = {}
    return {
        "arborist_info.name": (((d.get("arborist_info") or {}).get("name")) if isinstance(d.get("arborist_info"), dict) else None),
        "customer_info.address.city": (((((d.get("customer_info") or {}).get("address")) or {}).get("city"))
                                       if isinstance(d.get("customer_info"), dict) and isinstance((d.get("customer_info") or {}).get("address"), dict) else None),
        "tree_description.dbh_in": (((d.get("tree_description") or {}).get("dbh_in"))
                                    if isinstance(d.get("tree_description"), dict) else None),
        "tree_description.height_ft": (((d.get("tree_description") or {}).get("height_ft"))
                                       if isinstance(d.get("tree_description"), dict) else None),
    }


# -------------------- LLM data-domain classifier -----------------------------

DomainLabel = Literal["arborist_info", "customer_info", "tree_description", "risks"]

from pydantic import BaseModel, Field, ConfigDict

class DomainSchema(BaseModel):
    domains: List[DomainLabel] = Field(...)
    model_config = ConfigDict(extra="forbid")

def classify_data_domains_llm(text: str) -> List[str]:
    """One Outlines call via ModelFactory → list of domains to run."""
    model = ModelFactory.get()
    prompt = (
        "You are a router for an arborist report agent. "
        "From the user message, choose ALL relevant data sections from this set: "
        "['arborist_info','customer_info','tree_description','risks'].\n"
        "Output ONLY JSON matching: {\"domains\": [ ... ]}\n\n"
        f"User message:\n{text}\n"
    )
    raw = model(prompt, DomainSchema, temperature=0.0, max_tokens=64)
    parsed: DomainSchema = DomainSchema.model_validate_json(raw)
    return list(parsed.domains or [])


# ----------------------------- WHAT'S LEFT ----------------------------------

def compute_whats_left_from_state(state: ReportState) -> Dict[str, List[str]]:
    """
    Simple 'what's left' that walks state and returns paths with NOT_PROVIDED or empty lists.
    """
    try:
        d = state.model_dump()
    except Exception:
        d = getattr(state, "__dict__", {}) or {}

    missing: Dict[str, List[str]] = {}

    def walk(prefix: str, obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(obj, list):
            if len(obj) == 0:
                sec = prefix.split(".", 1)[0]
                missing.setdefault(sec, []).append(prefix)
        else:
            if isinstance(obj, str) and obj == NOT_PROVIDED:
                sec = prefix.split(".", 1)[0]
                missing.setdefault(sec, []).append(prefix)

    walk("", d)
    return {k: sorted(v) for k, v in missing.items() if v}


# ----------------------------- Coordinator ----------------------------------

def _handle_not_implemented(intent: str) -> Tuple[str, Dict[str, Any]]:
    mapping = {
        "REQUEST_SUMMARY": ("ReportNode", {"stub": "SUMMARY_NOT_IMPLEMENTED"}),
        "REQUEST_REPORT": ("ReportNode", {"stub": "REPORT_NOT_IMPLEMENTED"}),
        "ASK_FIELD": ("None", {"stub": "UNHANDLED_INTENT"}),
        "ASK_QUESTION": ("None", {"stub": "UNHANDLED_INTENT"}),
        "SMALL_TALK": ("None", {"stub": "UNHANDLED_INTENT"}),
    }
    return mapping.get(intent, ("None", {"stub": "UNHANDLED_INTENT"}))


class Coordinator:
    """
    Minimal coordinator with persistent ReportState:
      1) accept text
      2) classify intent (LLM-only)
      3) if PROVIDE_DATA → LLM domain routing → run direct extractors
      4) deep-merge updates into self.state
      5) log turn + compact state snapshot
    """

    def __init__(self) -> None:
        self.state = ReportState()
        self._extractors: Dict[str, Any] = {
            "arborist_info": ArboristInfoExtractor(),
            "customer_info": CustomerInfoExtractor(),
            "tree_description": TreeDescriptionExtractor(),
            "risks": RisksExtractor(),
        }

    def _merge_into_state(self, updates_aggregate: Dict[str, Any]) -> None:
        """Deep-merge dict updates into ReportState (pydantic-friendly)."""
        # 1) dump current state to dict
        try:
            data = self.state.model_dump()
        except Exception:
            data = getattr(self.state, "__dict__", {}) or {}

        # 2) deep merge
        _deep_merge(data, updates_aggregate)

        # 3) revalidate → new ReportState
        new_state = None
        for ctor in (
            getattr(ReportState, "model_validate", None),
            getattr(ReportState, "model_validate_json", None),
        ):
            if callable(ctor):
                try:
                    new_state = ctor(data)  # type: ignore[arg-type]
                    break
                except Exception:
                    pass
        if new_state is None:
            try:
                new_state = ReportState(**data)  # type: ignore[arg-type]
            except Exception:
                # last resort: keep old state if validation fails
                return

        self.state = new_state

    def _log_state_snapshot(self, turn_info: Dict[str, Any]) -> None:
        echo = _state_to_compact_echo(self.state)
        payload = {
            "turn": turn_info,
            "state_echo": echo,
        }
        _append_log(STATE_LOG_PATH, "STATE SNAPSHOT", payload)

    def handle_turn(self, user_text: str) -> Dict[str, Any]:
        # Update current_text but keep the rest of state
        try:
            self.state = self.state.model_copy(update={"current_text": user_text})
        except Exception:
            # fallback
            try:
                self.state.current_text = user_text
            except Exception:
                pass

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
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            _append_log(COORD_LOG_PATH, "TURN (intent error)", payload)
            self._log_state_snapshot(payload)
            return payload

        routed_to: Optional[str] = None
        ok = False
        result_payload: Optional[Dict[str, Any]] = None
        error: Optional[str] = None

        # 2) Routing
        if intent == "PROVIDE_DATA":
            routed_to = "LLM(domain) → direct extractors"
            try:
                domains = classify_data_domains_llm(user_text)

                updates_aggregate: Dict[str, Any] = {}
                provided_all: List[str] = []

                for dom in domains:
                    ex = self._extractors.get(dom)
                    if not ex:
                        continue
                    out = ex.extract_dict(user_text, temperature=0.0, max_tokens=300)
                    # tolerate {"updates": ...} or {"result": {"updates": ...}}
                    result = out.get("result") or out
                    updates = result.get("updates") or {}

                    # aggregate
                    for section, payload in (updates or {}).items():
                        if section not in updates_aggregate:
                            updates_aggregate[section] = payload
                        else:
                            _deep_merge(updates_aggregate[section], payload)

                    provided = out.get("provided_fields")
                    if not provided:
                        provided = _compute_presence({"updates": updates})
                    provided_all.extend(provided or [])

                # merge into persistent state
                self._merge_into_state(updates_aggregate)

                result_payload = {
                    "updates": updates_aggregate,                # delta merged this turn
                    "provided_fields": sorted(set(provided_all)),
                    "domains": domains,
                }
                ok = True

            except Exception as e:
                error = f"ProvideData (direct extractors) error: {e}"
                ok = False
                result_payload = None

        elif intent == "WHAT_IS_LEFT":
            routed_to = "WhatsLeft"
            result_payload = {"missing": compute_whats_left_from_state(self.state)}
            ok = True

        else:
            routed_to, result_payload = _handle_not_implemented(intent)
            ok = False

        # 3) Output + logs
        output = {
            "utterance": user_text,
            "intent": intent,
            "routed_to": routed_to,
            "ok": ok,
            "result": result_payload,
            "error": error,
        }

        print(json.dumps(output, indent=2, ensure_ascii=False))
        _append_log(COORD_LOG_PATH, "TURN", output)
        self._log_state_snapshot(output)
        return output


# Optional CLI for quick manual checks
if __name__ == "__main__":
    import sys
    phrases = sys.argv[1:] or [
        "my name is roger erismann",
        "customer address is 12 oak ave, san jose ca 95112",
        "dbh is 24 inches and height 60 ft",
        "give me a short summary",
        "what's left?",
        "thanks!",
    ]
    C = Coordinator()
    for p in phrases:
        C.handle_turn(p)
