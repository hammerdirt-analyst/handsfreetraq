# tests/unit/test_corrections_agent.py
"""
Unit tests for CorrectionsAgent.

What’s covered
--------------
1) Calls the correct section extractor(s) with the scoped payload(s).
2) Applies updates with policy='last_write' and de-dups scalar provenance.
3) Handles multi-scope correction utterances (segments routed per section).
4) No-op / "Not Found" behavior when extractors yield nothing.
5) Bypasses deterministic service router (agent does not call classify_service).
6) Returns a stable contract: {ok, model, tokens:{in,out}, service, sections_updated, result}.

File dependencies
-----------------
- corrections_agent.CorrectionsAgent (SUT)
- report_context._build_context_from_testdata (to seed context)
- report_state.ReportState (for merge/provenance checks)
- The per-section extractor class *names* referenced by CorrectionsAgent.registry, but we monkeypatch them here.
"""

import copy
from types import SimpleNamespace as _NS
import pytest

import corrections_agent
# from corrections_agent import CorrectionsAgent
from report_state import ReportState, NOT_PROVIDED
from report_context import _build_context_from_testdata


# ---------- Fixtures ----------

@pytest.fixture()
def state() -> ReportState:
    # Full state with arborist/customer/location from your testdata
    return ReportState(context=_build_context_from_testdata())


@pytest.fixture()
def agent(monkeypatch) -> corrections_agent.CorrectionsAgent:
    """
    Build CorrectionsAgent with a fake registry so no real LLMs are used.
    Each fake extractor exposes .extract_dict(text, ...) -> {"result": {"updates": {...}}}
    We’ll swap return payloads per test with monkeypatch.setattr on each fake.
    """
    # Default fakes: return empty updates (i.e., no capture)
    class _FakeEx:
        def __init__(self, name): self._name = name
        def extract_dict(self, text, **kwargs): return {"result": {"updates": {}}}

    fake_registry = {
        "area_description": _FakeEx("AreaDescriptionExtractor"),
        "tree_description": _FakeEx("TreeDescriptionExtractor"),
        "targets": _FakeEx("TargetsExtractor"),
        "risks": _FakeEx("RisksExtractor"),
        "recommendations": _FakeEx("RecommendationsExtractor"),
    }

    # Ensure agent uses this registry
    monkeypatch.setattr(corrections_agent, "EXTRACTOR_REGISTRY", fake_registry, raising=False)

    # Make sure the agent doesn’t try to call a deterministic classifier underneath
    if hasattr(corrections_agent, "classify_service"):
        monkeypatch.setattr(corrections_agent, "classify_service",
                            lambda *_a, **_k: (_NS(called=True)), raising=False)

    # Stable tokens/model echo (no real counting)
    monkeypatch.setattr(corrections_agent, "_model_name", lambda: "gpt-4o-mini", raising=False)
    monkeypatch.setattr(corrections_agent, "_count_tokens",
                        lambda prompt, text=None: _NS(tokens_in=123, tokens_out=45),
                        raising=False)

    return corrections_agent.CorrectionsAgent()


# ---------- Helpers ----------

def _updates_for(section: str, payload: dict) -> dict:
    """Wrap a section payload into the agent’s standard updates envelope."""
    return {"updates": {section: payload}}


# ---------- Tests ----------

def test_calls_correct_extractor_and_updates_scalar_with_dedup(state, agent, monkeypatch):
    """
    Single-scope correction to tree_description.
    - Calls tree extractor with the scoped text
    - Applies dbh_in=30 (last_write)
    - Dedups provenance rows for the same scalar path
    """
    # Seed an earlier value + provenance by writing once
    state = state.model_merge_updates(
        _updates_for("tree_description", {"dbh_in": "28"}),
        policy="last_write", domain="tree_description",
        turn_id="t1", timestamp="ts1", extractor="Seed", model_name="gpt-4o-mini",
        segment_text="dbh 28"
    )

    # Patch extractor to return the correction
    def _fake_tree_extract(self, text, **kwargs):
        assert "dbh" in text.lower()  # sanity: we got the right payload
        return {"result": _updates_for("tree_description", {"dbh_in": "30"})}
    monkeypatch.setattr(corrections_agent.EXTRACTOR_REGISTRY["tree_description"],
                        "extract_dict", _fake_tree_extract, raising=False)

    out = agent.run(state=state, user_text="Tree Description: change DBH to 30 in")

    assert out["ok"] is True
    assert out["service"] == "MAKE_CORRECTION"
    assert "tree_description" in (out.get("sections_updated") or [])
    assert out["tokens"] == {"in": 123, "out": 45}
    assert state.tree_description.dbh_in == "30"

    # Dedup provenance: only one row for tree_description.dbh_in remains
    rows = [r for r in state.provenance
            if r.section == "tree_description" and r.path == "tree_description.dbh_in"]
    assert len(rows) == 1
    assert rows[0].value == "30"


def test_multi_scope_calls_two_extractors_and_updates_both(state, agent, monkeypatch):
    """
    Multi-scope: Tree + Risks. Both extractors called once; both sections updated.
    """
    def _tree(self, text, **_):  # set crown_shape
        return {"result": _updates_for("tree_description", {"crown_shape": "vase"})}
    def _risks(self, text, **_):  # set likelihood on first item
        return {"result": _updates_for("risks", {
            "items": [{"description": "deadwood", "likelihood": "possible", "severity": NOT_PROVIDED, "rationale": NOT_PROVIDED}]
        })}

    monkeypatch.setattr(corrections_agent.EXTRACTOR_REGISTRY["tree_description"],
                        "extract_dict", _tree, raising=False)
    monkeypatch.setattr(corrections_agent.EXTRACTOR_REGISTRY["risks"],
                        "extract_dict", _risks, raising=False)

    out = agent.run(
        state=state,
        user_text="Tree Description: change crown shape to vase; Risks: set likelihood to possible"
    )

    assert out["ok"] is True
    assert set(out.get("sections_updated") or []) >= {"tree_description", "risks"}
    assert state.tree_description.crown_shape == "vase"
    assert len(state.risks.items) == 1
    assert state.risks.items[0].likelihood == "possible"


def test_no_capture_emits_single_not_found_provenance(state, agent, monkeypatch):
    """
    If the extractor returns empty updates, the agent should:
    - not alter section values
    - still emit exactly one 'Not Found' provenance row for the segment
    """
    before = copy.deepcopy(state.model_dump(exclude_none=False))
    before_p = len(state.provenance)

    # All fakes already return empty updates (from fixture)
    out = agent.run(state=state, user_text="Tree Description: (no actual data here)")

    assert out["ok"] is True  # agent handled gracefully
    after = state.model_dump(exclude_none=False)
    # ignore provenance for structural compare
    before.pop("provenance", None)
    after.pop("provenance", None)
    assert after == before

    # One new Not Found row
    assert len(state.provenance) == before_p + 1
    row = state.provenance[-1]
    assert row.section == "tree_description"
    assert row.path == "Not Found"
    assert row.value == "Not Found"


def test_bypasses_deterministic_router(state, agent, monkeypatch):
    """
    The CorrectionsAgent should not call the deterministic service router.
    We inject a sentinel that would explode if called.
    """
    called = {"value": False}

    def _boom(*_a, **_k):
        called["value"] = True
        raise AssertionError("Deterministic router must not be called by CorrectionsAgent")

    # If present, ensure it’s not used
    if hasattr(corrections_agent, "classify_service"):
        monkeypatch.setattr(corrections_agent, "classify_service", _boom, raising=False)

    # Make a benign tree correction
    monkeypatch.setattr(
        corrections_agent.EXTRACTOR_REGISTRY["tree_description"],
        "extract_dict",
        lambda self, text, **kw: {"result": _updates_for("tree_description", {"height_ft": "60 ft"})},
        raising=False
    )
    out = agent.run(state=state, user_text="Tree Description: set height to 60 ft")

    assert out["ok"] is True
    assert called["value"] is False
    assert state.tree_description.height_ft == "60 ft"


def test_returns_contract_shape(state, agent, monkeypatch):
    """
    Ensure the agent returns the agreed response envelope.
    """
    monkeypatch.setattr(
        corrections_agent.EXTRACTOR_REGISTRY["targets"],
        "extract_dict",
        lambda self, text, **kw: {"result": _updates_for("targets", {"narratives": ["update"]})},
        raising=False
    )
    out = agent.run(state=state, user_text="Targets: add note 'update'")

    assert set(out.keys()) >= {"ok", "model", "tokens", "service", "sections_updated", "result"}
    assert out["service"] == "MAKE_CORRECTION"
    assert isinstance(out["tokens"], dict) and set(out["tokens"].keys()) == {"in", "out"}
    assert out["model"] == "gpt-4o-mini"
