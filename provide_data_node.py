from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple

from models import ReportState
from nodes.llm_extractor import LLMExtractor
from nodes.data_domain_classifier import classify_data_domains

@dataclass
class ProvideDataResult:
    extracted: bool
    domains: List[str]
    updates: Dict[str, Any]
    narrate_paths: List[str]
    declined_paths: List[str]
    confirmation_stub: str

class ProvideDataNode:
    def __init__(self):
        self.extractor = LLMExtractor()

    def _scope_to_domains(self, updates: Dict[str, Any] | None, domains: List[str]) -> Dict[str, Any]:
        if not updates:
            return {}
        if hasattr(updates, "model_dump"):
            updates = updates.model_dump(exclude_none=True)
        allow = set(domains or [])
        if not allow:
            return {}
        return {k: v for k, v in (updates or {}).items() if k in allow and v not in (None, "", [], {})}

    def _extract_force(self, text: str):
        try:
            return self.extractor.extract(text, force=True)  # if extractor supports it
        except TypeError:
            return self.extractor.extract(text)

    def handle(self, user_text: str, state: ReportState) -> Tuple[ReportState, ProvideDataResult]:
        # 1) LLM: domains first
        dom_res = classify_data_domains(user_text)
        domains = dom_res.domains
        print(f"[ProvideData] Domains: {domains}")  # debug

        # 2) LLM: structured extraction
        out = self.extractor.extract(user_text, domains=domains)

        # 3) Scope to domains
        scoped = self._scope_to_domains(getattr(out, "updates", {}), domains)
        # tiny debug: show top-level keys captured
        if isinstance(scoped, dict):
            print(f"[ProvideData] Updates keys: {list(scoped.keys())}")

        if not scoped:
            return state, ProvideDataResult(False, domains, {}, [], [], "")

        # 4) Merge into state
        new_state = state.model_merge_updates(scoped)

        # 5) Notify Coordinator (structured, Coordinator will speak)
        return new_state, ProvideDataResult(
            extracted=True,
            domains=domains,
            updates=scoped,
            narrate_paths=getattr(out, "narrate_paths", []) or [],
            declined_paths=getattr(out, "declined_paths", []) or [],
            confirmation_stub=(getattr(out, "confirmation_stub", "") or "Noted.").strip(),
        )
