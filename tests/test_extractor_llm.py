# tests/test_extractor_llm.py
import types
import pytest

from nodes import llm_extractor as le
from nodes import ol_backends

# Build a fake outlines response in the exact shape your extractor expects
def _fake_full_output():
    # Use the real Pydantic class from your module so validation is identical
    payload = le._FullLLMOutput(
        updates=le.UpdatesRoot(
            customer_info=le.CustomerInfoUpdate(
                name="Mr Smith",
                address=le.AddressUpdate(
                    street="123 Plum Street",
                    city="Stockton",
                    state="CA",
                    postal_code=None,
                ),
                phone="445 907 8901",
            ),
            tree_description=le.TreeDescriptionUpdate(
                type_common="gray pine",
                height_ft="53",
                dbh_in="28",
            ),
            area_description=le.AreaDescriptionUpdate(
                context="suburban",
                site_use="residential",
            ),
        ),
        narrate_paths=["customer_info.narratives", "tree_description.narratives"],
        declined_paths=[],
        utterance_intent="PROVIDE_DATA",
        confirmation_stub="Noted.",
    )
    return payload

@pytest.fixture
def patch_outlines(monkeypatch):
    def fake_call(*, system_prompt, user_utterance, schema_model, temperature=0.2, backend_mode=None):
        return _fake_full_output()
    monkeypatch.setattr(ol_backends, "outlines_generate_schema_constrained", fake_call)
    yield

def test_llm_extractor_happy_path_returns_updates(patch_outlines):
    extractor = le.LLMExtractor()
    out = extractor.extract("We inspected a gray pine for Mr Smith at 123 Plum Street, Stockton CA.")
    assert out.utterance_intent == "PROVIDE_DATA"
    assert out.updates["customer_info"]["name"] == "Mr Smith"
    assert "customer_info.narratives" in out.narrate_paths
    assert out.confirmation_stub.lower().startswith("noted")
