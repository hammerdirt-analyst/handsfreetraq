# tests/full/test_request_services_llm.py
from __future__ import annotations
import os
import copy
import pytest
from dotenv import load_dotenv

import coordinator_agent
from coordinator_agent import Coordinator
from report_context import _build_context_from_testdata

# Ensure env is loaded so real models can run if needed
load_dotenv()

# -------------------------------------------------------------------
# Force logs to the standard repo location (identical to provide_statement)
# -------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
LOG_DIR = os.path.join(PROJECT_ROOT, "coordinator_logs")
os.makedirs(LOG_DIR, exist_ok=True)
report_agent.COORD_LOG = os.path.join(LOG_DIR, "coordinator-tests.txt")
# Do NOT stub _write_log; let it write for real.

# -----------------------------
# Live phrases (inputs only)
# -----------------------------
DET_HIT_CASES = [
    ("summary of the recommendations section", "SECTION_SUMMARY", "recommendations"),
    ("overview of targets section", "SECTION_SUMMARY", "targets"),
    ("make a full report draft", "MAKE_REPORT_DRAFT", None),
]

LLM_CONFIDENT_CASES = [
    ("give me the overall TL;DR", "QUICK_SUMMARY", None),
    ("fast brief of what we have so far", "QUICK_SUMMARY", None),
]

AMBIGUOUS_FOR_CLARIFY = "summarize"


# -----------------------------
# Fixtures
# -----------------------------
@pytest.fixture()
def coordinator():
    ctx = _build_context_from_testdata()
    return Coordinator(ctx)


# -----------------------------
# Helpers
# -----------------------------
def _assert_service_envelope(out, *, exp_service, exp_section):
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is True
    assert out["routed_to"] in (
        "RequestService",
        "RequestService → deterministic → llm_backstop",
    )
    assert isinstance(out["result"], dict)
    assert out["result"].get("service") == exp_service
    assert out["result"].get("section") == exp_section

def _assert_state_unchanged_except_current_text(before, after, utterance):
    # Coordinator writes the utterance into state.current_text on every turn.
    before = copy.deepcopy(before)
    before["current_text"] = utterance
    assert after == before

def _patch_llm_backstop(monkeypatch, *, service, section, confidence):
    """
    Add a .get() to ServiceRouterClassifier and return a fake classifier
    with the requested response. Use raising=False because .get doesn't exist.
    """
    class _Obj:
        def __init__(self, s, sec, conf):
            self.service = s
            self.section = sec
            self.confidence = conf

    class FakeClassifier:
        def classify(self, _text):
            return _Obj(service, section, confidence)

    monkeypatch.setattr(
        coordinator.ServiceRouterClassifier,
        "get",
        classmethod(lambda cls: FakeClassifier()),
        raising=False,
    )


# -----------------------------
# Tests
# -----------------------------
@pytest.mark.parametrize("utterance,exp_service,exp_section", DET_HIT_CASES)
def test_deterministic_hits_without_llm(coordinator, utterance, exp_service, exp_section):
    """
    Deterministic classifier should route directly.
    Verify final envelope and that only current_text changes.
    """
    before = copy.deepcopy(coordinator.state.model_dump(exclude_none=False))
    out = coordinator.handle_turn(utterance)
    _assert_service_envelope(out, exp_service=exp_service, exp_section=exp_section)
    after = coordinator.state.model_dump(exclude_none=False)
    _assert_state_unchanged_except_current_text(before, after, utterance)


@pytest.mark.parametrize("utterance,exp_service,exp_section", LLM_CONFIDENT_CASES)
def test_llm_backstop_confident_decision(coordinator, monkeypatch, utterance, exp_service, exp_section):
    """
    Force deterministic to NONE and make LLM backstop confident.
    If deterministic already routes, assertions still pass.
    """
    # Ensure we exercise the backstop path for this test
    monkeypatch.setattr(coordinator, "classify_service", lambda _t: ("NONE", None))
    _patch_llm_backstop(monkeypatch, service=exp_service, section=exp_section, confidence=0.91)

    before = copy.deepcopy(coordinator.state.model_dump(exclude_none=False))
    out = coordinator.handle_turn(utterance)
    _assert_service_envelope(out, exp_service=exp_service, exp_section=exp_section)
    after = coordinator.state.model_dump(exclude_none=False)
    _assert_state_unchanged_except_current_text(before, after, utterance)


def test_llm_backstop_low_confidence_yields_clarify(coordinator, monkeypatch):
    """
    Deterministic → NONE; LLM backstop → low confidence → CLARIFY envelope.
    """
    monkeypatch.setattr(coordinator, "classify_service", lambda _t: ("NONE", None))

    _patch_llm_backstop(monkeypatch, service="SECTION_SUMMARY", section=None, confidence=0.30)

    out = coordinator.handle_turn(AMBIGUOUS_FOR_CLARIFY)

    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is True
    assert out["routed_to"] == "RequestService → deterministic → llm_backstop"
    result = out["result"]
    assert isinstance(result, dict)
    assert result.get("service") == "CLARIFY"
    assert result.get("section") is None
    note = (result.get("note") or "").lower()
    assert "rephrase" in note or "unclear" in note
