# tests/unit/test_request_service_backstop.py
"""
Backstop routing unit tests.

Goal
----
When the deterministic router returns ("NONE", None), Coordinator must call
the LLM backstop (service_classifier.ServiceRouterClassifier) and handle:
- High confidence → route to predicted service/section (no state side-effects in this test)
- Low confidence  → CLARIFY, section=None
- Exception       → ok=False with 'service routing error'

We patch the *actual callsites* used by Coordinator.
"""

from types import SimpleNamespace as _NS
import pytest

import coordinator_agent
import report_context
from coordinator_agent import Coordinator

# Callsite modules
import service_router
import service_classifier



# ---------------- Fixtures ----------------

@pytest.fixture
def coordinator():
    """Build a Coordinator with valid test context."""
    ctx = report_context._build_context_from_testdata()
    return Coordinator(ctx)


# --------------- Patch helpers ------------

def _force_request_service_intent(monkeypatch):
    """Force intent to REQUEST_SERVICE."""
    stub = lambda text: _NS(intent="REQUEST_SERVICE")
    monkeypatch.setattr(coordinator_agent, "classify_intent_llm", stub, raising=False)

def _force_deterministic_none(monkeypatch):
    """Force deterministic router → NONE (both callsite and coordinator module)."""
    stub = lambda text: ("NONE", None)
    monkeypatch.setattr(service_router, "classify_service", stub, raising=False)
    monkeypatch.setattr(coordinator_agent, "classify_service", stub, raising=False)

def _patch_llm_backstop(monkeypatch, *, service, section, confidence):
    """
    Patch ServiceRouterClassifier.get().classify(...) to return an object with
    .service, .section, .confidence (attributes).
    """
    class _FakeLLM:
        def __init__(self, svc, sec, conf):
            self.service = svc
            self.section = sec
            self.confidence = conf
        def classify(self, text):
            return self

    class _FakeSRC:
        @classmethod
        def get(cls):
            return _FakeLLM(service, section, confidence)

    monkeypatch.setattr(service_classifier, "ServiceRouterClassifier", _FakeSRC, raising=False)
    monkeypatch.setattr(coordinator_agent, "ServiceRouterClassifier", _FakeSRC, raising=False)


# ---------------- Tests -------------------

def test_llm_backstop_high_confidence_routes_service(monkeypatch, coordinator):
    """
    Deterministic → NONE, backstop high confidence → route to predicted service.

    Use QUICK_SUMMARY to avoid state mutations in unit scope.
    """
    _force_request_service_intent(monkeypatch)
    _force_deterministic_none(monkeypatch)
    _patch_llm_backstop(
        monkeypatch,
        service="QUICK_SUMMARY",   # ← avoids SectionSummary state updates
        section=None,
        confidence=0.92,
    )
    from report_state import SectionSummaryInputs

    def _fake_inputs(self, section, user_text):
        # minimal, valid payload expected by set_section_summary provenance
        return SectionSummaryInputs.make(
            section=section, section_state={}, reference_text=user_text, provided_paths=[]
        )

    monkeypatch.setattr(coordinator_agent.Coordinator, "_summary_inputs_for", _fake_inputs, raising=False)

    out = coordinator.handle_turn("please give me a quick summary")
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is True
    assert out["result"]["service"] == "QUICK_SUMMARY"
    assert out["result"]["section"] is None


def test_llm_backstop_low_confidence_clarify(monkeypatch, coordinator):
    """
    Deterministic → NONE, backstop low confidence → CLARIFY, section=None.
    """
    _force_request_service_intent(monkeypatch)
    _force_deterministic_none(monkeypatch)
    _patch_llm_backstop(
        monkeypatch,
        service="SECTION_SUMMARY",
        section=None,
        confidence=0.30,
    )
    from report_state import SectionSummaryInputs

    def _fake_inputs(self, section, user_text):
        # minimal, valid payload expected by set_section_summary provenance
        return SectionSummaryInputs.make(
            section=section, section_state={}, reference_text=user_text, provided_paths=[]
        )

    monkeypatch.setattr(coordinator_agent.Coordinator, "_summary_inputs_for", _fake_inputs, raising=False)

    out = coordinator.handle_turn("summary please")
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is True
    assert out["result"]["service"] == "CLARIFY"
    assert out["result"]["section"] is None
    # note text is implementation-defined; don't overfit assertions here.


def test_llm_backstop_exception_is_caught(monkeypatch, coordinator):
    """
    Deterministic → NONE, backstop raises → ok=False with service routing error.
    """
    _force_request_service_intent(monkeypatch)
    _force_deterministic_none(monkeypatch)

    class _BoomSRC:
        @classmethod
        def get(cls):
            raise RuntimeError("classifier exploded")

    monkeypatch.setattr(service_classifier, "ServiceRouterClassifier", _BoomSRC, raising=False)
    monkeypatch.setattr(coordinator_agent, "ServiceRouterClassifier", _BoomSRC, raising=False)

    out = coordinator.handle_turn("please give me a targets summary")
    assert out["intent"] == "REQUEST_SERVICE"
    assert out["ok"] is False
    assert "service routing error" in (out.get("error") or "").lower()
