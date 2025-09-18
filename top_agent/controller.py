#!/usr/bin/env python3
# top_agent/controller.py
from __future__ import annotations

"""
TopChatAgent — thin, job-first conversation orchestrator around the Coordinator.

Responsibilities
---------------
- Open a report job (load ReportContext + ReportState) using LocalStore's job-first API.
- Run one user turn through Coordinator.handle_turn(user_text).
- Deterministically map the Coordinator TurnPacket to a user-facing reply (mapping.packet_to_template).
- Optionally guardrail-rephrase the reply (top_agent.rephraser.rephrase).
- Persist updated state + append a turn-log line via LocalStore.
- Best-effort write canvas artifacts (outline/report) for operator visibility.
- Export report artifacts on demand.

Non-responsibilities
--------------------
- No filesystem knowledge (paths/layout are entirely LocalStore’s concern).
- No intent/service logic (that lives in the Coordinator).
- No UI state beyond returning reply text and optional footer lines.

Public API (used by cli.py)
---------------------------
TopChatAgent(store: LocalStore, *, rephrased: bool = True)

open_by_job(job_number: int | str) -> None
open_or_create(job_number: int | str, context: ReportContext) -> None
handle(user_text: str) -> dict   # {"packet","reply","footer"}
export(fmt: str) -> dict         # {"path": <str>}
"""

from typing import Any, Dict, Optional

from arborist_report.report_context import ReportContext
from arborist_report.coordinator_agent import Coordinator
from top_agent.local_store import LocalStore
from top_agent.mapping import packet_to_template
from top_agent.rephraser import rephrase as _rephrase_fn
from arborist_report import app_logger


class TopChatAgent:
    def __init__(self, store: LocalStore, *, rephrased: bool = True) -> None:
        """
        Args:
            store: LocalStore instance exposing a job-first API.
            rephrased: If True, pass mapped replies through the guardrailed rephraser.
        """
        self.store = store
        self._rephrase_enabled = bool(rephrased)
        self._rephrase = _rephrase_fn

        self.job_number: Optional[str] = None
        self.coordinator: Optional[Coordinator] = None

    # ---------- Session management ----------

    def open_by_job(self, *, job_number: int | str) -> None:
        """
        Open an accepted job from local storage.

        Loads ReportContext + ReportState via LocalStore (job-first),
        then constructs a Coordinator for this session and injects the loaded state.
        """
        job = str(job_number)
        ctx = self.store.read_context(job)        # raises FileNotFoundError if missing
        state = self.store.read_state(job)        # returns default ReportState if missing
        self.job_number = job

        # Coordinator takes context only; we then inject the loaded state.
        self.coordinator = Coordinator(context=ctx)
        self.coordinator.state = state

    def open_or_create(self, *, job_number: int | str, context: ReportContext) -> None:
        """
        Create (or open) a job with the provided ReportContext.

        The LocalStore is expected to have already created the report scaffold.
        We load existing state (or a default) and inject it.
        """
        job = str(job_number)
        state = self.store.read_state(job)
        self.job_number = job

        self.coordinator = Coordinator(context=context)
        self.coordinator.state = state

    # ---------- Turn handling ----------

    def handle(self, user_text: str) -> Dict[str, Any]:
        """
        Run a single user turn and persist effects.

        Returns:
            {
              "packet": <TurnPacket dict from Coordinator>,
              "reply": <string>,
              "footer": <optional string with canvas file paths>
            }
        """
        if not self.coordinator or not self.job_number:
            raise RuntimeError("TopChatAgent is not open. Call open_by_job() or open_or_create().")

        # 1) Coordinator → TurnPacket
        pkt: Dict[str, Any] = self.coordinator.handle_turn(user_text)


        # 2) Deterministic mapping to reply + canvas hints
        reply_text, canvas_updates = packet_to_template(pkt)

        # 3) Optional guardrailed rephrase (numbers/IDs/quotes preserved)
        if self._rephrase_enabled and reply_text:
            reply_text = self._rephrase(reply_text)

        # 4) Persist state + turn log (job-first)
        job = self.job_number
        self.store.write_state(job, self.coordinator.state)
        if hasattr(self.store, "append_turn_log"):
            try:
                self.store.append_turn_log(job, pkt)
            except Exception:
                pass  # best-effort

        # 5) Canvas side-effects (best-effort, never crash)
        footer_lines = []
        result = (pkt.get("result") or {})
        preview = result.get("preview") or {}

        if canvas_updates:
            try:
                if canvas_updates.get("outline") and hasattr(self.store, "write_outline"):
                    sec = canvas_updates["outline"]
                    path = self.store.write_outline(job, section=sec, text=preview.get("summary_text", "") or "")
                    if path:
                        footer_lines.append(f"[outline] {sec}: {path}")
            except Exception:
                pass
            try:
                if canvas_updates.get("report") and hasattr(self.store, "write_report"):
                    path = self.store.write_report(job, text=preview.get("draft_excerpt", "") or "")
                    if path:
                        footer_lines.append(f"[report] {path}")
            except Exception:
                pass

        footer = "\n".join(footer_lines) if footer_lines else None
        app_logger.log_turn_packet(pkt, job_id=self.job_number)
        return {"packet": pkt, "reply": reply_text, "footer": footer}

    # ---------- Export ----------

    def export(self, fmt: str) -> Dict[str, Any]:
        """
        Export the current job’s report via LocalStore (job-first).

        Args:
            fmt: "md" or "pdf"
        Returns:
            {"path": "<absolute or project-relative path to artifact>"}
        """
        if not self.job_number:
            raise RuntimeError("No job is open.")
        out_path = self.store.export_report(self.job_number, fmt=fmt)
        return {"path": out_path}
