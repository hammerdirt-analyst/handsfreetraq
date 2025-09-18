# intent_model.py (cleaned to use ModelFactory normalized return)

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal, Dict

from pydantic import BaseModel, Field, ConfigDict
from arborist_report.models import ModelFactory

IntentLabel = Literal['PROVIDE_STATEMENT','REQUEST_SERVICE']

@dataclass
class IntentOutput:
    intent: IntentLabel
    tokens: Dict[str, int]
    model: str

class IntentSchema(BaseModel):
    intent: IntentLabel = Field(...)
    model_config = ConfigDict(extra="forbid")

def classify_intent_llm(utterance: str) -> IntentOutput:
    text = (utterance or "").strip()
    # Empty utterance → treat as a service request so Coordinator can route
    if not text:
        return IntentOutput(intent='REQUEST_SERVICE', tokens={'in': 0, 'out': 0}, model='deterministic')

    if os.getenv("LLM_BACKEND", "openai").strip().lower() != "openai":
        raise RuntimeError("Intent LLM unavailable: LLM_BACKEND != 'openai'")

    prompt = (
        "You are an intent router for an arborist_report agent.\n"
        "Return ONLY one JSON object:\n"
        '{ "intent": "PROVIDE_STATEMENT|REQUEST_SERVICE" }\n\n'
        "Definitions:\n"
        "- PROVIDE_STATEMENT: user supplies factual/observational content for the report.\n"
        "- REQUEST_SERVICE: user asks for an action (summary, draft, correction, questions).\n\n"
        "Examples:\n"
        '"dbh is 24 inches" -> {"intent":"PROVIDE_STATEMENT"}\n'
        '"give me a short summary" -> {"intent":"REQUEST_SERVICE"}\n\n'
        f"Utterance: {text}\n"
    )

    try:
        call = ModelFactory.get()(prompt, IntentSchema, temperature=0.0, max_tokens=40)
        # call is: {"parsed": Pydantic, "raw": str, "tokens": {...}, "model": "..."}
        parsed: IntentSchema = call["parsed"]
        tokens: Dict[str, int] = call["tokens"]
        model_name: str = call["model"]
    except Exception as e:
        raise RuntimeError(f"Intent LLM call failed: {e}")

    label = str(parsed.intent).strip().upper()
    if label not in {"PROVIDE_STATEMENT", "REQUEST_SERVICE"}:
        raise RuntimeError(f"Intent LLM returned invalid label: {label!r}")

    return IntentOutput(intent=label, tokens=tokens, model=model_name)
