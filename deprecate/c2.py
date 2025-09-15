# arborist_report/models.py
"""
Arborist Agent — Structured Models

Purpose
-------
Central Pydantic models used for structured extraction and service routing.

What changed in this revision
-----------------------------
1) Canonical sentinels
   - String sentinel for missing user input:  NOT_PROVIDED = "Not provided"
   - Sentinel for extractor miss (expected a field but couldn’t parse it): NOT_FOUND = "Not Found"

2) State-aligned shapes (no shim)
   - The models here now mirror the shapes in ReportState exactly so we don’t
     need an adapter when merging.
   - For **tree_description**, several fields are lists in `ReportState`
     and therefore are lists here as well:
       * trunk_notes: List[str]
       * roots: List[str]
       * defects: List[str]
       * general_observations: List[str]
       * pests_pathogens_observed: List[str]
       * physiological_stress_signs: List[str]
       * narratives: List[str]   (kept for parity with state snapshots)

3) Normalization rules built into the model validators
   - All string fields are trimmed; blank/whitespace -> "Not provided".
   - “Noise” values like "n/a", "none" are coerced to "Not provided".
   - List fields accept strings or lists. They are normalized as:
       * str -> [normalized_str] (unless noise -> ["Not provided"])
       * [] or lists containing only noise/empty -> ["Not provided"]
     This guarantees downstream logic doesn’t have to special-case empties.

4) Extractor return envelope unchanged
   - Extractors still return:
       {"updates": <SectionUpdatesModel>}
     which here is `ExtractorReturnTree(updates=UpdatesTree(tree_description=...))`
   - This continues to satisfy the StructuredModel / ModelFactory wrapper.

Notes
-----
- These models use `extra="forbid"` so that accidental keys from LLMs are rejected.
- If a future extractor truly cannot find a value that *should* exist, it may
  set a field to NOT_FOUND ("Not Found"). The Coordinator and Top Agent can use
  that to highlight “attempted but not extracted” to the arborist.

"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List, Optional, TypedDict, Any
from langchain_openai import ChatOpenAI
import json

from pydantic import BaseModel, Field, ConfigDict, field_validator

# ----------------------------- Sentinels & helpers -----------------------------

NOT_PROVIDED = "Not provided"
NOT_FOUND = "Not Found"

_NOISE_STRINGS = {"", "n/a", "na", "none", "no", "null", "not applicable", NOT_PROVIDED.lower()}

# --- Shared chat invocation for LangChain-based agents -----------------------
def chatllm_invoke(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, str]] = None,
    model_name: Optional[str] = None,
) -> Dict[str, Any]:
    mdl = model_name or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(
        model=mdl,
        temperature=temperature,
        max_tokens=max_tokens,
        **({"response_format": response_format} if response_format else {})
    )
    ai_msg = llm.invoke(messages)

    meta = getattr(ai_msg, "response_metadata", {}) or {}
    usage = meta.get("token_usage", {}) or {}
    tokens = {
        "in": int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
        "out": int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
    }

    content = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
    parsed: Optional[Any] = None
    if response_format and response_format.get("type") == "json_object":
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = None

    return {
        "text": content,
        "parsed": parsed,
        "tokens": tokens,
        "model": mdl,
        "raw": ai_msg,
    }

def _norm_str(v: Optional[str]) -> str:
    """Trim and coerce noise/empty -> NOT_PROVIDED."""
    if v is None:
        return NOT_PROVIDED
    s = str(v).strip()
    if s.lower() in _NOISE_STRINGS:
        return NOT_PROVIDED
    return s or NOT_PROVIDED


def _norm_list(value) -> List[str]:
    """
    Accept str|list for list-like fields. Coerce to a non-empty list.
    If empty or all-noise -> ["Not provided"].
    """
    items: List[str]
    if value is None:
        return [NOT_PROVIDED]
    if isinstance(value, str):
        s = _norm_str(value)
        return [s] if s != NOT_PROVIDED else [NOT_PROVIDED]
    if isinstance(value, list):
        out = []
        for x in value:
            sx = _norm_str(str(x) if x is not None else "")
            if sx != NOT_PROVIDED:
                out.append(sx)
        return out or [NOT_PROVIDED]
    # Fallback: stringify
    return [_norm_str(str(value))]


# ----------------------------- Common token typing ----------------------------

class TokenDict(TypedDict, total=False):
    in_: int  # not used directly; kept for reference
    out: int
    in_: int
    out: int


# ----------------------------- Service routing output -------------------------

from typing import Literal as _Literal

ServiceName = _Literal["MAKE_CORRECTION", "SECTION_SUMMARY", "OUTLINE", "MAKE_REPORT_DRAFT", "NONE", "CLARIFY"]
SectionName = _Literal["tree_description", "risks", "targets", "area_description", "recommendations"]

class ServiceRouteOutput(BaseModel):
    service: ServiceName = Field(...)
    section: Optional[SectionName] = Field(default=None)
    confidence: float = Field(..., ge=0.0, le=1.0)

    tokens: Dict[str, int] = Field(default_factory=lambda: {"in": 0, "out": 0})
    model: str = Field(default="deterministic")

    model_config = ConfigDict(extra="forbid")


# ----------------------------- Tree Description models ------------------------

class TreeDescription(BaseModel):
    # scalar strings (normalized to NOT_PROVIDED when empty/noise)
    type_common: str = Field(default=NOT_PROVIDED)
    type_scientific: str = Field(default=NOT_PROVIDED)
    height_ft: str = Field(default=NOT_PROVIDED)
    canopy_width_ft: str = Field(default=NOT_PROVIDED)
    crown_shape: str = Field(default=NOT_PROVIDED)
    dbh_in: str = Field(default=NOT_PROVIDED)
    health_overview: str = Field(default=NOT_PROVIDED)

    # list fields (accept str|list; normalize to ["Not provided"] when empty/noise)
    trunk_notes: List[str] = Field(default_factory=lambda: [NOT_PROVIDED])
    roots: List[str] = Field(default_factory=lambda: [NOT_PROVIDED])
    defects: List[str] = Field(default_factory=lambda: [NOT_PROVIDED])
    general_observations: List[str] = Field(default_factory=lambda: [NOT_PROVIDED])
    pests_pathogens_observed: List[str] = Field(default_factory=lambda: [NOT_PROVIDED])
    physiological_stress_signs: List[str] = Field(default_factory=lambda: [NOT_PROVIDED])

    # included to mirror ReportState snapshot shape (even if not used by extractors directly)
    narratives: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    # ---- validators (string normalization) ----
    @field_validator(
        "type_common",
        "type_scientific",
        "height_ft",
        "canopy_width_ft",
        "crown_shape",
        "dbh_in",
        "health_overview",
        mode="before",
    )
    @classmethod
    def _v_str(cls, v):
        return _norm_str(v)

    # ---- validators (list normalization) ----
    @field_validator(
        "trunk_notes",
        "roots",
        "defects",
        "general_observations",
        "pests_pathogens_observed",
        "physiological_stress_signs",
        mode="before",
    )
    @classmethod
    def _v_list(cls, v):
        return _norm_list(v)

    @field_validator("narratives", mode="before")
    @classmethod
    def _v_narratives(cls, v):
        # We allow narratives to be empty; if a single string is given, box it.
        if v is None:
            return []
        if isinstance(v, str):
            s = _norm_str(v)
            return [] if s == NOT_PROVIDED else [s]
        if isinstance(v, list):
            return [x for x in (_norm_str(i) for i in v) if x != NOT_PROVIDED]
        return []


class UpdatesTree(BaseModel):
    tree_description: TreeDescription = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnTree(BaseModel):
    updates: UpdatesTree = Field(...)
    model_config = ConfigDict(extra="forbid")


# ----------------------------- StructuredModel wrapper ------------------------

# Note: kept identical to prior behavior; only docstring changes above.
import openai
import outlines

class StructuredModel:
    """
    Unified entry point for Outlines+OpenAI structured calls.

    Call signature:
        __call__(prompt: str, output_type: type[BaseModel], **kwargs) -> dict

    Return shape (always the same):
        {
          "parsed": <Pydantic instance of output_type>,
          "raw": <str>,
          "tokens": {"in": int, "out": int},
          "model": <str>,
        }
    """
    def __init__(self, client: openai.OpenAI, model_name: str):
        self._client = client
        self._model_name = model_name
        self._fn = outlines.from_openai(client, model_name)

    def __call__(self, prompt: str, output_type: type[BaseModel], **kwargs) -> dict:
        resp = self._fn(prompt, output_type, **kwargs)

        if isinstance(resp, BaseModel):
            parsed = resp
            try:
                raw_text = parsed.model_dump_json(exclude_none=False)
            except Exception:
                raw_text = parsed.model_dump(exclude_none=False)
                raw_text = raw_text if isinstance(raw_text, str) else str(raw_text)
        else:
            try:
                parsed = output_type.model_validate_json(resp)
                raw_text = resp
            except Exception:
                parsed = output_type.model_validate(resp)
                try:
                    raw_text = parsed.model_dump_json(exclude_none=False)
                except Exception:
                    raw_text = str(resp)

        tokens = {"in": 0, "out": 0}
        model_name = self._model_name

        return {"parsed": parsed, "raw": raw_text, "tokens": tokens, "model": model_name}


class ModelFactory:
    @staticmethod
    @lru_cache(maxsize=1)
    def get() -> StructuredModel:
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("ERROR: set OPENAI_API_KEY")
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        client = openai.OpenAI()
        return StructuredModel(client, model_name)
