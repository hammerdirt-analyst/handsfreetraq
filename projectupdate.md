# Arborist Report Assistant — Project Status

## Files & Responsibilities

- **`report_agent.py`**
  - **Coordinator**: Orchestrates turns (routing utterances to intent, domain classification, extractors, or report services).
  - **Domain classifier**: Uses `classify_data_domains_llm` to map user text to one or more report-editable sections.

- **`models.py`**
  - **Extractor schemas**: Pydantic models for strict LLM-facing envelopes.
  - Enforces `extra="forbid"`, `NOT_PROVIDED`, and typed field structure.

- **`report_state.py`**
  - **Report state container**: Canonical in-memory object for a report.
  - **Pydantic models** for all report sections: tree_description, area_description, risks, recommendations, etc.
  - Tracks `provided_fields` for provenance and completeness checks.

- **`report_context.py`**
  - Context models for *non-editable info*: arborist, customer, job number, GPS coordinates.
  - Supplies stable metadata for inclusion in summaries/drafts.

- **`intent_llm.py`**
  - **Intent classifier**: Routes high-level intent → `PROVIDE_STATEMENT` vs `REQUEST_SERVICE`.
  - Provides the top-level decision that tells coordinator whether to extract data or pass request to a service stub.

- **`runners.py`**
  - **Harness for live testing**: runs phrases through the pipeline, compares outcomes to `EXPECTATIONS`.
  - Logs intent/domain verdicts, state snapshots, and overall pass/fail.

- **`test_data.py`**
  - Fixture phrases and expected intent/domain outcomes.
  - Drives `runners.py` verification loop.

## 2. Dependencies

- **Outlines** — structured prompting interface for extractors.
- **OpenAI** — LLM backend (default: gpt-4o-mini, configurable).
- **Pydantic** — strict schema validation (internal state + external envelopes).
- **Python stdlib** — `json`, `typing`, `argparse`, `datetime`.

---

## 3. What Works Well

- **Coordinator pipeline is solid**
  Utterance → Intent → Domain(s) → Extractors → State → Report Agent.

- **Domain classifiers & extractors function reliably**
  Each section extractor is strict, verbatim-only, and produces deterministic fields (`NOT_PROVIDED` vs populated).

- **State model is authoritative**
  All data flows into `report_state`, keeping provenance with `provided_fields`.

- **Context separation**
  Arborist/customer/location info is stable and isolated in `report_context`, not touched by extractors.

- **Testing infrastructure exists**
  `runners.py` + `test_data.py` already give pass/fail runs and JSON logs of state after every turn.

---

## 4. Current Weak Spots

- **Recommendations routing is inconsistent**
  Some utterances are misclassified into `tree_description` or `area_description`.

- **No explicit conversation flow**
  Coordinator does not yet track `current_section` or “awaiting confirmation”, so guided multi-turn interaction is missing.

- **Correction mode not implemented**
  No way to overwrite or adjust prior state entries mid-conversation.

---

## 5. Roadmap

### A) Coordinator v1 (Guided Sections)
- Add `current_section`, `mode`, `pending_action` to `report_state`.
- Flow: **Area → Tree → Risks → Recommendations**, with summary + confirm at each step.

### B) Recommendations Fix
- Add fallback rule: if router fails JSON parse but rec cues present → route to recommendations.

### C) Corrections
- Define correction syntax: `"Correction: <field/value>"`.
- Coordinator patches `report_state` directly, with provenance log.

### D) Section Jumping & Freeform
- Recognize `"Section: Risks"` or `"Section: Tree"` → update `current_section`.
- Support multi-domain utterances (update >1 section if routed).

### E) Services Layer
- `REQUEST_SERVICE` intent stub → pass to specialized service agents:
  - Report Agent (summary, draft, what’s missing).
  - Q/A Agent.
  - Map Agent.

### F) Drafting & Exports
- Report Agent generates full draft (markdown).
- Later: export pipeline to PDF (reportlab).
