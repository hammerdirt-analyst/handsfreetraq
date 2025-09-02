#!/usr/bin/env python3
"""
Project: Arborist Agent
File: section_report_agent.py
Author: roger erismann

SectionReportAgent
------------------
Multi-use agent operating on a single report section.

Modes:
- "prose"   → LLM-written narrative using LangChain ChatOpenAI (no extraction).
- "outline" → Deterministic list of provided fields/values from the section (no LLM).
- "payload" → Returns the exact JSON payload we would send to the LLM (client-inspectable).

Design:
- NO job context here; only the chosen state.<section> snapshot (+ optional reference_text).
- Temperature defaults to 0.3 (prose can be a bit free); caller can override per run().
- Returns token usage {in, out} when available via response_metadata.token_usage.
- Canonical payload mirrors what you’ll store alongside summaries (inputs snapshot + hash later).

Methods & Classes
- class SectionReportAgent:
    - __init__(model: str|None = None, client: Any = None)
    - build_payload(section, state, reference_text="", style=None) -> dict
    - run(section, state, reference_text="", mode="prose"|"outline"|"payload",
          temperature=0.3, style=None, include_payload=False) -> dict
- class FakeChatModel: tiny test double that mimics ChatOpenAI.invoke()
Dependencies
- External: langchain-openai (ChatOpenAI), langchain-core (SystemMessage, HumanMessage)
- Internal: report_state.ReportState, report_state.NOT_PROVIDED
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal, Tuple
import os
import json

# LangChain chat model + message classes (matches your working llm_ping pattern)
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# Project types
from report_state import ReportState, NOT_PROVIDED

import dotenv

dotenv.load_dotenv()

SectionName = Literal["area_description", "tree_description", "targets", "risks", "recommendations"]


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
        self._client = client  # if None, we lazily create ChatOpenAI per run()

    # --------------------- Public: payload builder (no LLM) ---------------------

    def build_payload(
        self,
        *,
        section: SectionName,
        state: ReportState,
        reference_text: str = "",
        style: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build the canonical, client-inspectable payload used for 'prose' prompting.

        Returns a dict with keys:
            version, section, snapshot, provided_paths, reference_text, style
        """
        section_state = getattr(state, section)
        snapshot = self._to_dict(section_state)
        provided_paths = self._list_provided_paths(section, snapshot)

        payload = {
            "version": "section_payload_v1",
            "section": section,
            "snapshot": snapshot,                 # exact dict of state.<section>
            "provided_paths": provided_paths,     # dotted paths with provided values
            "reference_text": reference_text or "",
            "style": {
                "length": "medium",               # caller can override via style
                "bullets": False,
                "reading_level": "general",
                **(style or {}),
            },
        }
        return payload

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
              "text": "<str>"            # only when mode == "prose"
              "outline": ["field: value", ...]  # only when mode == "outline"
              "payload": <dict>,         # present for payload mode; included when include_payload=True
              "tokens": { "in": int, "out": int },
              "model": "<model-name>"
            }
        """
        payload = self.build_payload(
            section=section, state=state, reference_text=reference_text, style=style
        )

        # Deterministic modes
        if mode == "payload":
            return {
                "mode": "payload",
                "payload": payload,
                "tokens": {"in": 0, "out": 0},
                "model": self._model_name,
            }

        if mode == "outline":
            outline = self._build_outline(payload["section"], payload["snapshot"])
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
        system = self._system_prompt_from_style(payload["style"])
        user = self._user_prompt_from_payload(payload)

        client = self._ensure_client(temperature=temperature)
        ai_msg = client.invoke([SystemMessage(content=system), HumanMessage(content=user)])

        text = self._extract_text(ai_msg)
        tok_in, tok_out = self._extract_token_usage(ai_msg)

        out = {
            "mode": "prose",
            "text": self._postprocess_text(text, bullets=payload["style"].get("bullets", False)),
            "tokens": {"in": tok_in, "out": tok_out},
            "model": self._model_name,
        }
        if include_payload:
            out["payload"] = payload
        return out

    # --------------------------- Internals --------------------------------------

    def _ensure_client(self, *, temperature: float):
        if self._client is not None:
            return self._client
        # Same pattern as llm_ping.py you validated
        self._client = ChatOpenAI(model=self._model_name, temperature=temperature)
        return self._client

    @staticmethod
    def _to_dict(model_or_obj: Any) -> Dict[str, Any]:
        if hasattr(model_or_obj, "model_dump"):
            return model_or_obj.model_dump(exclude_none=False)
        if isinstance(model_or_obj, dict):
            return model_or_obj
        raise TypeError("Section snapshot must be a Pydantic model or dict")

    @staticmethod
    def _is_provided(val: Any) -> bool:
        # Mirror ReportState._is_provided semantics using NOT_PROVIDED
        if isinstance(val, str):
            return val != NOT_PROVIDED
        if isinstance(val, list):
            return len(val) > 0
        if isinstance(val, dict):
            return any(SectionReportAgent._is_provided(v) for v in val.values())
        return val is not None

    def _list_provided_paths(self, section: str, snapshot: Dict[str, Any]) -> List[str]:
        paths: List[str] = []

        def walk(prefix: str, obj: Any):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(f"{prefix}.{k}" if prefix else k, v)
            elif isinstance(obj, list):
                if len(obj) > 0:
                    paths.append(prefix)
            else:
                if self._is_provided(obj):
                    paths.append(prefix)

        walk(section, snapshot)
        # Keep only leaves under the section (exclude bare top key)
        return sorted(set(p for p in paths if p and p.startswith(section + ".")))

    @staticmethod
    def _build_outline(section: str, snapshot: Dict[str, Any]) -> List[str]:
        """
        Deterministically flattens provided leaves into "field_path: value" lines.
        """
        out: List[str] = []

        def to_lines(prefix: str, obj: Any):
            if isinstance(obj, dict):
                for k in sorted(obj.keys()):
                    to_lines(f"{prefix}.{k}" if prefix else k, obj[k])
            elif isinstance(obj, list):
                if len(obj) > 0:
                    joined = "; ".join([json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x for x in obj])
                    out.append(f"{prefix}: {joined}")
            else:
                if SectionReportAgent._is_provided(obj):
                    val = obj if isinstance(obj, str) else ("" if obj is None else json.dumps(obj, ensure_ascii=False))
                    out.append(f"{prefix}: {val}")

        to_lines("", snapshot)
        return [line for line in out if line.startswith(section + ".")]

    @staticmethod
    def _system_prompt_from_style(style: Dict[str, Any]) -> str:
        bullets = bool(style.get("bullets", False))
        length = str(style.get("length", "medium"))
        reading = str(style.get("reading_level", "general"))
        # No context; summarize ONLY from payload JSON
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

    @staticmethod
    def _user_prompt_from_payload(payload: Dict[str, Any]) -> str:
        # Plain JSON so we can snapshot easily in tests; the LLM reads from this only.
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

    @staticmethod
    def _extract_text(ai_message: Any) -> str:
        # LangChain AIMessage: .content is the text
        try:
            return (ai_message.content or "").strip()
        except Exception:
            return str(ai_message).strip()

    @staticmethod
    def _extract_token_usage(ai_message: Any) -> Tuple[int, int]:
        """
        Pull tokens from LangChain/OpenAI metadata. If unavailable, return (0,0).
        Expected location (as seen in your llm_ping): ai_message.response_metadata["token_usage"]
        """
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

    @staticmethod
    def _postprocess_text(text: str, *, bullets: bool) -> str:
        # Light cleanup; keep deterministic
        t = " ".join(text.split())
        if bullets and "\n" not in text and ". " in text:
            parts = [p.strip() for p in t.split(". ") if p.strip()]
            return "\n".join(f"- {p.rstrip('.')}" for p in parts)
        return t


# ------------------------------ Test Double ----------------------------------

class FakeChatModel:
    """
    Minimal drop-in for tests: returns a fixed text and fake token usage.

    Usage:
        agent = SectionReportAgent(client=FakeChatModel("Hello world.", in_tokens=34, out_tokens=20))
        out = agent.run(section="risks", state=state, mode="prose", temperature=0.3)
    """
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

    def __init__(self, text: str = "[stub prose]", in_tokens: int = 0, out_tokens: int = 0):
        self._text = text
        self._in = in_tokens
        self._out = out_tokens

    def invoke(self, messages: List[Dict[str, str]]):
        return FakeChatModel._Msg(self._text, self._in, self._out)
