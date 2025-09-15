# tests/integrations/test_logging_stability.py
import os
import io
from types import SimpleNamespace

import pytest

import coordinator_agent
from coordinator_agent import Coordinator
from report_context import _build_context_from_testdata


# ---- tiny fakes (reuse pattern from other integration tests) ----

class FakeExtractor:
    """Extractor stub that returns a canned envelope OR calls a function with the payload."""
    def __init__(self, return_value):
        self.return_value = return_value

    def extract_dict(self, user_text: str, **_):
        if callable(self.return_value):
            return self.return_value(user_text)
        return self.return_value


class FakeRegistry(dict):
    def get(self, section):
        return super().__getitem__(section)


@pytest.fixture()
def coordinator(monkeypatch, tmp_path):
    """
    Coordinator with:
      - COORD_LOG redirected into tmp dir (we do NOT stub _write_log — we want real writes)
      - default_registry → fakes (so no model calls)
      - classify_intent_llm → simple router: if 'summary' in text → REQUEST_SERVICE, else PROVIDE_STATEMENT
      - classify_service → deterministic SECTION_SUMMARY/targets (so no LLM backstop)
    """
    # Redirect the logfile path
    log_path = tmp_path / "coordinator-tests.txt"
    monkeypatch.setattr(coordinator, "COORD_LOG", str(log_path))

    # Real logger, but make sure directory exists (Coordinator will also mkdir)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Simple intent switch
    def _intent_switch(text: str):
        intent = "REQUEST_SERVICE" if ("summary" in (text or "").lower()) else "PROVIDE_STATEMENT"
        return SimpleNamespace(intent=intent)

    monkeypatch.setattr(coordinator, "classify_intent_llm", _intent_switch)

    # Deterministic service router
    monkeypatch.setattr(coordinator, "classify_service", lambda _t: ("SECTION_SUMMARY", "targets"))

    # Faked extractors for sections (so Provide Statement path can run without models)
    registry = FakeRegistry({
        "tree_description": FakeExtractor({"updates": {"tree_description": {"dbh_in": "24"}}}),
        "area_description": FakeExtractor({"updates": {"area_description": {"foot_traffic_level": "moderate"}}}),
        "targets": FakeExtractor({"updates": {"targets": {"items": [{"label": "walkway", "occupied_frequency": "daily"}]}}}),
        "risks": FakeExtractor({"updates": {"risks": {}}}),
        "recommendations": FakeExtractor({"updates": {"recommendations": {}}}),
    })
    monkeypatch.setattr(coordinator, "default_registry", lambda: registry)

    # Build a normal context
    ctx = _build_context_from_testdata()
    c = Coordinator(ctx)

    # Sanity: logfile should be created (CONTEXT_LOADED write)
    assert os.path.exists(str(log_path)), "Log file wasn't created on Coordinator init"
    return c


def _read(path) -> str:
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_logfile_grows_and_contains_blocks(monkeypatch, coordinator):
    """
    - After init, file contains CONTEXT_LOADED block
    - After a Provide Statement turn, file grows and contains a TURN block with the utterance
    - After a Request Service turn, file grows again and contains another TURN block with the utterance
    """
    log_path = coordinator.COORD_LOG

    # Snapshot after init
    initial = _read(log_path)
    assert "CONTEXT_LOADED" in initial
    assert initial.count("TURN") == 0  # no turns yet

    # 1) Provide Statement turn (no 'summary' keyword)
    size_before = os.path.getsize(log_path)
    utter1 = "tree description: dbh 24 in"
    out1 = coordinator.handle_turn(utter1)
    assert out1["intent"] == "PROVIDE_STATEMENT"
    assert out1["ok"] is True

    after1 = _read(log_path)
    assert os.path.getsize(log_path) > size_before
    assert after1.count("TURN") >= 1
    assert utter1 in after1  # the utterance gets logged in the payload JSON

    # 2) Request Service turn (contains 'summary' → REQUEST_SERVICE)
    size_before_2 = os.path.getsize(log_path)
    utter2 = "targets section summary"
    out2 = coordinator.handle_turn(utter2)
    assert out2["intent"] == "REQUEST_SERVICE"
    assert out2["ok"] is True

    after2 = _read(log_path)
    assert os.path.getsize(log_path) > size_before_2
    # ensure a second TURN block was appended
    assert after2.count("TURN") >= 2
    assert utter2 in after2

    # Light structure check: headers and separators present
    # (Exactly formatting may evolve; we only sanity-check)
    assert "============================================================" in after2
    assert "------------------------------------------------------------" in after2


def test_logging_does_not_crash_on_multiple_turns(monkeypatch, coordinator):
    """
    Fire several turns back-to-back and assert the coordinator returns envelopes and the log keeps growing.
    """
    log_path = coordinator.COORD_LOG
    sizes = [os.path.getsize(log_path)]

    phrases = [
        "area description: foot traffic moderate",
        "tree description: dbh 24 in",
        "targets section summary",  # request service
        "targets: walkway occupied daily",
        "summary of targets section",  # request service
    ]
    for p in phrases:
        out = coordinator.handle_turn(p)
        assert out["ok"] in (True, False)  # both paths handle errors internally
        sizes.append(os.path.getsize(log_path))
        assert sizes[-1] >= sizes[-2], "Log size should be non-decreasing"

    # We should have at least as many TURN blocks as phrases
    text = _read(log_path)
    assert text.count("TURN") >= len(phrases)
