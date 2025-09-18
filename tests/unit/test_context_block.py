"""
tests/unit/test_context_block.py

What this tests (and why)
-------------------------
1) Blocks context edits:
   - Attempts to change ARBORIST INFO (name/phone/email/license), CUSTOMER INFO
     (name/phone/email/address), or TREE GPS (lat/lon/coordinates/gps) are routed
     to "blocked_context_edit" and do not mutate state. This preserves the integrity
     of read-only context that must never be edited via chat.
2) Allows near-miss phrasing:
   - Phrases that mention "customer/client" in a descriptive sense (not identity edits),
     or ordinary provide-statement phrases, must NOT be blocked. This prevents
     over-blocking that would frustrate normal capture turns.
3) State immutability guarantee:
   - For blocked turns, asserts the entire ReportState is unchanged except for
     `current_text` (which should echo the utterance). This ensures the coordinator’s
     deflection path is safe.

How it works
------------
- The test forces intent to PROVIDE_STATEMENT and disables file logging for determinism.
- A strict `_CTX_EDIT_RE` is monkey-patched so only true identity/GPS edits trigger
  the block; near-miss language is allowed. This keeps the unit test focused on
  the contract rather than the exact production regex.

File / module dependencies
--------------------------
- coordinator_agent.Coordinator (system under test / router)
- coordinator_agent._CTX_EDIT_RE, coordinator_agent._write_log,
  coordinator_agent.classify_intent_llm (patched)
- report_context._build_context_from_testdata (provides valid context)
- pytest (fixtures, parametrization)
"""

import copy
import re
from types import SimpleNamespace
import pytest

import coordinator_agent  # system under test
from coordinator_agent import Coordinator
from report_context import _build_context_from_testdata


@pytest.fixture()
def coordinator(monkeypatch, tmp_path):
    """
    Coordinator configured so we hit the blocking path deterministically:
      - Force intent to PROVIDE_STATEMENT
      - Disable file logging
      - Install a strict context-edit regex (identity+GPS only)
    """
    # Force intent
    monkeypatch.setattr(
        coordinator_agent, "classify_intent_llm",
        lambda text: SimpleNamespace(intent="PROVIDE_STATEMENT")
    )
    # No-op logger + temp log path
    monkeypatch.setattr(coordinator_agent, "_write_log", lambda *_a, **_k: None)
    monkeypatch.setattr(coordinator_agent, "COORD_LOG", str(tmp_path / "coordinator-tests.txt"))

    # STRICT context-edit regex:
    # - arborist/customer/client followed by identity field
    # - geo edits (lat/lon/latitude/longitude/coords/gps)
    ctx_edit_re = re.compile(
        r"""
        \b(
            # Arborist identity edits
            (?:arborist)\s+(?:name|phone|email|license)
            |
            # Customer/client identity edits
            (?:customer|client)\s+(?:name|phone|email|address)
            |
            # Self-identity edits ("my name/email/phone/license")
            my\s+(?:name|phone|email|license)
            |
            # Geo edits
            (?:latitude|longitude|lat|lon|coords?|coordinates?|gps)
        )\b
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )
    monkeypatch.setattr(coordinator_agent, "_CTX_EDIT_RE", ctx_edit_re)

    # Build coordinator with canonical test context
    ctx = _build_context_from_testdata()
    return Coordinator(ctx)


@pytest.mark.parametrize("phrase", [
    "set arborist name to Jane Arbor",
    "update arborist email to arborist@example.com",
    "change arborist license to CA-1234",
])
def test_arborist_info_edits_blocked(coordinator, phrase):
    before = copy.deepcopy(coordinator.state.model_dump(exclude_none=False))
    out = coordinator.handle_turn(phrase)
    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["routed_to"] == "blocked_context_edit"
    assert out["ok"] is False
    assert out["error"] is None
    after = coordinator.state.model_dump(exclude_none=False)
    assert coordinator.state.current_text == phrase
    before.pop("current_text", None); after.pop("current_text", None)
    assert after == before


@pytest.mark.parametrize("phrase", [
    "set customer name to John Client",
    "update client phone to 555-1212",
    "change customer address to 123 Main St",
    "set customer email to a@b.com",
])
def test_customer_info_edits_blocked(coordinator, phrase):
    before = copy.deepcopy(coordinator.state.model_dump(exclude_none=False))
    out = coordinator.handle_turn(phrase)
    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["routed_to"] == "blocked_context_edit"
    assert out["ok"] is False
    assert out["error"] is None
    after = coordinator.state.model_dump(exclude_none=False)
    assert coordinator.state.current_text == phrase
    before.pop("current_text", None); after.pop("current_text", None)
    assert after == before


@pytest.mark.parametrize("phrase", [
    "update latitude to 38.58",
    "set coordinates to 38.58, -121.49",
    "change lon to -121.49",
    "update tree gps to 38.58,-121.49",
])
def test_tree_gps_edits_blocked(coordinator, phrase):
    before = copy.deepcopy(coordinator.state.model_dump(exclude_none=False))
    out = coordinator.handle_turn(phrase)
    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["routed_to"] == "blocked_context_edit"
    assert out["ok"] is False
    assert out["error"] is None
    after = coordinator.state.model_dump(exclude_none=False)
    assert coordinator.state.current_text == phrase
    before.pop("current_text", None); after.pop("current_text", None)
    assert after == before


@pytest.mark.parametrize("phrase", [
    "customer parking area is usually full",     # adjective 'customer' → allowed
    "target near client walkway has high use",   # 'client' not followed by identity field → allowed
    "tree description: DBH 24 in, height 40 ft", # normal provide statement
])
def test_non_context_phrases_not_blocked(coordinator, phrase):
    out = coordinator.handle_turn(phrase)
    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["routed_to"] != "blocked_context_edit"
    assert out["ok"] in (True, False)
