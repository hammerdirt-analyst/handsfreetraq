# tests/unit/test_segmentation.py
"""
Segment parsing unit tests.

What is tested
--------------
- Single explicit scope → one (section, payload) pair.
- Multiple explicit scopes in one utterance → ordered list of pairs.
- Navigation-only scopes (header with no payload) are kept as empty payloads.
- Cursor-first fallback: if no explicit scope is present, use current_section.
- Trimming/normalization: headers and payloads are stripped of extra whitespace.

Why this matters
----------------
The Coordinator relies on segmentation to route each scoped payload to the
correct extractor. Deterministic, stable parsing keeps merges/provenance sane.

File dependencies
-----------------
- coordinator_agent.Coordinator (SUT for _parse_scoped_segments via instance)
- report_context._build_context_from_testdata (to build a valid context)
"""

import pytest

import coordinator_agent
from coordinator_agent import Coordinator
from report_context import _build_context_from_testdata


@pytest.fixture()
def coord():
    """Minimal Coordinator with valid context; no LLMs are invoked in these tests."""
    ctx = _build_context_from_testdata()
    return Coordinator(ctx)


def _segments(coord: Coordinator, text: str):
    """Helper to access the module-level parse helper through the instance."""
    # The parser is a module function; Coordinator uses it directly.
    # Import from the module where it lives so tests remain stable if it’s renamed.
    return coordinator_agent._parse_scoped_segments(text, coord.state.current_section)


def test_single_scope(coord):
    segs = _segments(coord, "tree description: DBH 28 in; height 60 ft")
    assert segs == [("tree_description", "DBH 28 in; height 60 ft")]


def test_multi_scope_order_and_trim(coord):
    text = """
      area description: suburban frontage with moderate foot traffic
      targets: sidewalk occupied daily
      risks: likelihood low; severity moderate
    """
    segs = _segments(coord, text)
    assert segs == [
        ("area_description", "suburban frontage with moderate foot traffic"),
        ("targets", "sidewalk occupied daily"),
        ("risks", "likelihood low; severity moderate"),
    ]


def test_navigation_only_sections(coord):
    text = "area description:\n\ntree description: DBH 24 in"
    segs = _segments(coord, text)
    # navigation-only segment has empty payload; Coordinator should skip extractor call for it
    assert segs == [
        ("area_description", ""),
        ("tree_description", "DBH 24 in"),
    ]


def test_cursor_first_fallback(coord):
    # Parser returns no segments when there is no explicit header
    segs = coordinator_agent._parse_scoped_segments("DBH 30 in, crown vase shaped",
                                                    coord.state.current_section)
    assert segs == []

    # Coordinator applies cursor-first fallback
    out = coord.handle_turn("DBH 30 in, crown vase shaped")
    assert out["intent"] == "PROVIDE_STATEMENT"
    assert out["routed_to"].startswith("cursor")
    # segment echo is kept in result
    assert any(s.get("section") == coord.state.current_section for s in out["result"]["segments"])



def test_ignores_empty_noise(coord):
    text = " \n  targets:   \n\n   risks: severity high  "
    segs = _segments(coord, text)
    # ‘targets’ is navigation-only (empty payload after trim)
    assert segs == [
        ("targets", ""),
        ("risks", "severity high"),
    ]
