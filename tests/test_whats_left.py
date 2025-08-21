# tests/test_whats_left.py
from models import ReportState
from whats_left import compute_whats_left

def test_whats_left_shows_missing_fields():
    state = ReportState()
    state = state.model_copy(update={
        "customer_info": {
            "name": "Mr Smith",
            "address": {"street": "123 Plum Street", "city": "Stockton", "state": "CA"}
        }
    })
    remaining = compute_whats_left(state)
    # must include some tree_description fields, etc.
    assert "tree_description" in remaining
    assert "height_ft" in remaining["tree_description"]
