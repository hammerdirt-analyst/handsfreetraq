#!/usr/bin/env python3
"""
Project: Arborist Agent
File: section_report_agent.py (drop-in replacement, no nested methods)
Author: roger erismann (revised)

SectionReportAgent
------------------
Multi-use agent operating on a single report section.

Modes:
- "prose"   → LLM-written narrative using LangChain ChatOpenAI (no extraction).
- "outline" → Deterministic list of *all* leaf paths with values, including "Not provided" for scalars and [] for empty arrays (no LLM).
- "payload" → Returns the exact JSON payload we would send to the LLM (client-inspectable).

Design:
- No job context; only the chosen state.<section> snapshot (+ optional reference_text).
- Returns token usage {in, out} when available via response_metadata/usage_metadata.
- Payload includes the exact snapshot and provided_paths (computed with NOT_PROVIDED semantics).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Literal, Optional, Tuple

import dotenv
# from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from arborist_report.report_state import ReportState, NOT_PROVIDED
from arborist_report.models import chatllm_invoke

dotenv.load_dotenv()

SectionName = Literal["area_description", "tree_description", "targets", "risks", "recommendations"]


# ---------------------------- Top-level helpers -----------------------------

def _ensure_dict(model_or_obj: Any) -> Dict[str, Any]:
    if hasattr(model_or_obj, "model_dump"):
        return model_or_obj.model_dump(exclude_none=False)
    if isinstance(model_or_obj, dict):
        return model_or_obj
    raise TypeError("Section snapshot must be a Pydantic model or dict")


def _is_provided_value(val: Any) -> bool:
    if isinstance(val, str):
        return val != NOT_PROVIDED
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, dict):
        # Provided if *any* child is provided
        return any(_is_provided_value(v) for v in val.values())
    return val is not None


def _walk_leaves(prefix: str, obj: Any, out: List[Tuple[str, Any]]) -> None:
    """
    Flatten to dotted leaves. Arrays and scalars are leaves.
    Dicts recurse; order is stable by sorted keys for determinism.
    """
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(exclude_none=False)
    if isinstance(obj, dict):
        for k in sorted(obj.keys()):
            key = f"{prefix}.{k}" if prefix else k
            _walk_leaves(key, obj[k], out)
    else:
        out.append((prefix, obj))


def _list_provided_paths(section: str, snapshot: Dict[str, Any]) -> List[str]:
    leaves: List[Tuple[str, Any]] = []
    _walk_leaves(section, snapshot, leaves)
    paths = [p for p, v in leaves if _is_provided_value(v)]
    return sorted(set(paths))


def _system_prompt_from_style(style: Dict[str, Any]) -> str:
    bullets = bool(style.get("bullets", False))
    length = str(style.get("length", "medium"))
    reading = str(style.get("reading_level", "general"))
    return (
        "You are an arborist writing assistant.\n"
        "RULES:\n"
        "1) Use ONLY facts present in the provided JSON payload.\n"
        "2) Treat 'Not provided' and empty arrays as absent; do NOT mention them.\n"
        "3) Do NOT invent facts or numbers. No external knowledge.\n"
        f"4) Tone: neutral, professional. Reading level: {reading}.\n"
        f"5) Output {'bullet points' if bullets else 'one concise paragraph'}.\n"
        f"6) Target length: {length}.\n"
    )


def _user_prompt_from_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "Summarize the section from this payload without inventing any information.",
            "section": payload["section"],
            "snapshot": payload["snapshot"],
            "provided_paths": payload["provided_paths"],
            "reference_text": payload.get("reference_text", ""),
            "style": payload.get("style", {}),
        },
        ensure_ascii=False,
    )


def _extract_text(ai_message: Any) -> str:
    try:
        return (ai_message.content or "").strip()
    except Exception:
        return str(ai_message).strip()


def _extract_token_usage(ai_message: Any) -> Tuple[int, int]:
    try:
        meta = getattr(ai_message, "response_metadata", {}) or {}
        usage = meta.get("token_usage") or {}
        if usage:
            return int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
    except Exception:
        pass
    try:
        usage2 = getattr(ai_message, "usage_metadata", {}) or {}
        if usage2:
            return int(usage2.get("input_tokens", 0) or 0), int(usage2.get("output_tokens", 0) or 0)
    except Exception:
        pass
    return 0, 0


def _postprocess_text(text: str, *, bullets: bool) -> str:
    # Light normalization; keep deterministic
    t = " ".join(text.split())
    if bullets and "\n" not in text and ". " in text:
        parts = [p.strip() for p in t.split(". ") if p.strip()]
        return "\n".join(f"- {p.rstrip('.')}" for p in parts)
    return t


def _build_payload(section: SectionName, state: ReportState, reference_text: str, style: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    section_state = getattr(state, section)
    snapshot = _ensure_dict(section_state)
    provided_paths = _list_provided_paths(section, snapshot)
    return {
        "version": "section_payload_v1",
        "section": section,
        "snapshot": snapshot,
        "provided_paths": provided_paths,
        "reference_text": reference_text or "",
        "style": {
            "length": "medium",
            "bullets": False,
            "reading_level": "general",
            **(style or {}),
        },
    }


def _outline_lines_for_snapshot(section: str, snapshot: Dict[str, Any]) -> List[str]:
    """
    Deterministically emit ALL leaves under the section as "path: value".
    - Scalars: show actual value or "Not provided" if sentinel/None.
    - Arrays: show JSON array (e.g., [] when empty).
    """
    leaves: List[Tuple[str, Any]] = []
    _walk_leaves(section, snapshot, leaves)

    lines: List[str] = []
    for path, val in leaves:
        # Arrays: dump as JSON array
        if isinstance(val, list):
            lines.append(f"{path}: {json.dumps(val, ensure_ascii=False)}")
        # Dicts shouldn't appear here (we only emit leaves), but guard anyway
        elif isinstance(val, dict):
            # If a dict slipped through, flattening missed it; be safe and dump
            lines.append(f"{path}: {json.dumps(val, ensure_ascii=False)}")
        else:
            if isinstance(val, str):
                v = val
                if v is None or v == "":
                    v = NOT_PROVIDED
            elif val is None:
                v = NOT_PROVIDED
            else:
                v = json.dumps(val, ensure_ascii=False)
            lines.append(f"{path}: {v}")
    # Keep only paths that start with the section root for safety
    return [ln for ln in lines if ln.startswith(section + ".")]


def _ensure_client(existing: Optional[ChatOpenAI], *, model_name: str, temperature: float) -> ChatOpenAI:
    if existing is not None:
        return existing
    return ChatOpenAI(model=model_name, temperature=temperature)


# ------------------------------ Public API ----------------------------------

class SectionReportAgent:
    """
    Multi-use section agent.

    Public API:
      - build_payload(...)
      - run(..., mode="prose"|"outline"|"payload")
    """

    def __init__(self, model: Optional[str] = None, client: Any = None):
        """
        Args:
            model: OpenAI model name (used if client is None). Defaults to $OPENAI_MODEL or 'gpt-4o-mini'.
            client: Optional injected chat client with .invoke(messages) (for tests or alt providers).
        """
        self._model_name = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._client = client  # if None, created lazily

    # --------------------- Public: payload builder (no LLM) ---------------------

    def build_payload(
        self,
        *,
        section: SectionName,
        state: ReportState,
        reference_text: str = "",
        style: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return _build_payload(section, state, reference_text, style)

    # --------------------------- Public: run() ----------------------------------

    def run(
        self,
        *,
        section: SectionName,
        state: ReportState,
        reference_text: str = "",
        mode: Literal["prose", "outline", "payload"] = "prose",
        temperature: float = 0.3,
        style: Optional[Dict[str, Any]] = None,
        include_payload: bool = False,
    ) -> Dict[str, Any]:
        """
        Returns:
            {
              "mode": "prose|outline|payload",
              "text": "<str>"                    # only when mode == "prose"
              "outline": ["field: value", ...]   # only when mode == "outline"
              "payload": <dict>,                 # present for payload mode; included when include_payload=True
              "tokens": { "in": int, "out": int },
              "model": "<model-name>"
            }
        """
        payload = _build_payload(section, state, reference_text, style)

        if mode == "payload":
            return {
                "mode": "payload",
                "payload": payload,
                "tokens": {"in": 0, "out": 0},
                "model": self._model_name,
            }

        if mode == "outline":
            outline = _outline_lines_for_snapshot(payload["section"], payload["snapshot"])
            out: Dict[str, Any] = {
                "mode": "outline",
                "outline": outline,
                "tokens": {"in": 0, "out": 0},
                "model": self._model_name,
            }
            if include_payload:
                out["payload"] = payload
            return out

        # Prose mode (LLM)
        assert mode == "prose"
        system = _system_prompt_from_style(payload["style"])
        user = _user_prompt_from_payload(payload)
        # If a test client was injected, keep the old path for FakeChatModel etc.
        if self._client is not None:
            ai_msg = self._client.invoke([{"role": "system", "content": system},
                                          {"role": "user", "content": user}])
            text = _extract_text(ai_msg)
            tok_in, tok_out = _extract_token_usage(ai_msg)
            tokens = {"in": tok_in, "out": tok_out}
            model = self._model_name
        else:
            # Shared helper for real runs (LangChain ChatOpenAI under the hood)
            llm_out = chatllm_invoke(
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=None,
                response_format=None,
                model_name=self._model_name,
            )
            text = llm_out["text"]
            tokens = llm_out["tokens"]  # {"in": int, "out": int}
            model = llm_out["model"]

        out = {
            "mode": "prose",
            "text": _postprocess_text(text, bullets=payload["style"].get("bullets", False)),
            "tokens": tokens,
            "model": model,
        }
        if include_payload:
            out["payload"] = payload
        return out


# ------------------------------ Test Double ----------------------------------

class FakeChatModel:
    """
    Minimal drop-in for tests: returns a fixed text and fake token usage.

    Usage:
        agent = SectionReportAgent(client=FakeChatModel("Hello world.", in_tokens=34, out_tokens=20))
        out = agent.run(section="risks", state=state, mode="prose", temperature=0.3)
    """
    def __init__(self, text: str = "[stub prose]", in_tokens: int = 0, out_tokens: int = 0):
        self._text = text
        self._in = in_tokens
        self._out = out_tokens

    def invoke(self, messages: List[Dict[str, str]]):
        class _Msg:
            def __init__(self, text: str, in_tokens: int, out_tokens: int):
                self.content = text
                self.response_metadata = {
                    "token_usage": {
                        "prompt_tokens": in_tokens,
                        "completion_tokens": out_tokens,
                        "total_tokens": in_tokens + out_tokens,
                    }
                }
        return _Msg(self._text, self._in, self._out)
