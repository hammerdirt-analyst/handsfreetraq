# turn_capture_parser.py
# Parse a single coordinator TURN output dict into capture objects.
# Contract:
#   parse_turn(turn: dict) -> list[dict]
# Emitted schema (one object per (segment, provided_field) OR one "Not Found" per segment with extractor and no capture):
#   {
#     "section": "<tree_description|area_description|risks|recommendations>",
#     "text": "<original utterance>",
#     "path": "<dotted.state.path>" | "Not Found",
#     "value": "<string value>"     | "Not Found"
#   }

from __future__ import annotations

from typing import Any, Dict, List, Optional

_NOT_FOUND = "Not Found"
# treat any of these (case-insensitive where str) as effectively missing
_NOT_PROVIDED_TOKENS = {"not provided", "n/a", "na", ""}

def _is_missing_value(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() in _NOT_PROVIDED_TOKENS
    if isinstance(v, list):
        return len(v) == 0
    return False

def _get_by_dotted(root: Dict[str, Any], dotted: str) -> Any:
    """
    Safely walk a nested dict by a dotted path.
    Returns None if any hop is missing.
    """
    cur: Any = root
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur[part]
    return cur

def _segment_had_extractor(note: Optional[str]) -> bool:
    # coordinator uses: "captured", "no_capture", "navigation_only"
    return (note == "captured") or (note == "no_capture")

def parse_turn(turn: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert a single TURN log object from the coordinator into capture rows.

    Rules:
      - Only consider segments where an extractor ran:
          note == "captured"  -> emit one row per provided_field
          note == "no_capture"-> emit exactly one row with path/value = "Not Found"
      - Skip segments with note == "navigation_only".
      - A provided_field whose value cannot be found in result.updates OR is "Not provided"
        becomes value="Not Found".
      - The original utterance string is copied into each row as 'text'.
    """
    out: List[Dict[str, Any]] = []

    if not isinstance(turn, dict):
        return out

    # gate on intent/path shape
    intent = (turn.get("intent") or "").upper()
    if intent != "PROVIDE_STATEMENT":
        return out

    result = turn.get("result") or {}
    segments = result.get("segments") or []
    updates_root = result.get("updates") or {}
    utter = turn.get("utterance") or ""

    if not isinstance(segments, list):
        return out

    for seg in segments:
        if not isinstance(seg, dict):
            continue

        section = seg.get("section")
        note = seg.get("note")
        provided_fields = seg.get("provided_fields") or []

        # only keep segments where the extractor ran
        if not _segment_had_extractor(note):
            # navigation_only or unknown → skip
            continue

        # extractor ran but nothing was captured → single Not Found row
        if not provided_fields:
            out.append({
                "section": section,
                "text": utter,
                "path": _NOT_FOUND,
                "value": _NOT_FOUND,
            })
            continue

        # normal case: one row per provided field
        for dotted_path in provided_fields:
            # try to read the value from updates; if missing or "Not provided" → Not Found
            val = _get_by_dotted(updates_root, dotted_path)
            value_str: str
            if _is_missing_value(val):
                value_str = _NOT_FOUND
            else:
                value_str = str(val)
            # prefer the top-level section from the dotted path to be robust
            sec_from_path = dotted_path.split(".", 1)[0] if isinstance(dotted_path, str) and "." in dotted_path else section
            out.append({
                "section": sec_from_path or section,
                "text": utter,
                "path": dotted_path if value_str != _NOT_FOUND else _NOT_FOUND if not dotted_path else dotted_path,
                "value": value_str,
            })

    return out
