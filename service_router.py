"""
Project: Arborist Agent
File: service_router.py
Author: roger erismann

Deterministic (no-LLM) service router. Classifies a service request and optionally
its section using lexicons, cues, and field→section hints. Returns (service, section|None).

Methods & Classes
- _normalize(s: str) -> str: trim/normalize whitespace/lowercase input.
- _contains_any(haystack: str, needles: set[str]) -> bool: membership utility.
- _detect_section(text: str) -> Optional[str]: infer canonical section from tokens or field hints.
- _looks_like_correction(text: str) -> bool: detect “change/fix/update …” requests (with domain hints).
- _looks_like_section_summary(text: str) -> Optional[str]: detect section-summary request and section.
- _looks_like_quick_summary(text: str) -> bool: detect quick overall summary requests.
- _looks_like_report_draft(text: str) -> bool: detect “make/draft/generate report” requests.
- classify_service(text: str) -> tuple[ServiceName, Optional[SectionName]]: main entry.

Dependencies
- Internal: none (standalone heuristics)
- Stdlib: typing
- Constants: SECTIONS, _FIELD_HINTS, _SECTION_TOKENS, _SECTION_SUMMARY_CUES, _QUICK_SUMMARY_CUES, _REPORT_DRAFT_CUES
"""


from typing import Optional, Tuple

SECTIONS = {
    "tree_description",
    "risks",
    "targets",
    "area_description",
    "recommendations",
}

# Lightweight lexicons
_CORRECTION_VERBS = {
    "update", "fix", "adjust", "replace", "amend", "edit", "modify", "revise",
    "set", "switch", "change", "correct", "make", "alter"
}

# Field→section hints for cases without explicit section tokens
_FIELD_HINTS = {
    # tree_description
    "species": "tree_description",
    "type_common": "tree_description",
    "type scientific": "tree_description",
    "type_scientific": "tree_description",
    "height": "tree_description",
    "dbh": "tree_description",
    "dbh_in": "tree_description",
    "crown shape": "tree_description",
    "canopy": "tree_description",
    "canopy width": "tree_description",

    # area_description
    "site use": "area_description",
    "context": "area_description",
    "foot traffic": "area_description",

    # risks
    "risk": "risks",
    "risks": "risks",
    "likelihood": "risks",
    "severity": "risks",
    "rationale": "risks",

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

    # recommendations
    "recommendation": "recommendations",
    "recommendations": "recommendations",
    "pruning": "recommendations",
    "removal": "recommendations",
    "continued maintenance": "recommendations",
    "scope": "recommendations",
    "limitations": "recommendations",
    "notes": "recommendations",
}

# Tokens that mean “this is about a specific section”
_SECTION_TOKENS = {
    "tree_description": {"tree description", "treedescription"},
    "risks": {"risk", "risks"},
    "targets": {"target", "targets"},
    "area_description": {"area description", "areadescription"},
    "recommendations": {"recommendation", "recommendations"},
}

# Phrasing for section summary
_SECTION_SUMMARY_CUES = {
    "section summary",
    "summary of the",  # must also find a section token/name
    "recap",           # with section token
    "tldr of the", "tl;dr of the",
    "rollup of", "roll up the", "rollup / summary", "rollup",
    "outline the",
    "overview of",
    "synopsis of",
    "summarize the", "section summary requested",
    "section overview", "overview the", "describe the",
    "breakdown of", "condensed summary of", "brief summary of",
    "section overview requested", "summary of"
}

# Phrasing for quick summary (global)
_QUICK_SUMMARY_CUES = {
    "quick status", "short summary", "summary please", "overall summary",
    "brief status", "quick recap", "high-level summary", "short recap",
    "snapshot summary", "overall tldr", "tl;dr overall",
    "state-of-play", "state of play", "topline summary", "quick overview",
    "overall recap", "brief rollup", "short overview", "quick brief",
    "executive summary", "status overview", "status at a glance", "fast recap", "rapid status summary", "fast overview",
    "complete recap", "quick rollup", "brief overview", "overall tldr", "quick status", "quick brief",
"fast summary", "speedy status summary", "brief summary", "complete summary", "brief recap", "quick summary of current information", "fast brief"
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

def _looks_like_correction(text: str) -> bool:
    if any(v in text for v in _CORRECTION_VERBS):
        # also require some domain hint to avoid overfiring
        if _detect_section(text) is not None:
            return True
        # or a direct assignment-like phrase (e.g., “change dbh to 30 inches”)
        assigners = {" to ", " = ", " should be ", " set to "}
        if any(a in text for a in assigners):
            return True
    return False

def _looks_like_section_summary(text: str) -> Optional[str]:
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

def _looks_like_quick_summary(text: str) -> bool:
    return _contains_any(text, _QUICK_SUMMARY_CUES) or text in {"summary", "summary please", "status", "quick summary"}

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
    service in {"MAKE_CORRECTION","SECTION_SUMMARY","QUICK_SUMMARY","MAKE_REPORT_DRAFT","NONE"}
    """
    t = _normalize(text)

    # 1) Correction
    if _looks_like_correction(t):
        sec = _detect_section(t)
        return ("MAKE_CORRECTION", sec)

    # 2) Section summary
    sec = _looks_like_section_summary(t)
    if sec:
        return ("SECTION_SUMMARY", sec)

    # 3) Quick summary
    if _looks_like_quick_summary(t):
        return ("QUICK_SUMMARY", None)

    # 4) Report draft
    if _looks_like_report_draft(t):
        return ("MAKE_REPORT_DRAFT", None)

    return ("NONE", None)
