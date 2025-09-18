Love this direction. Here’s a lean testing plan that gives us high confidence without bloat.

# What to test + how

## 1) Context & forbidden fields enforcement

**Goal:** coordinator blocks attempts to edit arborist/customer/location (and lat/long).
**Unit tests (pure):**

* Inputs that mention customer/arborist fields (“set customer email…”, “lat 38.58”).
* Assert: intent = PROVIDE\_STATEMENT → routed\_to = `blocked_context_edit`; no state mutation; helpful note present.
* Negative controls: similar wording that *isn’t* a context edit (“customer parking lot…” in targets) → not blocked.

**Integration (pipeline):**

* Feed 10–20 mixed phrases via Coordinator; assert state unchanged; log contains `blocked_context_edit`.

## 2) Intent classification & routing

**Goal:** high precision intent decisions; stable when phrasing varies.
**Unit tests:**

* Param tests for clear PROVIDE\_STATEMENT vs REQUEST\_SERVICE vs other (small-talk, questions).
* Boundary phrasing (“could you summarize…” vs “summary of targets”) to ensure REQUEST\_SERVICE.

**Integration:**

* 200–300 phrases corpus → assert `(intent, routed_to)` pairs; export a confusion matrix summary to console.

## 2a) Provide Statement path

**Sub-goals:** segmentation, correct extractor picked, correct merge semantics, provenance, errors.

**Unit tests (focused):**

* **Segmentation parser** (`_parse_scoped_segments`):

  * Single scope, multiple scopes, leading text before first scope, trailing scope with empty payload.
  * Assert the ordered `(section, payload)` tuples exactly.
* **State merge** (`ReportState.model_merge_updates`):

  * Scalars (overwrite policy), lists (append semantics), “Not provided” ignored, “empty list” ignored.
  * Provenance rules: one row only when something applied; otherwise single `Not Found` line with segment text.
  * “Prefer existing” policy: existing provided + incoming sentinel → no change, no prov.
* **Envelope “has provided”**: verify truth table for strings, lists, None.

**Integration (pipeline):**

* Feed phrases that set height, DBH, and append roots/defects; then a correction.
* Assert:

  * State values match.
  * Provenance shows one row per *applied* field with correct `text`, `path`, `value`.
  * When nothing extracted → single `Not Found`.

**Error/ambiguity handling:**

* Force extractor to raise (stub/mocked) → coordinator returns `ok=False` with `ProvideData error` and logs TURN.
* Ambiguous multi-scope with empty payload → segment note `navigation_only`; no state changes; one `Not Found` provenance for that segment.

## 2b) Request Service path

**Sub-goals:** deterministic router first, LLM-backstop only on NONE; correct section propagation; clarify on low confidence.

**Unit tests (deterministic router):**

* Already strong set (200+). Keep extending lexicons (the 14 misses you surfaced).
* Add explicit tests for section inference via field hints (e.g., “alter crown shape…” → tree\_description).

**Unit tests (LLM backstop – mocked):**

* Patch classifier to return each service with/without section and confidence around threshold:

  * Deterministic = `NONE`, LLM = high confidence → expect service/section from LLM.
  * Deterministic = `NONE`, LLM = low confidence → expect `service=CLARIFY`, `section=None`, note present.
  * Deterministic decides → LLM not called (verify via mock call count).

**Integration (pipeline):**

* Full Coordinator run for:

  * SECTION\_SUMMARY requests (each section) → ensure downstream agent stub would receive the section.
  * QUICK\_SUMMARY → section is None.
  * MAKE\_REPORT\_DRAFT → section None, agent stub path.
  * MAKE\_CORRECTION → section set or None depending on phrasing.

**Logging assertions:**

* Every turn produces a `TURN` block; REQUEST\_SERVICE with fallback sets `routed_to = "RequestService → deterministic → llm_backstop"` when used.
* Add a tiny helper to tail the log and assert the last block header + payload keys exist.

---

# Multiphrase coverage

**Unit (segmentation):**

* Strings with multiple explicit scopes and interleaved text:

  * “Area Description: … Targets: … Risks: …”
  * With extra leading: “Also note … Area Description: …”
* Assert: segment order and payload splits exact.

**Integration:**

* Send a multiphrase into Coordinator; assert:

  * Each segment calls the correct extractor (use stub that records invocations).
  * State reflects combined updates (lists appended; scalars last-write depending on policy).
  * Provenance contains one row per *applied* path for each segment (not a full field sweep).

---

# Structure of the test suite

* **/tests/unit/**

  * `test_context_block.py`
  * `test_segmentation.py`
  * `test_service_router.py` (deterministic)
  * `test_state_merge.py` (provenance + merge semantics)
  * `test_request_service_backstop.py` (mock LLM)
  * `test_intent_classifier.py` (mock model; or snapshot inputs→labels)

* **/tests/integration/**

  * `test_pipeline_provide_statement.py` (end-to-end with stubbed extractors returning canned envelopes)
  * `test_pipeline_request_service.py` (end-to-end routing to stubs, sections forwarded)
  * `test_logging_stability.py` (ensure logfile grows and contains blocks)

* **/tests/corpora/**

  * Plain text files (one phrase per line) for bulk runs:

    * `provide_statement_200.txt`
    * `request_service_300.txt`
  * A runner that:

    * Pipes each line through Coordinator.
    * Tallies accuracy per category (intent, service, section).
    * Optionally writes a CSV of failures with reason.

---

# Test data strategy

* **Golden cases** for each section field, including numeric formatting variants (e.g., `dbh 32"`, `dbh 32 in`, `diameter 32 inches`) and verify normalization in extractor output.
* **Corrections**: first set a value, then change it; assert provenance shows two events (both applied), final state equals corrected value.
* **Negatives**: near-miss phrases that *should not* trigger a summary/report or correction.
* **No-ops**: extractor returns only sentinels → single `Not Found` provenance row.

---

# Determinism & speed

* Seed any randomness (though we’re at temperature=0).
* Mock LLMs/extractors by default in unit tests.
* Run real model only in the “live corpus” suite, not in CI by default.

---

# Coverage targets (pragmatic)

* Unit layer: >90% of coordinator, router, state merge, segmentation.
* Integration: at least one test touches each code path including errors/clarify branch.
* Corpus runs: report pass rate per category and list top failing n-grams to drive lexicon tweaks.

great—let’s line up the integration plan so we can knock them out cleanly and keep everything deterministic (no live model calls).

# overall approach

* keep the **Coordinator** real.
* **stub anything that talks to models** (intent\_llm, ModelFactory-backed extractors, LLM backstop).
* use a **real ReportState** so we exercise merging + provenance.
* use **tmp\_path** for logs; don’t silence logging in these tests—verify it.

# common test scaffolding (fixtures)

* **context fixture**: `ReportContext._build_context_from_testdata()` (as you suggested).
* **coordinator fixture**: builds a Coordinator with:

  * `report_agent.COOD_LOG` → `tmp_path / "coordinator-tests.txt"`
  * `report_agent._write_log` → the real function (so it writes)
  * `report_agent.classify_intent_llm` → param-patched per test (either PROVIDE\_STATEMENT or REQUEST\_SERVICE)
  * `extractor_registry.default_registry()` → monkeypatch to a **FakeRegistry** that returns canned extractors by section.
* **fake extractors** (per section):

  * each exposes `extract_dict(text, **kwargs)` and returns a canned envelope you control per test case.
  * also let one return “no capture” (empty or NOT\_PROVIDED) so we assert the single `Not Found` provenance row.
* **service router knobs**:

  * deterministic router: keep real.
  * LLM backstop: monkeypatch `service_classifier.ServiceRouterClassifier` (or the factory method you chose) to return canned `(service, section, confidence)`.

---

## 1) `tests/integration/test_pipeline_provide_statement.py`

**goal**: end-to-end “Provide Statement” path, including multi-scope parsing, extractor calls, state merge, and provenance.

**setups to include**

1. **single-scope**:

   * intent → PROVIDE\_STATEMENT
   * utterance: `tree description: dbh 26 in`
   * fake `TreeDescriptionExtractor` returns:

     ```json
     {"updates": {"tree_description": {"dbh_in": "26", "height_ft": "Not provided"}}}
     ```

   **assert**:

   * coordinator result `ok=True`, `note=captured`
   * state fields updated
   * provenance has rows for `tree_description.dbh_in` only (no row for `height_ft` since NOT\_PROVIDED)
2. **multi-scope**:

   * utterance: `tree description: height 45 ft targets: walkway occupied daily`
   * two extractor calls in order; each returns a minimal envelope.
     **assert**:
   * `segments` shows two segments in order
   * state updated in both sections
   * last `current_section` = `targets`
   * provenance has at least one row per segment (and paths match)
3. **lead-in + scoped**:

   * current\_section = `area_description`
   * utterance: `foot traffic is moderate; tree description: dbh 30 in`
   * first segment goes to `area_description` extractor; second to `tree_description`.
     **assert**: both applied; provenance has two blocks/rows accordingly.
4. **navigation-only**:

   * utterance: `targets:` (nothing after colon)
   * extractor should **not** be called; segment `note=navigation_only`.
     **assert**: result contains that segment; **no state change**; **no provenance row** for that segment.
5. **no-capture**:

   * utterance: `tree description: [garbled]`
   * fake extractor returns either `{}` or `{ "updates": { "tree_description": {} } }`
     **assert**:
   * `ok=True` with `note=no_capture`
   * **one** provenance row with `path="Not Found"` / `value="Not Found"`.

**edge**:

* policy guard: seed state with a provided value, have extractor emit `NOT_PROVIDED`—ensure no overwrite under `prefer_existing` and no provenance row (unless overall segment has nothing → single Not Found row).

---

## 2) `tests/integration/test_pipeline_request_service.py`

**goal**: end-to-end “Request Service” routing (deterministic first; LLM backstop on NONE). We’re not executing summary/report agents yet—just verifying the coordinator’s **routing decision** and payload.

**setups to include**

1. **deterministic hit**:

   * intent → REQUEST\_SERVICE
   * phrase: `targets section summary`
   * **assert**: result `service="SECTION_SUMMARY"`, `section="targets"`, `ok=True`, state unchanged.
2. **NONE → LLM backstop (high confidence)**:

   * phrase deliberately outside deterministic cues (e.g., `give me executive rollup`)
   * monkeypatch backstop to return `QUICK_SUMMARY, section=None, confidence=0.9`
   * **assert**: service reflects backstop; `routed_to` string shows `… llm_backstop`; ok=True.
3. **NONE → LLM backstop (low confidence)**:

   * backstop returns `confidence=0.3`
   * **assert**: result `service="CLARIFY"`, ok=True, explanatory `note`.
4. **exceptions are contained**:

   * make backstop raise; expect `error` set, `ok=False`, and no crash.

* phrases covering the four service types + a couple with explicit sections for corrections.

---

## 3) `tests/integration/test_logging_stability.py`

**goal**: verify that our logger always writes well-formed blocks and never crashes the turn.

**setup**

* use `tmp_path / "coordinator-tests.txt"`; do **not** stub `_write_log`.
* parametrize a small script of turns:

  1. provide statement → captured
  2. provide statement → navigation only
  3. provide statement → no capture
  4. request service → deterministic
  5. request service → backstop
  6. context-edit block

**assertions**

* file exists and grows after each turn (compare `stat().st_size`).
* read the file; for each block (split on `=` line):

  * has a header line with ISO timestamp + block title (`[...Z] TURN`)
  * has a JSON payload we can `json.loads`
  * payload includes keys: `"utterance","intent","routed_to","ok","result","error"`
  * for provide-statement success, `result.segments` is a list.
  * assert that `routed_to` strings match the expected path for each scripted turn.

**fault-injection**

* monkeypatch an extractor to raise; ensure the **turn returns** `ok=False` but the log still writes a block.

---

## execution order

1. land the **fixtures** + canned fake extractors.
2. implement **Provide Statement** integration tests first (they exercise most moving parts).
3. add **Request Service** tests (deterministic + backstop).
4. finish with **Logging Stability** since it touches I/O.

---

## what you’ll get from these tests

* confidence that the **whole pipeline** (parsing → extractor calls → merging → provenance → logging) works with real state.
* guardrails on **routing decisions** (esp. NONE → backstop behavior).
* durability of **log writing** even when something fails.

If you want, I can draft the exact test case matrices for each file next (phrases → expected outcomes), so you can paste them straight into parametrized blocks.


# “Done” criteria before convo agent

1. Unit suite green.
2. Integration suite green.
3. Corpus pass-rate thresholds (e.g., ≥92% deterministic; ≥97% with LLM backstop).
4. Logs present for every turn in integration runs.
5. Manual smoke via CLI: multiphrase, correction, summaries, report draft.

# notes

Is one test enough for test_intent_classifier?

Almost. This file already acts as a contract test for the classifier’s output space and key cues, which is the most important piece. Two small additions would make it sturdier without adding much bulk:

Boundary/ambiguity cases (to prevent regressions):

Phrases that look corrective but aren’t (“change of season”) → should not flip to REQUEST_SERVICE.

Mixed sentences with both info and a cue (“dbh is 30; please draft a report”) → should be REQUEST_SERVICE.

Casing/punctuation fuzz:

Variants like TL;DR, tldr, extra whitespace—just 2–3 quick cases to lock normalization.

If you add those as a second parametrized test (e.g., test_intent_boundary_cases()), you’ll have solid coverage without bloat.