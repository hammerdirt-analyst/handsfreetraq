"""
Project: Arborist Agent
File: intent_model.py
Author: roger erismann

LLM intent classifier that maps a user utterance to exactly one label:
PROVIDE_STATEMENT or REQUEST_SERVICE. Designed for JSON-only, strict schema.

Methods & Classes
- type IntentLabel = Literal['PROVIDE_STATEMENT','REQUEST_SERVICE']
- @dataclass IntentOutput { intent: IntentLabel }
- class IntentSchema(pydantic): { intent } with extra="forbid"
- classify_intent_llm(utterance: str) -> IntentOutput
  - Validates environment (LLM_BACKEND=openai), builds short JSON-only prompt,
    calls ModelFactory.get(), validates parsed label.

Dependencies
- Internal: models.ModelFactory
- External: pydantic
- Stdlib: os, dataclasses, typing
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal, Type

from pydantic import BaseModel, Field, ConfigDict

# Reuse the exact same Outlines/OpenAI wiring you already use
# If ModelFactory lives elsewhere, adjust import path accordingly.
from models import ModelFactory  # <-- uses outlines.from_openai(...)

# ---------------- Fixed label set (must match Coordinator routing) ----------------
IntentLabel = Literal[
    'PROVIDE_STATEMENT',
    'REQUEST_SERVICE'
]

@dataclass
class IntentOutput:
    intent: IntentLabel

class IntentSchema(BaseModel):
    """
    Strict schema for OpenAI JSON-mode via Outlines.
    All keys required; no extras.
    """
    intent: IntentLabel = Field(...)
    model_config = ConfigDict(extra="forbid")

# ----------------------------- Public API ---------------------------------------
def classify_intent_llm(utterance: str) -> IntentOutput:
    """
    Single LLM call -> exactly one IntentLabel.
    LLM-only (no heuristics). Raises RuntimeError on config/call/parse error.
    """
    text = (utterance or "").strip()
    if not text:
        return IntentOutput(intent="SMALL_TALK")

    if os.getenv("LLM_BACKEND", "openai").strip().lower() != "openai":
        raise RuntimeError("Intent LLM unavailable: LLM_BACKEND != 'openai'")

    # Build prompt (short, stable, JSON-only)
    prompt = (
        "You are an intent router for an arborist-report agent.\n"
        "Return ONLY one JSON object:\n"
        '{ "intent": "PROVIDE_STATEMENT|REQUEST_SERVICE" }\n'
        "\n"
        "Definitions:\n"
        "- PROVIDE_STATEMENT: user supplies factual or observational content intended for the report "
        "(tree attributes, health, risks, recommendations, etc.).\n"
        "- REQUEST_SERVICE: user asks for an action (summary, draft, correction, questions, discussion).\n"
        "\n"
        "Examples:\n"
        '"dbh is 24 inches" -> {"intent":"PROVIDE_STATEMENT"}\n'
        '"site use is playground; foot traffic is high" -> {"intent":"PROVIDE_STATEMENT"}\n'
        '"recommend pruning to remove dead branches" -> {"intent":"PROVIDE_STATEMENT"}\n'
        '"give me a short summary" -> {"intent":"REQUEST_SERVICE"}\n'
        '"what’s left?" -> {"intent":"REQUEST_SERVICE"}\n'
        '"make a draft report" -> {"intent":"REQUEST_SERVICE"}\n'
        '"why do roots lift sidewalks?" -> {"intent":"REQUEST_SERVICE"}\n'
        "\n"
        f"Utterance: {text}\n"
    )

    # One call through Outlines+OpenAI v1
    try:
        model = ModelFactory.get()
        raw = model(prompt, IntentSchema, temperature=0.0, max_tokens=40)
        parsed: IntentSchema = IntentSchema.model_validate_json(raw)
    except Exception as e:
        raise RuntimeError(f"Intent LLM call failed: {e}")

    label = str(parsed.intent).strip().upper()
    allowed = {"PROVIDE_STATEMENT", "REQUEST_SERVICE"}
    if label not in allowed:
        raise RuntimeError(f"Intent LLM returned invalid label: {label!r}")

    return IntentOutput(intent=label)
