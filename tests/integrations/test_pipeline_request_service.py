# tests/integrations/test_pipeline_request_service.py

import pytest
from types import SimpleNamespace

import coordinator_agent  # system under test (Coordinator + routing path)
from coordinator_agent import Coordinator
from report_context import _build_context_from_testdata


# ---------- Fixtures ----------

@pytest.fixture()
def coordinator(monkeypatch, tmp_path):
    """
    Build a Coordinator wired for REQUEST_SERVICE tests:
      - intent_llm.classify_intent_llm → always REQUEST_SERVICE
      - _write_log → no-op (no file writes)
    """
    # Force the intent to REQUEST_SERVICE so we go down the service path
    monkeypatch.setattr(
        report_agent, "classify_intent_llm",
        lambda text: SimpleNamespace(intent="REQUEST_SERVICE")
    )

    # No-op logger + safe log path
    monkeypatch.setattr(coordinator, "_write_log", lambda *_a, **_k: None)
    monkeypatch.setattr(report_agent, "COORD_LOG", str(tmp_path / "coordinator-tests.txt"))

    # Build a minimal, valid context
    ctx = _build_context_from_testdata()
    return Coordinator(ctx)


# ---------- Helpers to patch the LLM backstop ----------

class _Obj(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


def _patch_llm_backstop(monkeypatch, *, service=None, section=None, confidence=0.0, raises: Exception | None = None):
    """
    Swap out the entire ServiceRouterClassifier symbol that the Coordinator uses with a fake
    that exposes a classmethod .get() returning an object with .classify(text).
    """
    class FakeClassifier:
        def classify(self, _text):
            if raises:
                raise raises
            return _Obj(service=service, section=section, confidence=confidence)

    class FakeSRClass:
        @classmethod
        def get(cls):
            return FakeClassifier()

    # Replace the class symbol inside report_agent
    monkeypatch.setattr(report_agent, "ServiceRouterClassifier", FakeSRClass)


def _patch_llm_backstop_counter(monkeypatch, counter_dict):
    """
    Like above, but increments counter_dict["llm"] if .get() is called (so we can assert it wasn't).
    """
    class FakeClassifier:
        def classify(self, _text):
            counter_dict["llm"] += 1
            # Should never be used in the 'deterministic hit' test; raise if it is:
            raise AssertionError("LLM backstop should not be called on deterministic hit")

    class FakeSRClass:
        @classmethod
        def get(cls):
            counter_dict["llm"] += 1
            return FakeClassifier()

    monkeypatch.setattr(report_agent, "ServiceRouterClassifier", FakeSRClass)

# --- and in your first test, use the counter version ---

def test_deterministic_hit_no_backstop(monkeypatch, coordinator):
    """
    Deterministic router returns a definite decision → we should NOT call the LLM backstop.
    """
    called = {"llm": 0}
    _patch_llm_backstop_counter(monkeypatch, called)

    # Deterministic classify returns direct SECTION_SUMMARY for targets
    monkeypatch.setattr(
        report_agent, "classify_service",
        lambda text: ("SECTION_SUMMARY", "targets")
    )

    out = coordinator.handle_turn("targets section summary")
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["routed_to"].startswith("RequestService")
    assert out["ok"] is True
    assert out["result"] == {
        "service": "SECTION_SUMMARY",
        "section": "targets",
        "utterance": "targets section summary",
    }
    # Ensure backstop never invoked
    assert called["llm"] == 0

def test_deterministic_none_llm_high_confidence(monkeypatch, coordinator):
    """
    Deterministic returns NONE → LLM backstop provides a confident decision.
    """
    # Deterministic → NONE
    monkeypatch.setattr(report_agent, "classify_service", lambda text: ("NONE", None))


    # LLM backstop → confident SECTION_SUMMARY/risks
    _patch_llm_backstop(monkeypatch, service="SECTION_SUMMARY", section="risks", confidence=0.91)

    out = coordinator.handle_turn("please summarize the risks section")
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is True
    assert out["result"] == {
        "service": "SECTION_SUMMARY",
        "section": "risks",
        "utterance": "please summarize the risks section",
    }


def test_deterministic_none_llm_low_confidence_clarify(monkeypatch, coordinator):
    """
    Deterministic returns NONE → LLM backstop returns low confidence → coordinator asks to clarify.
    """
    monkeypatch.setattr(report_agent, "classify_service", lambda text: ("NONE", None))
    _patch_llm_backstop(monkeypatch, service="SECTION_SUMMARY", section=None, confidence=0.30)

    out = coordinator.handle_turn("summary?")
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is True
    assert out["result"]["service"] == "CLARIFY"
    assert out["result"]["section"] is None
    assert "unclear" in out["result"]["note"].lower()


def test_make_report_draft_deterministic(monkeypatch, coordinator):
    """
    Deterministic path for report draft (no backstop).
    """
    monkeypatch.setattr(report_agent, "classify_service", lambda text: ("MAKE_REPORT_DRAFT", None))

    out = coordinator.handle_turn("please draft a report")
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is True
    assert out["result"] == {
        "service": "MAKE_REPORT_DRAFT",
        "section": None,
        "utterance": "please draft a report",
    }


def test_make_correction_with_section(monkeypatch, coordinator):
    """
    Deterministic correction with explicit section.
    """
    monkeypatch.setattr(
        report_agent, "classify_service",
        lambda text: ("MAKE_CORRECTION", "tree_description")
    )

    out = coordinator.handle_turn("change dbh to 28 inches")
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is True
    assert out["result"] == {
        "service": "MAKE_CORRECTION",
        "section": "tree_description",
        "utterance": "change dbh to 28 inches",
    }
