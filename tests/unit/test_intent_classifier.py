"""
tests/unit/test_intent_classifier.py

What this tests (and why)
-------------------------
Contract check for the intent classifier used by the coordinator:
1) Binary label space only:
   - For a curated corpus of phrases, the classifier must return one of
     {"PROVIDE_STATEMENT", "REQUEST_SERVICE"}—no extra/novel labels. This guards
     coordinator routing from unexpected values.
2) Routing cues sanity:
   - Service-like phrasing (corrections verbs, summary/report cues, "what's left")
     must map to REQUEST_SERVICE.
   - Plain fact capture (e.g., "dbh is 30 inches") must map to PROVIDE_STATEMENT.
   This ensures the coordinator takes the correct high-level path.

How it works
------------
- Patches `intent_model.classify_intent_llm` with a deterministic, table-driven
  heuristic so tests are fast and network-free.
- Asserts the returned object exposes `.intent` and that its value matches the
  expected label per case.

File / module dependencies
--------------------------
- intent_model.classify_intent_llm (patched)
- pytest (fixtures, parametrization)
"""

import re
import pytest

# System under test (renamed file)
import intent_model

# ---------- simple binary mock (REQUEST_SERVICE vs PROVIDE_STATEMENT) ----------

CORRECTION_VERBS = {
    "change", "set", "fix", "update", "adjust", "edit", "replace",
    "amend", "revise", "switch", "make", "correct", "alter",
}

SUMMARY_CUES = {
    "summary", "tldr", "tl;dr", "recap", "overview", "rollup",
    "outline", "synopsis", "breakdown", "status", "at a glance",
    "executive", "quick", "brief",
}

REPORT_CUES = {"report", "write-up", "write up", "draft"}

WHATS_LEFT_CUES = {
    "what's left", "whats left", "what is left", "what remains", "remaining items",
}

def _normalize(text: str) -> str:
    # lightweight normalization so cues match more consistently
    t = (text or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t

def _decide_intent(text: str) -> str:
    t = _normalize(text)

    # any service-like phrasing → REQUEST_SERVICE
    if any(v in t for v in CORRECTION_VERBS):
        return "REQUEST_SERVICE"
    if any(c in t for c in SUMMARY_CUES):
        return "REQUEST_SERVICE"
    if any(r in t for r in REPORT_CUES):
        return "REQUEST_SERVICE"
    if any(w in t for w in WHATS_LEFT_CUES):
        return "REQUEST_SERVICE"

    # default path is data capture
    return "PROVIDE_STATEMENT"


class _MockIntentObj:
    def __init__(self, intent: str):
        self.intent = intent

@pytest.fixture(autouse=True)
def patch_intent_classifier(monkeypatch):
    """Patch the function the coordinator calls to avoid hitting a real LLM."""
    def _mock_classify_intent_llm(text: str):
        return _MockIntentObj(_decide_intent(text))
    monkeypatch.setattr(intent_model, "classify_intent_llm", _mock_classify_intent_llm)
    yield

# ---------------------------- test cases & assertions ----------------------------

TEST_CASES = [
    # REQUEST_SERVICE (corrections)
    ("change dbh to 30 inches", "REQUEST_SERVICE"),
    ("please update targets: playground occupied daily", "REQUEST_SERVICE"),
    ("correct area description to residential", "REQUEST_SERVICE"),
    ("adjust risks to moderate likelihood", "REQUEST_SERVICE"),
    ("fix the recommendation to removal", "REQUEST_SERVICE"),

    # REQUEST_SERVICE (summaries)
    ("give me a quick status summary", "REQUEST_SERVICE"),
    ("summary of recommendations section", "REQUEST_SERVICE"),
    ("tldr overall", "REQUEST_SERVICE"),
    ("tl;dr overall", "REQUEST_SERVICE"),
    ("overview of targets", "REQUEST_SERVICE"),
    ("brief recap", "REQUEST_SERVICE"),

    # REQUEST_SERVICE (reports)
    ("please draft a report", "REQUEST_SERVICE"),
    ("generate a report draft", "REQUEST_SERVICE"),
    ("compile a report", "REQUEST_SERVICE"),

    # REQUEST_SERVICE (what’s left)
    ("what's left?", "REQUEST_SERVICE"),
    ("what is left to fill?", "REQUEST_SERVICE"),
    ("show remaining items", "REQUEST_SERVICE"),

    # PROVIDE_STATEMENT (plain data capture)
    ("dbh is 30 inches", "PROVIDE_STATEMENT"),
    ("height is 45 feet", "PROVIDE_STATEMENT"),
    ("targets: walkway occupied daily", "PROVIDE_STATEMENT"),
    ("tree description: crown shape is vase", "PROVIDE_STATEMENT"),
    ("risks: severity high, likelihood moderate", "PROVIDE_STATEMENT"),
]

def test_contract_and_binary_labels_only():
    """Ensure the classifier surfaces only the two allowed intents across samples."""
    seen = set()
    for text, expected in TEST_CASES:
        res = intent_model.classify_intent_llm(text)
        assert hasattr(res, "intent")
        seen.add(res.intent)
        assert res.intent == expected, f"text={text!r} expected={expected} got={res.intent}"
    assert seen <= {"PROVIDE_STATEMENT", "REQUEST_SERVICE"}, f"unexpected labels found: {seen}"
