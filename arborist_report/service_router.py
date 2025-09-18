"""
Project: Arborist Agent
File: service_router.py
Author: roger erismann (updated spec)

Deterministic (no-LLM) service router. Classifies a service request and optionally
its section using lexicons, cues, and field→section hints. Returns (service, section|None).

Updates in this version:
- Replaced QUICK_SUMMARY with OUTLINE.
- "Outline" is only triggered by the explicit word "outline".
- Phrases like "recap", "brief summary", "executive summary" imply **prose** and thus map to
  SECTION_SUMMARY only when a section is specified; otherwise they return NONE (let the
  Coordinator clarify).
- If the user says "outline" **with a section**, return SECTION_SUMMARY for that section
  (the Coordinator will render that summary in outline mode).
- If the user says "outline" **without a section**, return OUTLINE with section=None; the
  Coordinator will assume ReportState.current_section for scope.
- Expanded correction verbs (add/append/insert/remove/delete/replace) with guards to avoid
  overfiring.

Methods & Classes
- _normalize(s: str) -> str: trim/normalize whitespace/lowercase input.
- _contains_any(haystack: str, needles: set[str]) -> bool: membership utility.
- _detect_section(text: str) -> Optional[str]: infer canonical section from tokens or field hints.
- _has_outline(text: str) -> bool: detect explicit outline intent.
- _looks_like_correction(text: str) -> bool: detect “change/fix/update …” requests (with domain hints).
- _looks_like_section_summary(text: str) -> Optional[str]: detect section-summary (prose) request and section.
- _looks_like_report_draft(text: str) -> bool: detect “make/draft/generate report” requests.
- classify_service(text: str) -> tuple[ServiceName, Optional[SectionName]]: main entry.

Dependencies
- Internal: none (standalone heuristics)
- Stdlib: typing
- Constants: SECTIONS, _FIELD_HINTS, _SECTION_TOKENS, _SECTION_SUMMARY_CUES, _OUTLINE_CUES, _REPORT_DRAFT_CUES
"""

from typing import Optional, Tuple

# Canonical sections
SECTIONS = {
    "tree_description",
    "risks",
    "targets",
    "area_description",
    "recommendations",
}

# Lightweight lexicons
_CORRECTION_VERBS = {
    # existing
    "update", "fix", "adjust", "replace", "amend", "edit", "modify", "revise",
    "set", "switch", "change", "correct", "make", "alter",
    # expanded
    "add", "append", "insert", "remove", "delete",
}

# Field→section hints for cases without explicit section tokens
_FIELD_HINTS = {
    # tree_description
    "species": "tree_description",
    "scientific name": "tree_description",
    "type_common": "tree_description",
    "type scientific": "tree_description",
    "type_scientific": "tree_description",
    "height": "tree_description",
    "dbh": "tree_description",
    "dbh_in": "tree_description",
    "diameter": "tree_description",
    "crown shape": "tree_description",
    "canopy": "tree_description",
    "canopy width": "tree_description",

    # area_description
    "site": "area_description",
    "site description": "area_description",
    "site use": "area_description",
    "context": "area_description",
    "foot traffic": "area_description",

    # risks
    "risk": "risks",
    "risks": "risks",
    "likelihood": "risks",
    "severity": "risks",
    "rationale": "risks",
    "included bark": "risks",
    "deadwood": "risks",

    # targets
    "target": "targets",
    "targets": "targets",
    "occupied frequency": "targets",
    "proximity": "targets",
    "strike potential": "targets",
    "label": "targets",
    "walkway": "targets",
    "parking lot": "targets",
    "playground": "targets",
    "driveway": "targets",
    "roof": "targets",
    "house": "targets",
    "building": "targets",
    "vehicles": "targets",

    # recommendations
    "recommendation": "recommendations",
    "recommendations": "recommendations",
    "pruning": "recommendations",
    "removal": "recommendations",
    "continued maintenance": "recommendations",
    "work scope": "recommendations",
    "scope": "recommendations",
    "limitations": "recommendations",
    "notes": "recommendations",
    "treatment plan": "recommendations",
}

# Tokens that mean “this is about a specific section”
_SECTION_TOKENS = {
    "tree_description": {"tree description", "treedescription"},
    "risks": {"risk", "risks"},
    "targets": {"target", "targets"},
    "area_description": {"area description", "areadescription"},
    "recommendations": {"recommendation", "recommendations"},
}

# Phrasing for section summary (PROSE)
# NOTE: do **not** include "outline" variants here. Outline is handled explicitly.
_SECTION_SUMMARY_CUES = {
    "section summary",
    "summary of the",
    "recap",
    "overview of",
    "synopsis of",
    "tldr of the", "tl;dr of the",
    "summarize the",
    "section overview", "describe the",
    "breakdown of", "condensed summary of", "brief summary of",
    "section overview requested", "summary of",
}

# Phrasing for OUTLINE (whole-report intent). We only trigger on explicit "outline".
_OUTLINE_CUES = {
    "outline", "report outline", "overall outline", "outline everything",
    "outline the report", "give me an outline", "outline please",
}

# Phrasing for report draft
_REPORT_DRAFT_CUES = {
    "draft a report", "report draft", "generate a report", "build a report",
    "produce the final report", "prepare my report", "draft this report",
    "generate the report", "preliminary report", "produce a report",
    "make the report", "assemble a report draft", "create the report draft",
    "start a report draft", "compile a report", "spin up a report draft",
    "initiate the report draft", "draft the report", "prepare a draft report",
    "put together a report", "create a report now", "draft write-up (report)",
    "get me a report draft", "start drafting the report", "write a report draft",
    "construct a report", "assemble a report"
}


def _normalize(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _contains_any(haystack: str, needles: set[str]) -> bool:
    return any(n in haystack for n in needles)


def _detect_section(text: str) -> Optional[str]:
    # 1) direct section mentions
    for sec, tokens in _SECTION_TOKENS.items():
        if _contains_any(text, tokens) or sec in text:
            return sec
    # 2) field-hint inference
    for hint, sec in _FIELD_HINTS.items():
        if hint in text:
            return sec
    return None


def _has_outline(text: str) -> bool:
    # Only explicit outline words trigger outline behavior
    return _contains_any(text, _OUTLINE_CUES)


def _looks_like_correction(text: str) -> bool:
    if any(v in text for v in _CORRECTION_VERBS):
        # also require some domain hint to avoid overfiring
        if _detect_section(text) is not None:
            return True
        # or an assignment/replace-like phrase (e.g., “change dbh to 30 inches”)
        assigners = {" to ", " = ", " should be ", " set to ", " replace ", " with "}
        if any(a in text for a in assigners):
            return True
    return False


def _looks_like_section_summary(text: str) -> Optional[str]:
    # Section summary cues require a detectable section (prose assumption)
    if _contains_any(text, _SECTION_SUMMARY_CUES):
        sec = _detect_section(text)
        if sec:
            return sec
    # handle patterns like "TL;DR for targets section"
    if ("tldr" in text or "tl;dr" in text) and "section" in text:
        sec = _detect_section(text)
        if sec:
            return sec
    return None


def _looks_like_report_draft(text: str) -> bool:
    if _contains_any(text, _REPORT_DRAFT_CUES):
        return True
    # generic “report” with a creation verb
    if "report" in text and any(v in text for v in {"draft", "generate", "produce", "prepare", "build", "create", "compile", "write", "put together", "start"}):
        return True
    return False


def classify_service(text: str) -> Tuple[str, Optional[str]]:
    """
    Returns (service, section|None)
    service in {"MAKE_CORRECTION","SECTION_SUMMARY","OUTLINE","MAKE_REPORT_DRAFT","NONE"}

    Routing order (honors explicit outline intent early):
      1) MAKE_CORRECTION
      2) Outline special-case: if "outline" present → OUTLINE (section if present, else none)
      3) SECTION_SUMMARY (prose cues) — requires a section
      4) MAKE_REPORT_DRAFT
      5) NONE
    """
    t = _normalize(text)

    # 1) Correction
    if _looks_like_correction(t):
        sec = _detect_section(t)
        return ("MAKE_CORRECTION", sec)

    # 2) Explicit outline handling (only on the word "outline")
    if _has_outline(t):
        sec = _detect_section(t)
        if sec:
            return ("OUTLINE", sec)
        # No section mentioned → OUTLINE (Coordinator will default to current_section)
        return ("OUTLINE", None)

    # 3) Section summary (prose) if cues + section present
    sec = _looks_like_section_summary(t)
    if sec:
        return ("SECTION_SUMMARY", sec)

    # 4) Report draft
    if _looks_like_report_draft(t):
        return ("MAKE_REPORT_DRAFT", None)

    # 5) Ambiguous → NONE (backstop/clarify)
    return ("NONE", None)
