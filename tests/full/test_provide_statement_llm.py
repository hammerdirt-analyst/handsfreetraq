# tests/full/test_provide_statement_llm.py
import os
import re
import copy
from typing import List, Dict, Any

import pytest
from dotenv import load_dotenv

import coordinator_agent
from coordinator_agent import Coordinator
from report_context import _build_context_from_testdata
from report_state import NOT_PROVIDED

# Ensure env is loaded so real models can run if needed
load_dotenv()

# -------------------------------------------------------------------
# Force logs to the standard repo location for this *full* test suite
# -------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
LOG_DIR = os.path.join(PROJECT_ROOT, "coordinator_logs")
os.makedirs(LOG_DIR, exist_ok=True)
# Set the path on the imported module before Coordinator is constructed
coordinator_agent.COORD_LOG = os.path.join(LOG_DIR, "coordinator-tests.txt")
# Do NOT stub _write_log; let it write for real.

# -----------------------------
# Live test cases (inputs only)
# -----------------------------
BASIC_SINGLE_SCOPE_CASES = [
    "tree description: dbh 26 in",
    "tree description: height 45 ft",
    "tree description: defects include deadwood",
]

MULTI_SCOPE_CASE = "tree description: height 45 ft targets: walkway occupied daily"

LEAD_IN_THEN_SCOPED = "foot traffic is moderate; tree description: dbh 30 in"

NAV_ONLY_CASE = "targets:"

NO_CAPTURE_CASE = "tree description: [garbled]"

LIST_APPEND_TURN_A = "tree description: defects include deadwood"
LIST_APPEND_TURN_B = "tree description: defects include crack"

TARGETS_TURN_A = "targets: playground occupied daily"
TARGETS_TURN_B = "targets: parking lot occupied weekly"

PREFER_EXISTING_REDACTION = "tree description: height unknown"

PARTIAL_ENVELOPE_CASE = "tree description: looks okay overall"

NOISY_NUMBER_CASE = "tree description: DBH around ~ 28 inches; maybe check later"

THREE_SCOPE_CASE = "tree description: dbh 24 in targets: walkway occupied daily risks: moderate likelihood"


# -----------------------------
# Helpers
# -----------------------------
def _prov_rows(state) -> List[Dict[str, Any]]:
    return [e.model_dump(exclude_none=False) for e in state.provenance]

def _prov_contains_not_found_for_section(state, section: str) -> bool:
    for r in _prov_rows(state):
        if r.get("section") == section and r.get("path") == "Not Found" and r.get("value") == "Not Found":
            return True
    return False

def _prov_has_path_prefix(state, section: str, path_prefix: str) -> bool:
    for r in _prov_rows(state):
        if r.get("section") == section and isinstance(r.get("path"), str) and r["path"].startswith(path_prefix):
            if r.get("value") not in (None, "", NOT_PROVIDED, "Not Found"):
                return True
    return False

def _targets_last_item(state):
    items = state.targets.items or []
    return items[-1] if items else None


# -----------------------------
# Fixtures
# -----------------------------
@pytest.fixture()
def coordinator():
    """
    Real coordinator & real registry/intent (no mocks).
    Logs go to project_root/coordinator_logs/coordinator-tests.txt (set above).
    """
    ctx = _build_context_from_testdata()
    return Coordinator(ctx)


# -----------------------------
# Tests
# -----------------------------
@pytest.mark.parametrize("utterance", BASIC_SINGLE_SCOPE_CASES)
def test_basic_single_scope_captures(coordinator, utterance):
    prov_before = len(_prov_rows(coordinator.state))
    out = coordinator.handle_turn(utterance)

    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["ok"] is True
    assert out["result"]["note"] == "captured"

    # Light, robust checks:
    if "dbh" in utterance.lower():
        # expect dbh_in captured to include 26ish digits
        val = coordinator.state.tree_description.dbh_in
        assert re.search(r"\b26\b", str(val))
        assert _prov_has_path_prefix(coordinator.state, "tree_description", "tree_description.dbh_in")

    if "height" in utterance.lower():
        val = coordinator.state.tree_description.height_ft
        assert re.search(r"\b45\b", str(val))
        assert _prov_has_path_prefix(coordinator.state, "tree_description", "tree_description.height_ft")

    if "defects" in utterance.lower():
        defects = coordinator.state.tree_description.defects
        # list grew and contains something truthy
        assert isinstance(defects, list) and len(defects) >= 1
        assert _prov_has_path_prefix(coordinator.state, "tree_description", "tree_description.defects")

    # provenance grew at least by 1 for the applied field(s)
    assert len(_prov_rows(coordinator.state)) >= prov_before + 1


def test_multi_scope_two_sections_merge(coordinator):
    prov_before = len(_prov_rows(coordinator.state))
    out = coordinator.handle_turn(MULTI_SCOPE_CASE)

    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["ok"] is True
    assert out["result"]["note"] == "captured"
    assert isinstance(out["result"]["segments"], list) and len(out["result"]["segments"]) == 2

    # tree_description height captured
    assert re.search(r"\b45\b", str(coordinator.state.tree_description.height_ft))
    assert _prov_has_path_prefix(coordinator.state, "tree_description", "tree_description.height_ft")

    # targets item appended
    last = _targets_last_item(coordinator.state)
    assert last is not None
    assert "walkway" in last.label.lower()
    assert "daily" in last.occupied_frequency.lower()
    assert _prov_has_path_prefix(coordinator.state, "targets", "targets.items")

    assert len(_prov_rows(coordinator.state)) >= prov_before + 2


def test_lead_in_then_scoped_two_segments(coordinator):
    # Start in area_description so the lead-in text routes there
    coordinator.state.current_section = "area_description"
    prov_before = len(_prov_rows(coordinator.state))

    out = coordinator.handle_turn(LEAD_IN_THEN_SCOPED)

    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["ok"] is True
    assert out["result"]["note"] == "captured"

    # Lead-in → area_description: check foot traffic level was set
    ftl = getattr(coordinator.state.area_description, "foot_traffic_level", "")
    assert isinstance(ftl, str) and ftl != "" and ftl != NOT_PROVIDED
    assert _prov_has_path_prefix(coordinator.state, "area_description", "area_description.foot_traffic_level")

    # Scoped → tree_description.dbh_in ~ 30
    assert re.search(r"\b30\b", str(coordinator.state.tree_description.dbh_in))
    assert _prov_has_path_prefix(coordinator.state, "tree_description", "tree_description.dbh_in")

    assert len(_prov_rows(coordinator.state)) >= prov_before + 2


def test_navigation_only_segment(coordinator):
    before = copy.deepcopy(coordinator.state.model_dump(exclude_none=False))
    prov_before = len(_prov_rows(coordinator.state))

    out = coordinator.handle_turn(NAV_ONLY_CASE)

    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["ok"] is True
    assert out["result"]["segments"] == [{"section": "targets", "note": "navigation_only"}]

    # Only cursor and current_text should change; no provenance rows
    after = coordinator.state.model_dump(exclude_none=False)
    assert after["current_section"] == "targets"
    before["current_section"] = "targets"
    # coordinator records the utterance into current_text — account for that
    before["current_text"] = NAV_ONLY_CASE
    assert after == before

    assert len(_prov_rows(coordinator.state)) == prov_before  # no new rows


def test_no_capture_emits_single_not_found_prov(coordinator):
    prov_before = len(_prov_rows(coordinator.state))

    out = coordinator.handle_turn(NO_CAPTURE_CASE)

    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["ok"] is True
    assert out["result"]["note"] == "no_capture"

    # Exactly one Not Found row for tree_description
    prov_after = _prov_rows(coordinator.state)
    assert len(prov_after) == prov_before + 1
    assert _prov_contains_not_found_for_section(coordinator.state, "tree_description")


def test_list_append_across_turns(coordinator):
    # Turn A
    out_a = coordinator.handle_turn(LIST_APPEND_TURN_A)
    assert out_a["ok"] is True

    len_a = len(coordinator.state.tree_description.defects or [])

    # Turn B
    out_b = coordinator.handle_turn(LIST_APPEND_TURN_B)
    assert out_b["ok"] is True

    defects = coordinator.state.tree_description.defects or []
    assert len(defects) >= len_a + 1


def test_targets_two_items_across_turns(coordinator):
    # Turn A
    out_a = coordinator.handle_turn(TARGETS_TURN_A)
    assert out_a["ok"] is True
    n_a = len(coordinator.state.targets.items or [])

    # Turn B
    out_b = coordinator.handle_turn(TARGETS_TURN_B)
    assert out_b["ok"] is True
    n_b = len(coordinator.state.targets.items or [])

    assert n_b >= n_a + 1
    last = _targets_last_item(coordinator.state)
    assert last is not None
    assert "parking" in last.label.lower()
    assert "weekly" in last.occupied_frequency.lower()


def test_prefer_existing_blocks_redaction(coordinator):
    # Seed an existing provided value
    coordinator.state.tree_description.height_ft = "45 feet"
    prov_before = len(_prov_rows(coordinator.state))

    out = coordinator.handle_turn(PREFER_EXISTING_REDACTION)
    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["ok"] is True

    # Prefer-existing should keep 45 feet
    assert coordinator.state.tree_description.height_ft == "45 feet"

    # If extractor tried to redact/not-provide, merge should avoid field-row;
    # if nothing captured at all, coordinator will add a single Not Found row.
    prov_after = _prov_rows(coordinator.state)
    assert len(prov_after) in (prov_before, prov_before + 1)


def test_partial_envelope_no_capture(coordinator):
    prov_before = len(_prov_rows(coordinator.state))
    out = coordinator.handle_turn(PARTIAL_ENVELOPE_CASE)

    assert out["intent"] == "PROVIDE_STATEMENT"
    # Many extractors will produce no structured capture here
    assert out["result"]["note"] in ("no_capture", "captured")
    # If no_capture → expect one Not Found row appended
    if out["result"]["note"] == "no_capture":
        assert len(_prov_rows(coordinator.state)) == prov_before + 1
        assert _prov_contains_not_found_for_section(coordinator.state, "tree_description")


def test_noisy_number_dbh_still_captured(coordinator):
    prov_before = len(_prov_rows(coordinator.state))
    out = coordinator.handle_turn(NOISY_NUMBER_CASE)

    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["ok"] is True
    assert "note" in out["result"]

    # Expect dbh around 28 extracted despite noise
    assert re.search(r"\b28\b", str(coordinator.state.tree_description.dbh_in))
    assert _prov_has_path_prefix(coordinator.state, "tree_description", "tree_description.dbh_in")
    assert len(_prov_rows(coordinator.state)) >= prov_before + 1


def test_three_scopes_in_one_turn(coordinator):
    prov_before = len(_prov_rows(coordinator.state))
    out = coordinator.handle_turn(THREE_SCOPE_CASE)

    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["ok"] is True
    assert isinstance(out["result"].get("segments"), list)
    assert len(out["result"]["segments"]) == 3

    # tree_description dbh captured
    assert re.search(r"\b24\b", str(coordinator.state.tree_description.dbh_in))

    # targets appended
    last = _targets_last_item(coordinator.state)
    assert last is not None and "walkway" in last.label.lower()

    # For risks, allow either a captured field OR an explicit "no_capture" segment
    segs = out["result"]["segments"]
    risks_seg = next((s for s in segs if s.get("section") == "risks"), None)
    assert risks_seg is not None

    if risks_seg.get("note") == "captured":
        risks_dict = coordinator.state.risks.model_dump(exclude_none=False)
        has_nonempty_field = any(isinstance(v, str) and v not in ("", NOT_PROVIDED) for v in risks_dict.values())

        # provenance check as a fallback proof of movement on risks.*
        prov_rows = [e.model_dump(exclude_none=False) for e in coordinator.state.provenance]
        has_risks_prov = any(
            (row.get("section") == "risks") and
            isinstance(row.get("path"), str) and
            row["path"].startswith("risks.")
            for row in prov_rows
        )

        assert has_nonempty_field or has_risks_prov, "Expected either a non-empty risks field or a risks.* provenance row"
    else:
        # explicit no_capture is acceptable
        assert risks_seg.get("note") == "no_capture"

