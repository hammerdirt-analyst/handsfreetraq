# tests/test_models_validation.py
from typing import Dict, List
from pydantic import BaseModel
import pytest

from models import ReportState, IssueBucket, NOT_PROVIDED

def _collect_issues(state: ReportState) -> List[Dict[str, str]]:
    return getattr(state.meta, "issues", [])

def test_area_context_enum_and_issue_logging():
    ib = IssueBucket()
    data = {
        "area_description": {
            "context": "Suburuban",  # misspelled → should be rejected or normalized by your mapping
        }
    }
    # Validate with context issues bucket
    state = ReportState.model_validate(data, context={"issues": ib})
    issues = [i for i in ib.items if isinstance(i, dict) or hasattr(i, "model_dump")]
    # Depending on your mapping, either normalized or rejected should appear.
    # We accept either, but assert that NOT_PROVIDED is used if rejected.
    if state.area_description.context == NOT_PROVIDED:
        assert any((it.get("action") == "rejected" or getattr(it, "action", "") == "rejected") for it in issues)
    else:
        assert state.area_description.context in {"urban", "suburban", "rural", "park", "school", "public_buildings", "other"}
        assert any((it.get("action") in ("normalized", "coerced") or getattr(it, "action", "") in ("normalized", "coerced")) for it in issues)

def test_height_and_dbh_bounds_and_coercion():
    ib = IssueBucket()
    data = {
        "tree_description": {
            "height_ft": "420",   # out of allowed range → NOT_PROVIDED + rejected
            "dbh_in": " 28 ",     # should trim/coerce to "28"
        }
    }
    state = ReportState.model_validate(data, context={"issues": ib})
    assert state.tree_description.height_ft == NOT_PROVIDED
    assert state.tree_description.dbh_in == "28"

    actions = [getattr(i, "action", i.get("action")) for i in ib.items]
    assert "rejected" in actions or any(a == "rejected" for a in actions)
    assert any(a in ("normalized", "coerced") for a in actions)

def test_model_merge_updates_accumulates_issues_on_meta():
    base = ReportState()
    updates = {"area_description": {"context": "spaceport"}}  # invalid → NOT_PROVIDED + issue
    ib = IssueBucket()
    new_state = base.model_merge_updates(updates, issues=ib)
    assert hasattr(new_state.meta, "issues")
    assert len(new_state.meta.issues) >= 1
