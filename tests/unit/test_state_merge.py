# tests/unit/test_state_merge.py
"""
State merge + provenance unit tests.

What is tested
--------------
- prefer_existing vs last_write policy for scalars and lists.
- “Not provided” semantics and when a single "Not Found" provenance row is emitted.
- Successful scalar apply records a field-level provenance row.
- List appends accumulate and record provenance.
- No-updates envelope → one "Not Found" row, no state change.
- Correction de-dup (policy='last_write'): for scalars, older provenance rows
  for the same section.path are removed so only the latest is active.

Why this matters
----------------
Deterministic merge behavior (append for lists, guarded/overriding for scalars),
plus precise provenance, prevents double-accounting and keeps corrections clean.

File dependencies
-----------------
- report_state.ReportState, report_state.NOT_PROVIDED (system under test)
"""

from typing import Any, Dict

from report_state import ReportState, NOT_PROVIDED


def _merge(
    s: ReportState,
    updates: Dict[str, Any] | None,
    *,
    policy: str = "prefer_existing",
    turn_id: str = "T",
    ts: str = "TS",
    domain: str = "tree_description",
    extractor: str = "TreeDescriptionExtractor",
    model_name: str = "gpt-4o-mini",
    segment_text: str = "seg",
) -> ReportState:
    """Helper to call model_merge_updates with standard metadata."""
    return s.model_merge_updates(
        updates,
        policy=policy,
        turn_id=turn_id,
        timestamp=ts,
        domain=domain,
        extractor=extractor,
        model_name=model_name,
        segment_text=segment_text,
    )


# ---------------------- Original tests (kept as-is) ----------------------

def test_prefer_existing_blocks_not_provided_but_writes_one_not_found_row():
    """
    Existing scalar is provided; incoming says Not provided.
    - State should NOT change (prefer_existing)
    - BUT per policy, extractor was invoked → one Not Found provenance row.
    """
    s = ReportState()
    s.tree_description.height_ft = "45 feet"

    updates = {"updates": {"tree_description": {"height_ft": NOT_PROVIDED}}}
    before_len = len(s.provenance)

    s2 = _merge(
        s,
        updates,
        policy="prefer_existing",
        turn_id="T2",
        ts="TS2",
        domain="tree_description",
        segment_text="(empty/unsure)",
    )

    assert s2.tree_description.height_ft == "45 feet"
    # exactly one new row because extractor ran but nothing applied
    assert len(s2.provenance) == before_len + 1
    row = s2.provenance[-1]
    assert row.section == "tree_description"
    assert row.path == "Not Found"
    assert row.value == "Not Found"
    assert row.text == "(empty/unsure)"


def test_last_write_overwrites_with_not_provided_and_writes_one_not_found_row():
    """
    policy=last_write: incoming Not provided overwrites scalar.
    - State becomes NOT_PROVIDED
    - No field-level provenance (value not provided), but we DO log one Not Found row for the segment.
    """
    s = ReportState()
    s.tree_description.height_ft = "45 feet"

    updates = {"updates": {"tree_description": {"height_ft": NOT_PROVIDED}}}
    before_len = len(s.provenance)

    s2 = _merge(
        s,
        updates,
        policy="last_write",
        turn_id="T3",
        ts="TS3",
        domain="tree_description",
        segment_text="(redaction)",
    )

    assert s2.tree_description.height_ft == NOT_PROVIDED
    assert len(s2.provenance) == before_len + 1
    row = s2.provenance[-1]
    assert row.path == "Not Found"
    assert row.value == "Not Found"
    assert row.text == "(redaction)"


def test_empty_list_input_results_in_one_not_found_row_and_no_change():
    """
    Incoming empty list for a list field:
    - No items appended (no state change to report data)
    - But we still emit one Not Found provenance row for the segment.
    """
    s = ReportState()
    before = s.model_dump(exclude_none=False)
    before_len = len(s.provenance)

    updates = {"updates": {"tree_description": {"defects": []}}}
    s2 = _merge(
        s,
        updates,
        policy="prefer_existing",
        turn_id="T5a",
        ts="TS5a",
        domain="tree_description",
        segment_text="defects: []",
    )

    after = s2.model_dump(exclude_none=False)

    # Compare state excluding provenance (since we expect one new Not Found row)
    before_no_prov = dict(before)
    after_no_prov = dict(after)
    before_no_prov.pop("provenance", None)
    after_no_prov.pop("provenance", None)
    assert after_no_prov == before_no_prov

    # And verify that exactly one provenance row was added, with Not Found markers
    assert len(s2.provenance) == before_len + 1
    row = s2.provenance[-1]
    assert row.section == "tree_description"
    assert row.text == "defects: []"
    assert row.path == "Not Found"
    assert row.value == "Not Found"


def test_scalar_apply_records_field_row():
    """
    A normal successful capture:
    - Scalar field gets applied
    - Field-level provenance row recorded (not Not Found)
    """
    s = ReportState()
    before_len = len(s.provenance)

    updates = {"updates": {"tree_description": {"dbh_in": "32"}}}
    s2 = _merge(
        s,
        updates,
        policy="prefer_existing",
        turn_id="T6",
        ts="TS6",
        domain="tree_description",
        segment_text='DBH 32"',
    )

    assert s2.tree_description.dbh_in == "32"
    assert len(s2.provenance) == before_len + 1
    row = s2.provenance[-1]
    assert row.path == "tree_description.dbh_in"
    assert row.value == "32"
    assert row.text == 'DBH 32"'


# ---------------------- Additions: tighter coverage ----------------------

def test_list_append_accumulates_and_records_provenance():
    """
    Appending to a list field should add items and record a field-level provenance row.
    """
    s = ReportState()
    before_len = len(s.provenance)

    updates = {"updates": {"tree_description": {"defects": ["minor seam on west scaffold"]}}}
    s2 = _merge(
        s,
        updates,
        policy="prefer_existing",
        turn_id="T7",
        ts="TS7",
        domain="tree_description",
        segment_text="defects: minor seam on west scaffold",
    )

    assert s2.tree_description.defects == ["minor seam on west scaffold"]
    assert len(s2.provenance) == before_len + 1
    row = s2.provenance[-1]
    assert row.path == "tree_description.defects"
    assert "minor seam" in row.value


def test_no_updates_envelope_emits_single_not_found_provenance():
    """
    Passing updates=None means extractor ran but yielded no applicable updates:
    - No state change
    - One 'Not Found' provenance row with the segment text.
    """
    s = ReportState()
    before = s.model_dump(exclude_none=False)
    before_len = len(s.provenance)

    s2 = _merge(
        s,
        None,
        policy="prefer_existing",
        turn_id="T8",
        ts="TS8",
        domain="tree_description",
        segment_text="(no signal)",
    )

    after = s2.model_dump(exclude_none=False)
    # exclude provenance for equality
    before_no_prov = dict(before); before_no_prov.pop("provenance", None)
    after_no_prov = dict(after);   after_no_prov.pop("provenance", None)
    assert after_no_prov == before_no_prov

    assert len(s2.provenance) == before_len + 1
    row = s2.provenance[-1]
    assert row.section == "tree_description"
    assert row.path == "Not Found"
    assert row.value == "Not Found"
    assert row.text == "(no signal)"


def test_last_write_correction_deduplicates_scalar_provenance():
    """
    When correcting a scalar with policy='last_write':
    - The later write replaces the prior value in state.
    - Older provenance rows for the same section.path are removed,
      leaving a single row for that key.
    """
    s = ReportState()

    # First write
    s1 = _merge(
        s,
        {"updates": {"tree_description": {"dbh_in": "28"}}},
        policy="last_write",
        turn_id="T9a",
        ts="TS9a",
        domain="tree_description",
        segment_text="dbh 28 in",
    )
    # Second correction write (same path)
    s2 = _merge(
        s1,
        {"updates": {"tree_description": {"dbh_in": "30"}}},
        policy="last_write",
        turn_id="T9b",
        ts="TS9b",
        domain="tree_description",
        segment_text="dbh 30 in",
    )

    # State reflects the latest value
    assert s2.tree_description.dbh_in == "30"

    # Exactly one provenance row exists for this path+section (the latest)
    path_rows = [r for r in s2.provenance if r.section == "tree_description" and r.path == "tree_description.dbh_in"]
    assert len(path_rows) == 1
    assert path_rows[0].value == "30"
