"""
whats_left.py — author: roger erismann
Compute a per-section list of missing fields (value == "not provided"),
excluding declined paths, and with special handling for list sections.
"""

from __future__ import annotations
from typing import Dict, List, Any

from models import ReportState, NOT_PROVIDED


# Fields we never report as "missing" in the checklist view
_EXCLUDE_FIELD_NAMES = {
    "narratives",      # narrative arrays are never "required"
    "current_text",    # raw utterance buffer
    "declined_paths",  # audit list
}


def _is_scalar_missing(val: Any) -> bool:
    return isinstance(val, str) and val == NOT_PROVIDED


def compute_whats_left(state: ReportState) -> Dict[str, List[str]]:
    """
    Return a dict mapping top-level section name -> list of missing field paths (dotted),
    reflecting *all* fields whose value == "not provided", excluding declined paths.

    Special handling for list sections (targets.items, risks.items):
      - if the list is empty -> include "0 items" for that section
      - if it has entries -> we do not enumerate per-item missing fields in this compact view
    """
    declined = set(state.meta.declined_paths or [])
    missing: Dict[str, List[str]] = {}

    def add_missing(section: str, path: str) -> None:
        dotted = f"{section}.{path}" if path else section
        if dotted in declined:
            return
        missing.setdefault(section, []).append(path)

    def walk(section_name: str, obj: Any, base_path: str = "") -> None:
        if hasattr(obj, "model_dump"):
            data = obj.model_dump()
        elif isinstance(obj, dict):
            data = obj
        else:
            return

        for k, v in data.items():
            if k in _EXCLUDE_FIELD_NAMES:
                continue

            path = f"{base_path}.{k}" if base_path else k

            # Top-level list sections: items
            if section_name in {"targets", "risks"} and k == "items":
                if isinstance(v, list) and len(v) == 0:
                    add_missing(section_name, "0 items")
                continue

            # Nested object
            if hasattr(v, "model_dump") or isinstance(v, dict):
                walk(section_name, v, path)
                continue

            # Primitive
            if _is_scalar_missing(v):
                add_missing(section_name, path)

    # Walk each top-level section (full coverage)
    walk("arborist_info", state.arborist_info)
    walk("customer_info", state.customer_info)
    walk("tree_description", state.tree_description)
    walk("area_description", state.area_description)
    walk("targets", state.targets)
    walk("risks", state.risks)
    walk("recommendations", state.recommendations)

    # Drop sections with no missing fields after filtering
    return {sec: fields for sec, fields in missing.items() if fields}
