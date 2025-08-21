I’ve updated your **project plan** to reflect the current state of progress (with the working LLMExtractor, schema-constrained date extraction, and early conversational flow), and laid out a **roadmap** for the next steps.

Here’s the revised document:

---

# Project: Arborist Report Conversational Agent

### Purpose

A conversational agent that incrementally collects data for arborist tree inspection reports, storing structured fields and narratives, and generating summaries/reports.

---

## Contracts (Stable Interfaces)

These define the “public contracts” we will preserve across phases.

### 1. **State Contract**

* State is a Pydantic model (`ReportState`) with sections:

  * `inspection`: date, location, etc.
  * `arborist_info`: name, license, etc.
  * `site_history`: narratives list
  * `defects_risk`: narratives list
  * `meta`: audit / declined paths
* Supports merging updates (`model_merge_updates`).
* Used everywhere downstream — never bypassed.

### 2. **Extractor Contract**

* Input: free-form `utterance: str`
* Output: `ExtractorOutput` Pydantic model:

  * `updates: Dict[str, Any]` — structured field updates
  * `narrate_paths: List[str]` — where to append narratives
  * `declined_paths: List[str]` — user refused fields
  * `utterance_intent: Literal[...]` — core intent classification
  * `ask_field_targets: Optional[List[str]]` — for ASK\_FIELD intent
  * `confirmation_stub: str` — optional acknowledgement ("Noted.")

### 3. **Coordinator Contract**

* Orchestrates interaction:

  1. Capture user input in state
  2. Call extractor
  3. Merge updates + narratives
  4. Route by intent:

     * `ASK_FIELD` → echo field status
     * `WHAT_IS_LEFT` → compute missing fields
     * `REQUEST_SUMMARY` / `REQUEST_REPORT` → call ReportNode
     * Default → confirmation only
* Response is always a plain text string.

### 4. **Report / QA Contracts**

* **ReportNode**: given mode (`"summary"` or `"report"`) + `ReportState` → formatted text.
* **QANode**: for direct factual Q\&A (stubbed).

---

## Phase Milestones

### **Phase 1 (Complete)**

* Repo scaffolded with core modules.
* `MockExtractor` and Coordinator implemented.
* Basic “Noted.” confirmation working.

### **Phase 2.1 (Complete)**

* Added **LLMExtractor wrapper** (delegating to MockExtractor).
* Coordinator supports extractor switching by flag.
* Tests for extractor switching, “what’s left”, and ASK\_FIELD.

### **Phase 2.2 (Complete)**

* **Schema-constrained LLM extraction for inspection.date.**
* Graceful fallback to “not provided” on invalid/missing values.
* Tests for valid/invalid parsing.
* Centralized Pydantic models created (`models.py`).
* Unified `ReportState` model with explicit `"not provided"` defaults.

### **Phase 2.3 (Complete)**

* Created `whats_left.py` to compute missing fields against schema.
* Coordinator integrated with `compute_whats_left`.

### **Phase 2.4 (Complete)**

- ✅ **LLMExtractor** routes all *provide-data* utterances through **Outlines+OpenAI** with a single, full **Pydantic schema** (`_FullLLMOutput`), not just a subset.  
  - **Sections covered:** `arborist_info`, `customer_info`, `tree_description`, `area_description`, `targets`, `risks`, `recommendations` (full map present; 2.4’s target set is fully included).

- ✅ **MockExtractor** removed from the extraction path for *provide-data* (no fallback; if LLM fails, app surfaces the error).

- ✅ **Schema-constrained generation:** Outlines `generate.json()` with a **strictified JSON Schema**; Pydantic’s `model_validate()` enforces structure on return.

- ✅ **Backend control:** OpenAI primary, HF stub present and intentionally hard-fails. CLI `--backend` and env `LLM_BACKEND` wired.

- ✅ **Coordinator** unchanged behavior-wise (merges updates, narrates, computes “what’s left”); now receives real updates from LLMExtractor.

- ✅ **Manual sanity test passes** (from your transcript): multiple utterances update state; “what’s left” shrinks appropriately.

---


### ✅ What’s done in 2.5 (Validation Layer)

- **Validators wired & tested**
  - Enum mapping + graceful fallback for unknowns.
  - Numeric coercions & bounds (e.g., `height_ft`, `dbh_in`) with **issues** recorded.
  - `IssueBucket` plumbed through `model_validate(context=...)` and **carried into `ReportState.meta.issues`** on merge.
- **Schema-constrained extraction stays strict**
  - Outlines `generate.json(...)` uses a **strictified schema** (no `additionalProperties`, required fields enforced).
  - Pydantic `model_validate()` still the final gate.
- **End-to-end flow remains stable**
  - Coordinator merges updates and “what’s left” reflects reductions after each utterance.
- **Tests are green**
  - `pytest` summary: **6 passed** (incl. validation behavior, “what’s left”, merge & issues accumulation).

#### 📊 Current Test Coverage Snapshot

- **Models/Validation:** enums, coercions, range checks, issues accumulation ✅  
- **Extraction Path (mocked LLM):** structured updates present, intent correct ✅  
- **What’s Left logic:** correct field inventory ✅  
- **Pending:** Coordinator issue surfacing, empty utterance behavior, strictifier unit test, format validators tests ⏳

## Roadmap

### Increment 2.5 – Validation Layer Finish field validators (enum maps, numeric ranges) — quick wins.

* Cross-field constraints for risks and recommendations.
* Issues plumbing so users get immediate feedback (“normalized X”, “rejected Y”).
* Unit tests for each rule + a few end-to-end tests (utterance → state).
* Tuning pass (expand synonym maps as you see real data).
* (Optional) Soft prompts: when a critical field is still NOT_PROVIDED, set utterance_intent="ASK_FIELD" with targeted follow-ups.

* Add stricter validation for:

  * Addresses (split into components)
  * Phone numbers
  * Date formats
* Always fallback to “not provided” gracefully.

#### 📁 File-Level Import Graph (Phase 2.5)

- main.py  
  - agent_graph.py  
    - models.py  
    - whats_left.py  
      - models.py  
    - qa_node.py  
      - models.py  
    - extractor_node.py  
      - models.py  
      - llm_extractor.py  
        - llm_backends.py  
    - report_node.py  
      - models.py  
      - llm_extractor.py  
        - llm_backends.py  

- state.py (legacy / redundant; replaced by models.py)

#### 🧪 Hardening (2.5)  before 2.6

- **Surface issues to the user (Coordinator)**
  - Add a short, batched note when `meta.issues` has entries:
    - _“Normalized: area_description.context (suburban) …; Rejected: tree_description.height_ft (420 out of range) …”_
  - **Test:** feed a payload that triggers both “normalized” & “rejected” and assert the Coordinator text contains both.
- **Empty/irrelevant utterances**
  - Confirm extractor returns either `SMALL_TALK` intent **or** no updates.
  - **Test:** utterances like “okay”, “thanks”, or whitespace → assert intent & no updates.
- **LLM strictness smoke test**
  - Ensure `outlines_generate_schema_constrained` indeed sets `additionalProperties: false` and passes a stringified schema.
  - **Test:** unit test the strictifier (no call to OpenAI) to assert the JSON schema is locked down.
- **Format validators (targeted quick wins)**
  - **Phone numbers:** trim/normalize digits; reject impossible lengths.
  - **Dates:** accept common formats; normalize to ISO (`YYYY-MM-DD`); log issues on failure.
  - **Addresses:** confirm split fields are respected; log issue if an address blob slips in.
  - **Tests:** 1–2 unit tests per formatter (valid → normalized; invalid → `NOT_PROVIDED` + issue).

> **Nice-to-have (keep in 2.5 if time permits):**
- **Cross-field constraints** (e.g., recommendations present only if context implies work; risk severity aligns with scope).  
- **Soft prompts:** if critical fields remain `NOT_PROVIDED`, set `utterance_intent="ASK_FIELD"` with a single targeted follow-up.

#### 🚦 Go/No-Go to 2.6

**Go to 2.6** once all below are ✅:
- [ ] Coordinator surfaces `meta.issues` in user responses (with truncation logic).
- [ ] Empty/irrelevant utterances produce `SMALL_TALK` (or no updates); tested.
- [ ] Strictifier test proves schema is **closed** (`additionalProperties: false`) and **required** keys are enforced.
- [ ] Phone/date/address format validators implemented with unit tests.

### **Phase 2.6 – Intent Separation (Tool-Call Model)**

* Promote **utterance intent** to first-class tool call.
* Coordinator explicitly dispatches to nodes:

  * `ProvideDataNode`
  * `AskFieldNode`
  * `WhatsLeftNode`
  * `ReportNode`
  * `QANode`
* Extractor limited to **context + data extraction** only.
* Clarify flow: context first → intent dispatch → node executes.

---

### **Phase 2.7 – Conversational Flow**

* Integrate proactive suggestions:

  * `WhatsLeftNode` surfaces missing fields.
  * Optional “Would you like to provide X?” stubs.
* Ensure compliance: agent never instructs, only responds.

---

### **Phase 3 – Reporting Agent**

* Build **ReportAgent node**:

  * Export reports as PDF/DOCX.
  * Arborist report formatting.
  * Later: embed situational maps, charts.

---

### **Phase 4 – Persistence & Visualization**

* Save/load report states.
* Multi-format export (Word, PDF).
* Visualizations: charts, maps, risk overlays.

---
