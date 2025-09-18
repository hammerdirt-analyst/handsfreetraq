# tests/integrations/test_pipeline_provide_statement.py

import copy
from dataclasses import dataclass
from typing import Any, Dict

import pytest
from types import SimpleNamespace

import coordinator_agent  # system under test (Coordinator + parser, merge, etc.)
from coordinator_agent import Coordinator
from report_context import _build_context_from_testdata
from report_state import NOT_PROVIDED
import models  # to patch ModelFactory.get()


# -------------------------------
# Test doubles (registry/extractors)
# -------------------------------

@dataclass
class FakeExtractor:
    """A tiny stand-in that returns a canned dict, or calls a provided callable."""
    result_or_fn: Any

    def extract_dict(self, user_text: str, **_kw) -> Dict[str, Any]:
        if callable(self.result_or_fn):
            return self.result_or_fn(user_text)
        return self.result_or_fn


class FakeRegistry:
    """Mimics extractor_registry.default_registry() interface: .get(section) -> extractor."""
    def __init__(self, mapping: Dict[str, FakeExtractor]):
        self._m = mapping

    def get(self, section: str) -> FakeExtractor:
        return self._m[section]


# -------------------------------
# Fixtures
# -------------------------------

@pytest.fixture()
def coordinator(monkeypatch, tmp_path):
    """
    Build a Coordinator with:
      - intent_llm.classify_intent_llm → PROVIDE_STATEMENT
      - _write_log → no-op
      - COORD_LOG → tmp path
      - ModelFactory.get() → dummy (no OpenAI)
    """
    # Force intent
    monkeypatch.setattr(
        report_agent, "classify_intent_llm",
        lambda text: SimpleNamespace(intent="PROVIDE_STATEMENT")
    )

    # No-op logger + redirect file path
    monkeypatch.setattr(report_agent, "_write_log", lambda *_a, **_k: None)
    monkeypatch.setattr(coordinator, "COORD_LOG", str(tmp_path / "coordinator-tests.txt"))

    # Prevent any model calls from trying to reach OpenAI
    monkeypatch.setattr(models.ModelFactory, "get", staticmethod(lambda: (lambda *a, **k: None)))

    # Realistic minimal context
    ctx = _build_context_from_testdata()
    return Coordinator(ctx)


# -------------------------------
# Tests
# -------------------------------

def test_single_scope_captures_and_provenance(monkeypatch, coordinator):
    """
    Utterance: one explicit scope → one extractor call
    - Expect state updated (dbh_in=26)
    - Expect provenance row for that field only (no row for NOT_PROVIDED fields)
    """
    tree_desc_env = {
        "updates": {
            "tree_description": {
                "dbh_in": "26",
                "height_ft": NOT_PROVIDED,  # should NOT produce a provenance row
            }
        }
    }

    registry = FakeRegistry({
        "tree_description": FakeExtractor(tree_desc_env),
        "area_description": FakeExtractor({"updates": {"area_description": {}}}),
        "targets": FakeExtractor({"updates": {"targets": {}}}),
        "risks": FakeExtractor({"updates": {"risks": {}}}),
        "recommendations": FakeExtractor({"updates": {"recommendations": {}}}),
    })
    # IMPORTANT: assign the fake registry directly to the already-constructed coordinator
    coordinator.registry = registry

    prov_before = len(coordinator.state.provenance)
    out = coordinator.handle_turn("tree description: dbh 26 in")

    assert out["ok"] is True
    assert coordinator.state.tree_description.dbh_in == "26"
    # No provenance row for NOT_PROVIDED height_ft; exactly one row captured
    prov_after = coordinator.state.provenance
    assert len(prov_after) == prov_before + 1
    last = prov_after[-1]
    assert last.path.endswith("tree_description.dbh_in") or last.path == "tree_description.dbh_in"


def test_multi_scope_two_extractors_merge_and_provenance(monkeypatch, coordinator):
    """
    Utterance: two scopes → two extractor calls
    - tree description: height 45 ft
    - targets: walkway occupied daily
    """
    td_env = {"updates": {"tree_description": {"height_ft": "45 feet"}}}
    tg_env = {
        "updates": {
            "targets": {
                "items": [
                    {
                        "label": "walkway",
                        "occupied_frequency": "daily",
                        "damage_modes": [],
                        "proximity_note": NOT_PROVIDED,
                        "narratives": [],
                    }
                ]
            }
        }
    }

    registry = FakeRegistry({
        "tree_description": FakeExtractor(td_env),
        "targets": FakeExtractor(tg_env),
        "area_description": FakeExtractor({"updates": {"area_description": {}}}),
        "risks": FakeExtractor({"updates": {"risks": {}}}),
        "recommendations": FakeExtractor({"updates": {"recommendations": {}}}),
    })
    coordinator.registry = registry

    prov_before = len(coordinator.state.provenance)
    out = coordinator.handle_turn("tree description: height 45 ft targets: walkway occupied daily")

    assert out["ok"] is True
    assert coordinator.state.tree_description.height_ft == "45 feet"
    assert coordinator.state.targets.items and coordinator.state.targets.items[0].label == "walkway"
    assert coordinator.state.targets.items[0].occupied_frequency == "daily"

    # Two captures → at least 2 provenance rows added
    assert len(coordinator.state.provenance) >= prov_before + 2


def test_lead_in_then_scope_two_segments(monkeypatch, coordinator):
    """
    Lead-in (unscoped) text goes to current_section, then scoped segment.
    - current_section = area_description
    - lead-in := foot traffic moderate (→ area_description)
    - scope := tree description dbh 30 in
    """
    coordinator.state.current_section = "area_description"

    ad_env = {"updates": {"area_description": {"foot_traffic_level": "moderate"}}}
    td_env = {"updates": {"tree_description": {"dbh_in": "30"}}}

    registry = FakeRegistry({
        "area_description": FakeExtractor(ad_env),
        "tree_description": FakeExtractor(td_env),
        "targets": FakeExtractor({"updates": {"targets": {}}}),
        "risks": FakeExtractor({"updates": {"risks": {}}}),
        "recommendations": FakeExtractor({"updates": {"recommendations": {}}}),
    })
    coordinator.registry = registry

    prov_before = len(coordinator.state.provenance)

    out = coordinator.handle_turn("foot traffic is moderate; tree description: dbh 30 in")
    assert out["ok"] is True

    # First segment → area_description.foot_traffic
    assert coordinator.state.area_description.foot_traffic_level == "moderate"
    # Second segment → tree_description.dbh_in
    assert coordinator.state.tree_description.dbh_in == "30"

    # At least two provenance rows (one per captured field)
    assert len(coordinator.state.provenance) >= prov_before + 2


def test_navigation_only_segment_no_extractor_no_state_change(monkeypatch, coordinator):
    """
    Scope with no trailing content ⇒ navigation-only.
    - No extractor should be called
    - No semantic state change
    - No provenance row
    - Cursor (current_section/current_text) MAY update (that’s expected)
    """
    called = {"targets": 0}

    def _should_not_be_called(_text):
        called["targets"] += 1
        return {"updates": {"targets": {"items": [{"label": "playground"}]}}}

    registry = FakeRegistry({
        "targets": FakeExtractor(_should_not_be_called),
        "tree_description": FakeExtractor({"updates": {"tree_description": {}}}),
        "area_description": FakeExtractor({"updates": {"area_description": {}}}),
        "risks": FakeExtractor({"updates": {"risks": {}}}),
        "recommendations": FakeExtractor({"updates": {"recommendations": {}}}),
    })
    coordinator.registry = registry

    before_semantic = {
        "tree_description": copy.deepcopy(coordinator.state.tree_description.model_dump(exclude_none=False)),
        "area_description": copy.deepcopy(coordinator.state.area_description.model_dump(exclude_none=False)),
        "targets": copy.deepcopy(coordinator.state.targets.model_dump(exclude_none=False)),
        "risks": copy.deepcopy(coordinator.state.risks.model_dump(exclude_none=False)),
        "recommendations": copy.deepcopy(coordinator.state.recommendations.model_dump(exclude_none=False)),
    }
    prov_before = len(coordinator.state.provenance)

    out = coordinator.handle_turn("targets:")

    assert out["ok"] is True
    assert out["result"]["segments"] == [{"section": "targets", "note": "navigation_only"}]

    # Extractor not called
    assert called["targets"] == 0

    # Semantic state unchanged; provenance unchanged
    after_semantic = {
        "tree_description": coordinator.state.tree_description.model_dump(exclude_none=False),
        "area_description": coordinator.state.area_description.model_dump(exclude_none=False),
        "targets": coordinator.state.targets.model_dump(exclude_none=False),
        "risks": coordinator.state.risks.model_dump(exclude_none=False),
        "recommendations": coordinator.state.recommendations.model_dump(exclude_none=False),
    }
    assert after_semantic == before_semantic
    assert len(coordinator.state.provenance) == prov_before

    # Cursor can update — that’s expected for navigation
    assert coordinator.state.current_section == "targets"
    assert coordinator.state.current_text == "targets:"


def test_no_capture_results_in_single_not_found_provenance(monkeypatch, coordinator):
    """
    Extractor returns an empty envelope → model_merge emits one Not Found row.
    Coordinator returns ok=True with note='no_capture'.
    """
    td_env = {}  # empty → no "updates" key

    registry = FakeRegistry({
        "tree_description": FakeExtractor(td_env),
        "area_description": FakeExtractor({"updates": {"area_description": {}}}),
        "targets": FakeExtractor({"updates": {"targets": {}}}),
        "risks": FakeExtractor({"updates": {"risks": {}}}),
        "recommendations": FakeExtractor({"updates": {"recommendations": {}}}),
    })
    coordinator.registry = registry

    prov_before = len(coordinator.state.provenance)

    out = coordinator.handle_turn("tree description: [garbled]")

    assert out["ok"] is True
    assert out["result"]["note"] == "no_capture"

    # Exactly one new Not Found row
    prov_after = coordinator.state.provenance
    assert len(prov_after) == prov_before + 1
    assert prov_after[-1].path == "Not Found"
    assert prov_after[-1].value == "Not Found"
