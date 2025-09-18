#!/usr/bin/env python3
"""
Project: Arborist Agent
File: corrections_agent.py
Author: roger erismann (PEP 8 cleanup)

CorrectionsAgent
----------------
Run the appropriate extractor against the *user's correction text* and return
a normalized updates envelope ready for ReportState.model_merge_updates(...).

Design
- Bypasses any deterministic routing/filters; this is an explicit service call.
- Reuses existing extractor classes.
- Does NOT mutate state; Coordinator remains the single point to merge + log.
- Returns token usage {in, out} if available elsewhere (not handled here).

Public API
- class CorrectionsAgent:
    - __init__()
    - run(section, text, state, policy="last_write", temperature=0.0,
          max_tokens=300) -> dict

Dependencies
- Internal: extractor_registry.default_registry, report_state.ReportState/NOT_PROVIDED
- External: python-dotenv (env loading)
"""

from __future__ import annotations

from typing import Any, Dict, Literal

import dotenv

from arborist_report.extractor_registry import default_registry
from arborist_report.report_state import NOT_PROVIDED, ReportState

dotenv.load_dotenv()

SectionName = Literal[
    "area_description", "tree_description", "targets", "risks", "recommendations"
]


# ----------------------------- Module helpers ---------------------------------


def _value_is_provided(v: Any) -> bool:
    """Return True if a single value is considered 'provided'."""
    if isinstance(v, str):
        return v != NOT_PROVIDED and v.strip() != ""
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, dict):
        return any(_value_is_provided(x) for x in v.values())
    return v is not None


def _has_provided(envelope: Dict[str, Any]) -> bool:
    """
    True if any leaf in the given updates envelope is provided.
    Accepts either {"updates": {...}} or the inner {...}.
    """
    if not envelope:
        return False
    root = envelope.get("updates") if "updates" in envelope else envelope
    if not isinstance(root, dict):
        return False
    return _value_is_provided(root)


def _walk_and_collect(prefix: str, obj: Any, out: Dict[str, Any]) -> None:
    """Flatten to dotted leaves (mirrors ReportState._walk_and_collect)."""
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(exclude_none=False)
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            _walk_and_collect(key, v, out)
    else:
        out[prefix] = obj


def _set_by_path(data: Dict[str, Any], path: str, value: Any) -> None:
    """Set value into a nested dict using dotted path notation."""
    parts = path.split(".")
    cur = data
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _coerce_updates_to_state_shapes(
    updates_envelope: Dict[str, Any],
    state: ReportState,
) -> Dict[str, Any]:
    """
    Ensure incoming updates match the types in state:
      - If the target in state is a list and incoming is a non-empty string,
        wrap as [string].
      - Filter out the sentinel "Not provided" from list payloads.
      - Leave correct types as-is; ignore empty lists.

    Returns a normalized {"updates": {...}} dict.
    """
    # Normalize to {"updates": {...}}
    if "updates" in updates_envelope and isinstance(
        updates_envelope["updates"], dict
    ):
        incoming = updates_envelope["updates"]
    else:
        # assume the caller passed just the inner dict
        incoming = updates_envelope

    if not isinstance(incoming, dict):
        return {"updates": {}}

    # Flatten incoming and current state for type checks
    flat_in: Dict[str, Any] = {}
    _walk_and_collect("", incoming, flat_in)

    flat_state: Dict[str, Any] = {}
    _walk_and_collect("", state, flat_state)

    # Rebuild a corrected updates dict
    normalized: Dict[str, Any] = {}

    for path, new_val in flat_in.items():
        if not path:
            continue
        target_type = flat_state.get(path, None)

        if isinstance(target_type, list):
            if isinstance(new_val, list):
                coerced = [x for x in new_val if (x is not None and x != NOT_PROVIDED)]
            elif isinstance(new_val, str) and new_val and new_val != NOT_PROVIDED:
                coerced = [new_val]
            else:
                coerced = []
            if coerced:
                _set_by_path(normalized, path, coerced)
            # else: nothing to set (avoid writing empty lists)
        else:
            _set_by_path(normalized, path, new_val)

    return {"updates": normalized}


# --------------------------------- Agent --------------------------------------


class CorrectionsAgent:
    """
    Single-scope correction runner. Stateless; does not mutate ReportState.

    Normalizes extractor output so that list-typed fields in state receive list
    values (e.g., "defects": "fresh crack" -> ["fresh crack"]) to trigger append
    semantics during merge.
    """

    def __init__(self) -> None:
        self._reg = default_registry()

    def run(
        self,
        *,
        section: SectionName,
        text: str,
        state: ReportState,
        policy: Literal["last_write", "prefer_existing"] = "last_write",
        temperature: float = 0.0,
        max_tokens: int = 300,
    ) -> Dict[str, Any]:
        """
        Execute the section extractor on the correction text and produce a
        normalized updates envelope.

        Returns:
            {
              "section": "<section>",
              "updates": { "updates": { "<section>": {...} } },
              "applied": <bool>,
              "policy": "last_write"
            }
        """
        ex = self._reg.get(section)
        out = ex.extract_dict(text, temperature=temperature, max_tokens=max_tokens)
        result = out.get("result") or out
        raw_updates = result.get("updates") or {}

        # Ensure envelope has only the requested section's block (defensive)
        section_block = raw_updates.get(section, {})
        section_envelope = {"updates": {section: section_block}}

        # Normalize shapes so list fields append correctly
        normalized = _coerce_updates_to_state_shapes(section_envelope, state)

        return {
            "section": section,
            "updates": normalized,
            "applied": _has_provided(normalized),
            "policy": policy,
        }
