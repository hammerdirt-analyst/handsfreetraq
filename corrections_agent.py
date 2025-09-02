#!/usr/bin/env python3
"""
Project: Arborist Agent
File: corrections_agent.py
Author: roger erismann

CorrectionsAgent
----------------
Run the appropriate extractor against the *user's correction text* and return
a normalized updates envelope ready for ReportState.model_merge_updates(...).

Design:
- Bypasses any deterministic routing/filters; this is an explicit service call.
- Reuses your existing extractor classes (Outlines+OpenAI via ModelFactory).
- Does NOT mutate state; Coordinator remains the single point to merge + log provenance.
- Returns token usage {in, out} if available (best-effort; Outlines often hides this),
  else zeros (documented).

Methods & Classes
- class CorrectionsAgent:
    - __init__(model: str|None = None)
    - run(section, text, state, policy="last_write", temperature=0.0, max_tokens=300) -> dict

Dependencies
- Internal: extractor_registry.default_registry, report_state.ReportState/NOT_PROVIDED
- External: python-dotenv (env loading)
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Literal
import os

# Ensure .env is loaded for OPENAI_* envs
import dotenv
dotenv.load_dotenv()

from extractor_registry import default_registry
from report_state import ReportState, NOT_PROVIDED

SectionName = Literal["area_description", "tree_description", "targets", "risks", "recommendations"]


class CorrectionsAgent:
    """
    Corrections-as-a-service:
      - choose extractor by section
      - run LLM extractor on the user's correction text
      - return updates envelope + 'applied' boolean + token usage (best-effort)
    """

    def __init__(self, model: Optional[str] = None):
        # For visibility only; extractors use ModelFactory under the hood.
        self._model_name = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self._registry = default_registry()

    def run(
        self,
        *,
        section: SectionName,
        text: str,
        state: ReportState,
        policy: Literal["prefer_existing", "last_write"] = "last_write",
        temperature: float = 0.0,
        max_tokens: int = 300,
    ) -> Dict[str, Any]:
        """
        Execute the section extractor against `text` and return a corrections envelope.

        Returns:
          {
            "section": "<section>",
            "updates": { ... },           # extractor envelope (echo)
            "applied": bool,              # True if any provided values present in updates
            "policy": "last_write" | "prefer_existing",
            "tokens": {"in": int, "out": int},  # often (0,0) with Outlines
            "model": "<model-name>"
          }
        """
        # 1) Instantiate the correct extractor for the target section
        ex = self._registry.get(section)

        # 2) Run LLM extractor (same path as Provide Statement)
        #    NOTE: Most Outlines integrations don't expose token usage; we return zeros if unavailable.
        out = ex.extract_dict(text, temperature=temperature, max_tokens=max_tokens)

        # 3) Normalize to the canonical updates dict
        result_obj = out.get("result") or out
        updates = result_obj.get("updates") or {}

        # 4) Did this envelope contain any provided values?
        applied = self._envelope_has_provided(updates)

        # 5) Token usage best-effort: extractors generally don't return usage; return zeros explicitly
        tokens = {"in": 0, "out": 0}

        return {
            "section": section,
            "updates": updates,
            "applied": bool(applied),
            "policy": policy,
            "tokens": tokens,
            "model": self._model_name,
        }

    # ---------- internals ----------

    @staticmethod
    def _is_provided(v: Any) -> bool:
        if isinstance(v, str):
            return v != NOT_PROVIDED
        if isinstance(v, list):
            return len(v) > 0
        if isinstance(v, dict):
            return any(CorrectionsAgent._is_provided(x) for x in v.values())
        return v is not None

    def _envelope_has_provided(self, updates_envelope: Dict[str, Any]) -> bool:
        """
        Works with either:
          {"updates": {"<section>": {...}}}  OR  {"<section>": {...}}
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
