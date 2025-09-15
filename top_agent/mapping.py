# top_agent/mapping.py
from __future__ import annotations
from typing import Any, Dict, Tuple

# ------------------------------------------------------------------------------
# Clarify helpers (centralized copy)
# ------------------------------------------------------------------------------

_MENU = (
    "• Section summary (name the section)\n"
    "• Outline (name the section or say 'use current section')\n"
    "• Full report draft\n"
    "• Apply a correction (name the section and the change)"
)

def _clarify_message(pkt: Dict[str, Any]) -> str:
    """For service=CLARIFY: offer a single, explicit choice."""
    hint = (pkt.get("result") or {}).get("note") or "I need a bit more to proceed."
    return f"{hint}\nPick one action:\n{_MENU}"

def _no_capture_message(current_section: str | None) -> str:
    """For Provide-Statement note='no_capture': nudge toward scorable facts."""
    sec = (current_section or "the current section").replace("_", " ").title()
    examples = (
        "Examples:\n"
        "• DBH: 30 in\n"
        "• Targets: driveway, playset\n"
        "• Risk item: 'low-hanging branch over driveway' (likelihood/severity if known)"
    )
    return (
        f"I didn’t find structured details to capture in {sec}.\n"
        "You can:\n"
        f"{_MENU}\n\n"
        "Or provide concrete facts for this section (numbers with units, short noun phrases).\n"
        f"{examples}"
    )

# ------------------------------------------------------------------------------
# Main mapping
# ------------------------------------------------------------------------------

def packet_to_template(pkt: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Deterministic mapping: Coordinator TurnPacket -> (template_reply, canvas_updates)
    canvas_updates example:
      {"outline": "risks"} or {"report": True}
    """
    res = pkt.get("result") or {}
    note = res.get("note")
    service = res.get("service")
    section = res.get("section")
    preview = (res.get("preview") or {})
    applied_paths = res.get("applied_paths") or []
    routed_to = pkt.get("routed_to")
    error = pkt.get("error")

    # ---------------- Blocked context edits ----------------
    if routed_to == "blocked_context_edit":
        return ("I can’t modify arborist/customer/location here—use the job setup screen.", {})

    # ---------------- Errors ----------------
    if error:
        return (f"Something went wrong: {error}. Try rephrasing or another action.", {})

    # ---------------- Provide-Statement path ----------------
    if service is None and routed_to and "extractor" in routed_to:
        # Successful capture
        if applied_paths:
            leafs = ", ".join(ap.split(".")[-1] for ap in applied_paths)
            return (f"Captured: {leafs}.", {})
        # No capture → show clarify/nudge menu
        if note == "no_capture":
            # prefer Coordinator-provided current_section if present in result; otherwise we
            # can’t read Coordinator state here, so fall back to section or None.
            cur = section  # Coordinator usually sets current_section onto result.section
            return (_no_capture_message(cur), {})
        # generic fallback (shouldn’t normally hit if note is set)
        return ("I didn’t find structured details. Which section would you like to add—Area Description, Tree Description, Targets, Risks, or Recommendations?", {})

    # ---------------- Request-Service path ----------------
    if service == "SECTION_SUMMARY":
        text = (preview.get("summary_text") or "").strip()
        # canvas update hints the UI to write/update the outline/summary file for that section
        return (f"Here’s your {str(section).replace('_',' ')} summary:\n{text}", {"outline": section})

    if service == "OUTLINE":
        text = (preview.get("summary_text") or "").strip()
        # If section is None, your controller/UI should default to current section
        return (f"Outline for {str(section).replace('_',' ')}:\n{text}", {"outline": section} if section else {})

    if service == "MAKE_REPORT_DRAFT":
        ex = (preview.get("draft_excerpt") or "").strip()
        return (f"Draft created. Preview:\n{ex}", {"report": True})

    if service == "MAKE_CORRECTION":
        if res.get("applied"):
            leafs = ", ".join(ap.split(".")[-1] for ap in (res.get("applied_paths") or []))
            return (f"Updated: {leafs}.", {})
        else:
            if section:
                return (f"I didn’t detect any fields to change in {section}. Want to restate the correction?", {})
            return ("I didn’t detect any fields to change. Which section should I correct?", {})

    if service == "CLARIFY":
        # Deterministic router + backstop couldn’t settle (or missing section)
        return (_clarify_message(pkt), {})

    # ---------------- Fallback ----------------
    return ("Okay.", {})
