"""
ol_backends.py
Author: Roger Erismann

Backend integration for schema-constrained generation using
Outlines with OpenAI. Provides helpers for strict JSON schema
validation and OpenAI client setup.
"""

from __future__ import annotations
import os
import json
from typing import Literal, Optional
from pydantic import BaseModel
from outlines.models.openai import OpenAI, OpenAIConfig
from outlines import generate
TEST_BYPASS = os.getenv("OFFLINE_TEST") == "1"

# ---------------- Config ---------------- #
BACKEND_MODE: Literal["auto", "openai", "hf"] = (
    os.getenv("LLM_BACKEND", "auto").strip().lower() or "auto"
)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
HF_MODEL = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")


# ---------------- Errors ---------------- #
class HFNotImplemented(RuntimeError):
    """Raised if HuggingFace backend is requested but not implemented."""
    pass


class OpenAIUnavailable(RuntimeError):
    """Raised if OpenAI backend cannot be reached or fails."""
    pass


# ---------------- Helpers ---------------- #
def _strictify_json_schema(schema: dict) -> dict:
    """
    Recursively set `additionalProperties = False` and make all
    object properties required in a JSON Schema.
    """
    def visit(node: dict):
        if not isinstance(node, dict):
            return

        # Recurse into nested schema containers
        for key in ("$defs", "definitions", "properties", "items",
                    "anyOf", "oneOf", "allOf"):
            val = node.get(key)
            if isinstance(val, dict):
                for v in val.values():
                    visit(v)
            elif isinstance(val, list):
                for v in val:
                    visit(v)

        # Strictify object schemas
        if node.get("type") == "object":
            props = node.get("properties", {})
            if isinstance(props, dict) and props:
                node["required"] = list(props.keys())
            node["additionalProperties"] = False

    out = json.loads(json.dumps(schema))
    visit(out)
    return out


def _openai_chat_model(model_name: str, temperature: float = 0.0) -> OpenAI:
    """
    Create an Outlines `OpenAI` model using the async OpenAI client,
    with defensive handling for stray string-based `max_tokens`.
    """
    from openai import AsyncOpenAI

    # Normalize model name
    if "/" in model_name:
        _, model_name = model_name.split("/", 1)

    # Clear environment variables that may leak invalid defaults
    for k in (
        "OPENAI_MAX_TOKENS",
        "OPENAI_COMPLETION_TOKENS",
        "MAX_TOKENS",
        "OPENAI_DEFAULTS",
        "OPENAI_CHAT_COMPLETIONS_DEFAULTS",
        "OPENAI_COMPLETIONS_DEFAULTS",
    ):
        os.environ.pop(k, None)

    cfg = OpenAIConfig(
        model=model_name,
        temperature=float(temperature),
    )
    client = AsyncOpenAI()

    # Defensive wrapper
    orig_create = client.chat.completions.create

    async def _create_coerce_max_tokens(**kwargs):
        mt = kwargs.get("max_tokens", None)
        if isinstance(mt, str):
            if mt.isdigit():
                kwargs["max_tokens"] = int(mt)
            else:
                kwargs.pop("max_tokens", None)
        return await orig_create(**kwargs)

    client.chat.completions.create = _create_coerce_max_tokens
    return OpenAI(client=client, config=cfg)


# ---------------- Public API ---------------- #
def outlines_generate_schema_constrained(
    *,
    system_prompt: str,
    user_utterance: str,
    schema_model: type[BaseModel],
    temperature: float = 0.2,
    backend_mode: Optional[str] = None,
) -> BaseModel:
    """
    Generate structured output constrained by a Pydantic schema using
    Outlines + OpenAI.
    """
    if TEST_BYPASS:
        # Return an empty, valid object for the given schema so tests can proceed
        return schema_model()
    mode = (backend_mode or BACKEND_MODE).strip().lower()

    if mode not in ("openai", "auto"):
        raise HFNotImplemented("HF backend not implemented yet.")

    if not os.getenv("OPENAI_API_KEY"):
        raise OpenAIUnavailable("Missing OPENAI_API_KEY")

    try:
        raw_schema = schema_model.model_json_schema()
        strict_schema = _strictify_json_schema(raw_schema)
        schema_str = json.dumps(strict_schema)

        model = _openai_chat_model(OPENAI_MODEL, temperature=temperature)
        generator = generate.json(model, schema_str)
        raw = generator(system_prompt, user_utterance)
        return schema_model.model_validate(raw)
    except Exception as e:
        raise OpenAIUnavailable(f"OpenAI generation failed: {e!r}")
