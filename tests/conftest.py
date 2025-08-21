# tests/conftest.py
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

@pytest.fixture(autouse=True)
def env_isolation(monkeypatch):
    # Keep runtime env clean during tests
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    yield

@pytest.fixture
def patch_outlines(monkeypatch):
    """
    Patch the EXACT symbol used by LLMExtractor:
    nodes.llm_extractor.outlines_generate_schema_constrained
    """
    import nodes.llm_extractor as le

    def fake_ogsc(*, system_prompt, user_utterance, schema_model, **_):
        payload = {
            "updates": {
                "customer_info": {
                    "name": "Mr Smith",
                    "address": {"street": "123 Plum Street", "city": "Stockton", "state": "CA"},
                },
                "tree_description": {"type_common": "gray pine"},
            },
            "narrate_paths": [],
            "declined_paths": [],
            "utterance_intent": "PROVIDE_DATA",
            "confirmation_stub": "Noted.",
        }
        return schema_model.model_validate(payload)

    monkeypatch.setattr(le, "outlines_generate_schema_constrained", fake_ogsc, raising=True)
