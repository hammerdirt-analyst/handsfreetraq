"""
agent_graph.py — Arborist Agent coordinator (ProvideData-driven)
Author: Roger Erismann (updated)

Pipeline:
  User utterance
     ↓
  Intent Tool → (single intent)
     ↓
  Coordinator
     ├── if PROVIDE_DATA:
     │       ProvideDataNode → (classify domains → extract → merge → notify)
     │       Coordinator formats the user-facing reply
     │
     ├── if REQUEST_SUMMARY/REPORT/WHAT_IS_LEFT:
     │       Report Node / What's Left
     │
     └── else:
             Small-talk, ask-field, etc.
"""

from typing import List

from models import ReportState
from nodes.report_node import ReportNode
from nodes.qa_node import QANode
from whats_left import compute_whats_left
from nodes.llm_backends import LLMUnavailableError
from nodes.llm_backends import LLM_BACKEND, OPENAI_MODEL, HF_MODEL
from intent_llm import classify_intent_llm
from nodes.llm_extractor import LLMExtractor
# NEW: ProvideData node (owns domain classification → extraction → merge → notify)
from provide_data_node import ProvideDataNode


def _flatten_updates(updates):
    """Return {'path.to.field': 'value', ...} for dict or Pydantic models."""
    if updates is None:
        return {}
    if hasattr(updates, "model_dump"):
        updates = updates.model_dump(exclude_none=True)
    out = {}

    def rec(prefix, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                rec(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(obj, list):
            # Summarize lists by count for now
            out[prefix] = f"{len(obj)} item(s)"
        elif obj is not None:
            out[prefix] = str(obj)

    rec("", updates)
    return out


class Coordinator:
    """
    Orchestrates the conversational flow:
      1) ingest utterance
      2) classify intent (LLM-only)
      3) route to nodes
         - ProvideDataNode for PROVIDE_DATA
         - Report/What's Left/Q&A for their intents
      4) format the user-facing reply (Coordinator is the ONLY speaker)
    """

    def __init__(self):
        self.state = ReportState()
        # Keep these around for debugging/telemetry; ProvideDataNode has its own extractor
        self.extractor = LLMExtractor()
        self.report = ReportNode()
        self.qa = QANode()
        self.provide = ProvideDataNode()

        # Console banner for backend/model visibility
        print("Extractor: LLMExtractor")
        active_model = OPENAI_MODEL if LLM_BACKEND == "openai" else HF_MODEL
        print(f"Extractor: LLMExtractor | Backend: {LLM_BACKEND} | Model: {active_model}")

    def _format_issues_note(self, issues: list[dict]) -> str:
        if not issues:
            return ""
        # map internal paths to friendly labels
        label = {
            "area_description.context": "area context",
            "tree_description.height_ft": "tree height",
            "tree_description.dbh_in": "trunk diameter (DBH)",
            "customer_info.phone": "customer phone",
            "arborist_info.license": "license",
        }
        normalized = []
        rejected = []
        for it in issues:
            action = (it.get("action") or "").lower()
            path = it.get("path", "")
            detail = it.get("detail", "")
            pretty = label.get(path, path.replace("_", " "))
            if action in ("normalized", "coerced"):
                normalized.append(pretty)
            elif action == "rejected":
                rejected.append(pretty)

        parts = []
        if normalized:
            parts.append("I normalized: " + ", ".join(sorted(set(normalized))[:3]) + ("…" if len(set(normalized)) > 3 else ""))
        if rejected:
            parts.append("I couldn’t use: " + ", ".join(sorted(set(rejected))[:3]) + ("…" if len(set(rejected)) > 3 else ""))
        return " ".join(parts).strip()

    def _append_narratives(self, narr_paths: List[str], text: str):
        for path in narr_paths:
            try:
                section, field = path.split(".", 1)
                arr = getattr(self.state, section).__getattribute__(field)
                if isinstance(arr, list):
                    arr.append(text)
            except Exception:
                # best-effort only
                continue

    def handle_turn(self, user_text: str) -> str:
        # 1) Ingest
        self.state = self.state.model_copy(update={"current_text": user_text})

        # 2) Classify intent first (via LLM intent tool)
        try:
            intent_out = classify_intent_llm(user_text)
            intent = intent_out.intent
        except Exception as e:
            return f"Intent classifier unavailable: {e}"

        # 3) Route on intent
        if intent == "SMALL_TALK":
            return "I didn’t catch anything I can add to the report. You can tell me things like customer name, address, tree species, measurements, or say “what’s left?”."

        if intent == "WHAT_IS_LEFT":
            remaining = compute_whats_left(self.state)
            if not remaining:
                return "All core items appear captured."
            return "\n".join(f"{sec}: {', '.join(fields)}" for sec, fields in remaining.items())

        if intent in ("REQUEST_SUMMARY", "REQUEST_REPORT"):
            mode = "summary" if intent == "REQUEST_SUMMARY" else "report"
            cue = f"Preparing your {mode}…"
            result = self.report.handle(mode, self.state)
            return f"{cue}\n{result}"

        if intent == "ASK_QUESTION":
            return "Q&A not enabled yet — soon I’ll answer questions about the current report."

        if intent != "PROVIDE_DATA":
            return "I’m not sure what to do with that yet. You can give me report details or say “what’s left?”."

        # 4) PROVIDE_DATA path → ProvideDataNode (domains → extraction → merge)
        try:
            new_state, pd = self.provide.handle(user_text, self.state)
        except LLMUnavailableError as e:
            return f"LLM backend unavailable: {e}"
        except Exception as e:
            # Any unexpected error from the node
            return f"Extraction pipeline error: {e}"

        # If nothing extracted, Coordinator communicates that to the client
        if not getattr(pd, "extracted", False):
            return "I didn’t understand that — could you rephrase?"

        # Commit new state
        self.state = new_state
        parts: List[str] = []

        # 5) Surface validation issues (normalized/rejected), then clear
        try:
            issues = getattr(self.state.meta, "issues", []) or []
            if issues:
                note = self._format_issues_note(issues)
                if note:
                    parts.append(note)
                self.state.meta.issues = []
        except Exception:
            pass

        # 6) Append any narratives captured by the node/extractor
        if getattr(pd, "narrate_paths", None):
            self._append_narratives(pd.narrate_paths, user_text)

        # 7) Track explicit declines
        if getattr(pd, "declined_paths", None):
            self.state.meta.declined_paths.extend(pd.declined_paths)

        # 8) Build the user-facing response
        if getattr(pd, "confirmation_stub", ""):
            parts.append(pd.confirmation_stub.strip())

        captured_kv = _flatten_updates(pd.updates if hasattr(pd, "updates") else {})
        if captured_kv:
            head_items = list(captured_kv.items())[:6]
            parts.append(
                "Captured: " + "; ".join(f"{k}={v}" for k, v in head_items)
                + ("…" if len(captured_kv) > 6 else "")
            )

        # Include any lingering note and clear it
        issue_note = getattr(self.state.meta, "_last_issue_note", "").strip()
        if issue_note:
            parts.append(issue_note)
            try:
                self.state.meta._last_issue_note = ""
            except Exception:
                pass

        return " ".join(parts).strip() or "Noted"
