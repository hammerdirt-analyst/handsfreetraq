# nodes/intent_llm.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal, Type

from pydantic import BaseModel, Field, ConfigDict

# Reuse the exact same Outlines/OpenAI wiring you already use
# If ModelFactory lives elsewhere, adjust import path accordingly.
from models2 import ModelFactory  # <-- uses outlines.from_openai(...)

# ---------------- Fixed label set (must match Coordinator routing) ----------------
IntentLabel = Literal[
    "PROVIDE_DATA",
    "REQUEST_SUMMARY",
    "REQUEST_REPORT",
    "WHAT_IS_LEFT",
    "ASK_FIELD",
    "ASK_QUESTION",
    "SMALL_TALK",
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
        "You are an intent classifier for an arborist-report agent.\n"
        "Return ONLY a JSON object that matches exactly:\n"
        '{ "intent": "PROVIDE_DATA|REQUEST_SUMMARY|REQUEST_REPORT|WHAT_IS_LEFT|ASK_FIELD|ASK_QUESTION|SMALL_TALK" }\n'
        "\n"
        "BRIGHT-LINE RULE:\n"
        "- If the user states ANY concrete report fact — first-person or third-person — choose PROVIDE_DATA.\n"
        "  Facts include (but aren’t limited to): name, phone, email, address, license, species, DBH, height,\n"
        "  canopy, crown shape, targets, risks, recommendations.\n"
        "\n"
        "Other labels:\n"
        "- REQUEST_SUMMARY: asks for a brief recap of the current state.\n"
        "- REQUEST_REPORT: asks for the full report text.\n"
        "- WHAT_IS_LEFT: asks what remains to be filled.\n"
        "- ASK_FIELD: asks about a specific stored field (e.g., “what did you capture for DBH?”).\n"
        "- ASK_QUESTION: general question about trees/site unrelated to stored fields.\n"
        "- SMALL_TALK: greetings/thanks/acks with no report data.\n"
        "\n"
        "Examples (format -> intent):\n"
        '  "my name is roger erismann" -> {"intent":"PROVIDE_DATA"}\n'
        '  "customer address is 12 oak ave san jose ca 95112" -> {"intent":"PROVIDE_DATA"}\n'
        '  "dbh is 24 inches" -> {"intent":"PROVIDE_DATA"}\n'
        '  "give me a short summary" -> {"intent":"REQUEST_SUMMARY"}\n'
        '  "what\'s left?" -> {"intent":"WHAT_IS_LEFT"}\n'
        '  "what did you capture for DBH?" -> {"intent":"ASK_FIELD"}\n'
        '  "thanks!" -> {"intent":"SMALL_TALK"}\n'
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
    allowed = {
        "PROVIDE_DATA", "REQUEST_SUMMARY", "REQUEST_REPORT",
        "WHAT_IS_LEFT", "ASK_FIELD", "ASK_QUESTION", "SMALL_TALK"
    }
    if label not in allowed:
        raise RuntimeError(f"Intent LLM returned invalid label: {label!r}")

    return IntentOutput(intent=label)
