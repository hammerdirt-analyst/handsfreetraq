"""
llm_backends.py
Author: Roger Erismann

Backend integration for schema-constrained LLM calls via
LangChain’s `ChatOutlines`, supporting OpenAI and HF models.
"""

from __future__ import annotations
import os
from typing import Type
from pydantic import BaseModel


class LLMUnavailableError(RuntimeError):
    """Raised when the selected backend fails (no auto-fallback)."""
    pass


# ---------------- Config ---------------- #
LLM_BACKEND = os.getenv("LLM_BACKEND", "openai").strip().lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "openai/gpt-4o-mini")
HF_MODEL = os.getenv("HF_MODEL", "hf/meta-llama/Meta-Llama-3-8B-Instruct")


# ---------------- Public API ---------------- #
def outlines_structured_call(
    utterance: str,
    schema: Type[BaseModel],
    *,
    temperature: float = 0.2,
    request_timeout: float | None = 30.0,
    max_retries: int = 2,
) -> BaseModel:
    """
    Perform a structured LLM call using LangChain’s `ChatOutlines`,
    returning output validated against a Pydantic schema.
    """
    try:
        from langchain_community.chat_models.outlines import ChatOutlines
    except Exception as e:
        raise LLMUnavailableError(f"LangChain Outlines not available: {repr(e)}")

    backend = LLM_BACKEND
    model_id = (
        OPENAI_MODEL if backend == "openai"
        else HF_MODEL if backend == "hf"
        else None
    )
    if not model_id:
        raise LLMUnavailableError(
            f"Unknown LLM_BACKEND '{backend}'. Use 'openai' or 'hf'."
        )

    try:
        chat = ChatOutlines(
            model=model_id,
            temperature=temperature,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
        chain = chat.with_structured_output(schema)
        result = chain.invoke(utterance)

        if isinstance(result, dict):
            return schema.model_validate(result)
        return schema.model_validate(result.model_dump())
    except Exception as e:
        raise LLMUnavailableError(f"{backend} backend failed: {repr(e)}")
