# 🖐️ Hands Free TRAQ

**Hands Free TRAQ** is a voice-first application that guides users through the process of completing the ISA TRAQ (Tree Risk Assessment Qualification) form entirely hands-free. 

## 🌳 Arborist agent -- the first stop on the way to hands free TRAQ

The **Arborist Report Assistant** is a Python-based conversational system that helps arborists capture, structure, and generate tree risk assessment reports.
It transforms free-form observations into structured report data with **provenance**, enabling reliable summaries, corrections, and full report drafts.

---

## 📐 Architecture Overview

```mermaid
graph LR
  A[TopChatAgent (conversation)] -->|turn| B[Coordinator (coordinator_agent.py)]
  B -->|intent classification| C[intent_model.py]
  B -->|deterministic routing| D[service_router.py]
  B -->|backstop| E[ServiceRouterExtractor (models.py)]
  B -->|extract structured data| F[extractor_registry.py → section extractors]
  B -->|apply updates| G[ReportState (report_state.py)]
  B -->|guard context| H[ReportContext (report_context.py)]
  B -->|render| I[SectionReportAgent, ReportAgent]
  B -->|corrections| J[CorrectionsAgent]
  B -->|log| K[app_logger.py]
```

---

## 🧠 Core Components

### **Coordinator (`coordinator_agent.py`)**

* The orchestrator: classifies intent, routes requests, merges updates.
* Two main paths:

  * **Provide Statement** → extract data into `ReportState`.
  * **Request Service** → summaries, outline, draft, or corrections.
* Blocks context edits (arborist/customer/location).
* Logs every turn with routing transparency + correlation IDs.

### **Segmentation (`segment.py`)**

* Splits free text into section-scoped segments.
* Deterministic lexicon + cursor fallback.
* Falls back to LLM segmentation if confidence is low.

### **Extractors (`extractor_registry.py` + `models.py`)**

* One extractor per report section (`tree_description`, `risks`, `targets`, etc.).
* Strict Pydantic schemas; `NOT_PROVIDED` sentinel prevents clobbering.

### **Corrections (`corrections_agent.py`)**

* Runs a section extractor on correction text.
* Normalizes shapes so scalars overwrite, lists append.
* Stateless — Coordinator merges corrections into state.

### **State & Provenance (`report_state.py`)**

* Canonical container for report data.
* Merge policies:

  * **Lists** → append.
  * **Scalars** → prefer-existing or last-write (for corrections).
* Every applied update yields a provenance row: section, path, value, extractor, timestamp.

### **Service Routing**

* **Deterministic** (`service_router.py`) handles corrections, section summaries, outlines, drafts.
* **LLM backstop** (`ServiceRouterExtractor` in `models.py`) runs only if deterministic router returns `NONE`.

### **Service Agents**

* `SectionReportAgent`: produces prose or outline summaries for one section.
* `ReportAgent`: generates a full Markdown draft with headings, paragraph IDs, and “Editor Comment” notes.
* `CorrectionsAgent`: single-section corrections with overwrite semantics.

### **Error Handling (`error_handler.py`)**

* Unified error envelopes (`code`, `origin`, `retryable`, `user_message`, `next_actions`, …).
* Ensures consistent handling and logging across all paths.

---

## 📂 File & Data Layout

### **Local Store**

```
local_store/
  inbox/        # jobs pending acceptance
  reports/      # accepted jobs (context.json, state.json, turn_log.jsonl, canvas/)
  outbox/       # exports (markdown, pdf)
```

### **Exports**

* **Markdown (`.md`)** — sectioned draft with provenance-aware omissions notes.
* **PDF (`.pdf`)** — finalized report.
* **JSONL logs** — turn packets, correlation IDs, router transparency.

---

## 🧰 Tech Stack

| Layer          | Technology                        |
| -------------- | --------------------------------- |
| Core logic     | Python 3.11+                      |
| Models & state | Pydantic                          |
| LLM calls      | Outlines + OpenAI (configurable)  |
| Tests          | pytest                            |
| Export         | reportlab (PDF), Markdown writers |
| CLI            | click / argparse                  |
| Logging        | JSONL logs via `app_logger.py`    |

---

## ✅ Current Status

* Coordinator is stable: context guard, segmentation, routing, provenance logging.
* Provide-Statement → extractors → state merge path is **fully tested**.
* Request-Service path covers summaries, outline, corrections, and drafts.
* Errors travel in structured envelopes, logs are machine-readable and consistent.
* CLI supports job lifecycle: inbox → accept → chat → export.

---

## 🗺️ Roadmap

1. **Conversational flow**: clarify loops when no capture / low confidence.
2. **Summaries & Drafts**: persist outputs in state with provenance.
3. **Corrections UX**: confirmations after merge, diff-style feedback.
4. **Normalization**: spacing/quotes cleanup; field-specific list vs scalar policies.
5. **CI & Coverage**: add pytest-cov, gating on unit+integration, keep “full” optional.
6. **Operator guide**: log reading, reproduction, rollback knobs.

---

Would you like me to also **include a “Quick Start” section** in the README (CLI examples like `python cli.py jobs inbox`, `chat --job 1`, `export pdf`), so new developers can run the system right away?
