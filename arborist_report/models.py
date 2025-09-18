"""
Project: Arborist Agent
File: models.py
Author: roger erismann

LLM wiring (ModelFactory), strict JSON schemas for extractors, a BaseExtractor
protocol, presence computation, and concrete extractor implementations for all sections.

Methods & Classes
- Constants: NOT_PROVIDED
- class ModelFactory: get() -> outlines model (cached); reads OPENAI_API_KEY/OPENAI_MODEL.
- build_prompt(..., user_text: str) -> str: common JSON-only, verbatim-copy prompt builder.
- class BaseExtractor:
  - build_prompt(user_text) -> str  # to implement
  - extract(user_text, *, temperature=0.0, max_tokens=300) -> dict
  - extract_dict(user_text, **kwargs) -> dict: {"result": parsed, "provided_fields": [...]}
- compute_presence(parsed_envelope: dict) -> list[str]: dotted paths with provided (non-sentinel) values.
- Concrete extractors (schema_cls set appropriately):
  - ArboristInfoExtractor, CustomerInfoExtractor, TreeDescriptionExtractor,
    RisksExtractor, AreaDescriptionExtractor, TargetExtractor, RecommendationsExtractor

Dependencies
- External: outlines, openai, pydantic
- Stdlib: os, json, functools.lru_cache, typing
"""

from __future__ import annotations

import os
import json
from functools import lru_cache
from typing import Dict, List, Tuple, Type, Any, Literal, Optional

import outlines
import openai
from pydantic import BaseModel, Field, ConfigDict

from typing import Union
from langchain_openai import ChatOpenAI

NOT_PROVIDED = "Not provided"

# ---- Shared enums (reuse across modules) -------------------------------------
ServiceName = Literal[
    "MAKE_CORRECTION",
    "SECTION_SUMMARY",
    "OUTLINE",
    "MAKE_REPORT_DRAFT",
    "NONE",
]

SectionName = Literal[
    "tree_description",
    "risks",
    "targets",
    "area_description",
    "recommendations",
]

TokenDict = Dict[str, int]  # must contain keys "in" and "out"

# ---- Canonical service-route output (single, flat object) --------------------
class ServiceRouteOutput(BaseModel):
    service: ServiceName = Field(...)
    section: Optional[SectionName] = Field(default=None)
    confidence: float = Field(..., ge=0.0, le=1.0)

    tokens: TokenDict = Field(default_factory=lambda: {"in": 0, "out": 0})
    model: str = Field(default="deterministic")

    model_config = ConfigDict(extra="forbid")


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


# ---------- Strict schemas (LLM-facing) ----------
class Address(BaseModel):
    street: str = Field(...)
    city: str = Field(...)
    state: str = Field(...)
    postal_code: str = Field(...)
    country: str = Field(...)
    model_config = ConfigDict(extra="forbid")


class ArboristInfo(BaseModel):
    name: str = Field(...)
    company: str = Field(...)
    phone: str = Field(...)
    email: str = Field(...)
    license: str = Field(...)
    address: Address = Field(...)
    model_config = ConfigDict(extra="forbid")


class UpdatesArborist(BaseModel):
    arborist_info: ArboristInfo = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnArborist(BaseModel):
    updates: UpdatesArborist = Field(...)
    model_config = ConfigDict(extra="forbid")


class CustomerInfo(BaseModel):
    name: str = Field(...)
    company: str = Field(...)
    phone: str = Field(...)
    email: str = Field(...)
    address: Address = Field(...)
    model_config = ConfigDict(extra="forbid")


class UpdatesCustomer(BaseModel):
    customer_info: CustomerInfo = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnCustomer(BaseModel):
    updates: UpdatesCustomer = Field(...)
    model_config = ConfigDict(extra="forbid")


# ---- TreeDescription ----
# class TreeDescription(BaseModel):
#     type_common: str = Field(...)
#     type_scientific: str = Field(...)
#     height_ft: str = Field(...)
#     canopy_width_ft: str = Field(...)
#     crown_shape: str = Field(...)
#     dbh_in: str = Field(...)
#     trunk_notes: str = Field(...)
#     roots: str = Field(...)
#     defects: str = Field(...)
#     general_observations: str = Field(...)
#     health_overview: str = Field(...)
#     pests_pathogens_observed: str = Field(...)
#     physiological_stress_signs: str = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class UpdatesTree(BaseModel):
#     tree_description: TreeDescription = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class ExtractorReturnTree(BaseModel):
#     updates: UpdatesTree = Field(...)
#     model_config = ConfigDict(extra="forbid")


# class RiskItem(BaseModel):
#     description: str = Field(...)
#     likelihood: str = Field(...)
#     severity: str = Field(...)
#     rationale: str = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class RisksSection(BaseModel):
#     items: List[RiskItem] = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class UpdatesRisks(BaseModel):
#     risks: RisksSection = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class ExtractorReturnRisks(BaseModel):
#     updates: UpdatesRisks = Field(...)
#     model_config = ConfigDict(extra="forbid")


# # ---- State-friendly simple models ----
# class TargetItem(BaseModel):
#     label: str = Field(default=NOT_PROVIDED)
#     damage_modes: List[str] = Field(default_factory=list)
#     proximity_note: str = Field(default=NOT_PROVIDED)
#     occupied_frequency: str = Field(default=NOT_PROVIDED)
#     narratives: List[str] = Field(default_factory=list)
#
#
# class TargetsSection(BaseModel):
#     items: List[TargetItem] = Field(default_factory=list)
#     narratives: List[str] = Field(default_factory=list)


# class RecommendationDetail(BaseModel):
#     narrative: str = Field(default=NOT_PROVIDED)
#     scope: str = Field(default=NOT_PROVIDED)
#     limitations: str = Field(default=NOT_PROVIDED)
#     notes: str = Field(default=NOT_PROVIDED)
#
#
# class RecommendationsSection(BaseModel):
#     pruning: RecommendationDetail = Field(default_factory=RecommendationDetail)
#     removal: RecommendationDetail = Field(default_factory=RecommendationDetail)
#     continued_maintenance: RecommendationDetail = Field(default_factory=RecommendationDetail)
#     narratives: List[str] = Field(default_factory=list)


# ---------- Prompt builder / base extractor ----------
def build_prompt(*, section_name: str, role_hint: str, fields: List[Tuple[str, str]],
                 list_notes: Dict[str, str] | None, user_text: str) -> str:
    field_lines = []
    for fname, fdesc in fields:
        field_lines.append(f'      "{fname}": string  # {fdesc}')
    if list_notes:
        for fname, note in list_notes.items():
            field_lines.append(f'      "{fname}": array  # {note}')
    prompt = (
        "VERBATIM-ONLY MODE.\n"
        "Output a JSON object that matches the schema exactly. All fields are REQUIRED.\n"
        "If a value appears in the user message (case-insensitive substring), COPY it verbatim.\n"
        f"Otherwise set it to the exact string: {NOT_PROVIDED}\n\n"
        f"Section: {section_name}\n"
        f"First-person policy: {role_hint}\n\n"
        "Envelope schema (keys only):\n"
        "{\n"
        '  "updates": {\n'
        f'    "{section_name}": {{\n'
        + "\n".join(field_lines)
        + "\n"
        "    }\n"
        "  }\n"
        "}\n\n"
        "Rules:\n"
        "- Do not guess or paraphrase. Do not invent values.\n"
        "- Only copy text present in the message; otherwise use the exact string above.\n"
        "- Disallow extra keys. Output only the JSON object.\n\n"
        f"User message:\n{user_text}\n"
    )
    return prompt


class BaseExtractor:
    schema_cls: Type[BaseModel]

    def build_prompt(self, user_text: str) -> str: ...

    def extract(self, user_text: str, *, temperature: float = 0.0, max_tokens: int = 300) -> Dict[str, Any]:
        model = ModelFactory.get()
        prompt = self.build_prompt(user_text)
        resp = model(prompt, self.schema_cls, temperature=temperature, max_tokens=max_tokens)
        return resp  # keep full dict (parsed/raw/tokens/model)

    def extract_dict(self, user_text: str, **kwargs) -> Dict[str, Any]:
        resp = self.extract(user_text, **kwargs)
        parsed = resp["parsed"].model_dump(exclude_none=False)
        presence = compute_presence(parsed)
        return {"result": parsed, "provided_fields": presence}


def compute_presence(parsed_envelope: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    upd = parsed_envelope.get("updates") or {}
    if not isinstance(upd, dict):
        return out
    for section, payload in upd.items():
        def walk(prefix: str, obj: Any):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(f"{prefix}.{k}" if prefix else k, v)
            elif isinstance(obj, list):
                if len(obj) > 0:
                    out.append(prefix)
            else:
                if isinstance(obj, str) and obj != NOT_PROVIDED:
                    out.append(prefix)
        if isinstance(payload, dict):
            walk(section, payload)
    return sorted(set(out))


# ---------- Concrete extractors ----------
class ArboristInfoExtractor(BaseExtractor):
    schema_cls = ExtractorReturnArborist
    def build_prompt(self, user_text: str) -> str:
        role_hint = "First-person statements refer to the ARBORIST."
        base = build_prompt(
            section_name="arborist_info",
            role_hint=role_hint,
            fields=[
                ("name", "string"),
                ("company", "string"),
                ("phone", "string"),
                ("email", "string"),
                ("license", "string"),
            ],
            list_notes=None,
            user_text=user_text,
        )
        address_block = (
            "Also include inside arborist_info the nested object exactly as:\n"
            '"address": {"street": string, "city": string, "state": string, "postal_code": string, "country": string}\n'
        )
        return base + "\n" + address_block


class CustomerInfoExtractor(BaseExtractor):
    schema_cls = ExtractorReturnCustomer
    def build_prompt(self, user_text: str) -> str:
        role_hint = "Customer values refer to the CUSTOMER (not first-person unless explicitly stated as customer)."
        base = build_prompt(
            section_name="customer_info",
            role_hint=role_hint,
            fields=[
                ("name", "string"),
                ("company", "string"),
                ("phone", "string"),
                ("email", "string"),
            ],
            list_notes=None,
            user_text=user_text,
        )
        address_block = (
            "Also include inside customer_info the nested object exactly as:\n"
            '"address": {"street": string, "city": string, "state": string, "postal_code": string, "country": string}\n'
        )
        return base + "\n" + address_block


# class TreeDescriptionExtractor(BaseExtractor):
#     schema_cls = ExtractorReturnTree
#     def build_prompt(self, user_text: str) -> str:
#         role_hint = "No first-person mapping; copy attributes verbatim."
#         return build_prompt(
#             section_name="tree_description",
#             role_hint=role_hint,
#             fields=[
#                 ("type_common", "common species name"),
#                 ("type_scientific", "scientific name"),
#                 ("height_ft", "numeric string as stated (e.g., '60', '60 ft')"),
#                 ("canopy_width_ft", "numeric string as stated"),
#                 ("crown_shape", "shape term"),
#                 ("dbh_in", "numeric string as stated (e.g., '24', '24 in')"),
#                 ("trunk_notes", "free text notes"),
#                 ("roots", "free text notes about root conditions"),
#                 ("defects", "free text notes about defects (e.g., cavities, cracks)"),
#                 ("general_observations", "other notable observations"),
#                 ("health_overview", "overall health/vigor summary"),
#                 ("pests_pathogens_observed", "diseases/pests named in text"),
#                 ("physiological_stress_signs", "stress indicators (e.g., chlorosis, dieback)"),
#             ],
#             list_notes=None,
#             user_text=user_text,
#         )
#
#
# class RisksExtractor(BaseExtractor):
#     schema_cls = ExtractorReturnRisks
#     def build_prompt(self, user_text: str) -> str:
#         role_hint = "Copy risks verbatim; 'items' is an array; [] if none."
#         base = build_prompt(
#             section_name="risks",
#             role_hint=role_hint,
#             fields=[],
#             list_notes={"items": "Array of objects with fields: description, likelihood, severity, rationale"},
#             user_text=user_text,
#         )
#         items_shape = (
#             "Each element of 'items' must be an object with exactly these string fields:\n"
#             '{ "description": string, "likelihood": string, "severity": string, "rationale": string }\n'
#         )
#         return base + "\n" + items_shape


# ---- AreaDescription extractor ----
# class AreaDescriptionStrict(BaseModel):
#     context: str = Field(...)
#     other_context_note: str = Field(...)
#     site_use: str = Field(...)
#     foot_traffic_level: str = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class UpdatesArea(BaseModel):
#     area_description: AreaDescriptionStrict = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class ExtractorReturnArea(BaseModel):
#     updates: UpdatesArea = Field(...)
#     model_config = ConfigDict(extra="forbid")
#

# class AreaDescriptionExtractor(BaseExtractor):
#     schema_cls: Type[BaseModel] = ExtractorReturnArea
#     def build_prompt(self, user_text: str) -> str:
#         return (
#             "VERBATIM-ONLY MODE.\n"
#             "You must output a JSON object matching the schema exactly. All fields are REQUIRED.\n"
#             "Rules:\n"
#             f"  • If a value appears in the user message (case-insensitive substring), COPY it verbatim.\n"
#             f"  • Otherwise, set the field to the exact string: {NOT_PROVIDED}\n"
#             "  • Do not guess or paraphrase. Do not invent values.\n"
#             "  • Disallow extra keys; output only the JSON object.\n\n"
#             "Section: area_description\n"
#             "First-person policy: no special mapping; copy values that appear.\n\n"
#             "Schema:\n"
#             "{\n"
#             "  \"updates\": {\n"
#             "    \"area_description\": {\n"
#             "      \"context\": string,\n"
#             "      \"other_context_note\": string,\n"
#             "      \"site_use\": string,\n"
#             "      \"foot_traffic_level\": string\n"
#             "    }\n"
#             "  }\n"
#             "}\n\n"
#             f"User message:\n{user_text}\n"
#         )

# ---- Recommendations extractor ----
# class RecommendationDetailX(BaseModel):
#     narrative: str = Field(...)
#     scope: str = Field(...)
#     limitations: str = Field(...)
#     notes: str = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class RecommendationsSectionX(BaseModel):
#     pruning: RecommendationDetailX = Field(...)
#     removal: RecommendationDetailX = Field(...)
#     continued_maintenance: RecommendationDetailX = Field(...)
#     narratives: List[str] = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class UpdatesRecommendations(BaseModel):
#     recommendations: RecommendationsSectionX = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
#
# class ExtractorReturnRecommendations(BaseModel):
#     updates: UpdatesRecommendations = Field(...)
#     model_config = ConfigDict(extra="forbid")


# class RecommendationsExtractor(BaseExtractor):
#     schema_cls = ExtractorReturnRecommendations
#     def build_prompt(self, user_text: str) -> str:
#         return (
#             "VERBATIM-ONLY MODE.\n"
#             "Output a JSON object that matches the schema exactly. All fields are REQUIRED.\n"
#             f"If a value appears in the user message (case-insensitive substring), COPY it verbatim.\n"
#             f"Otherwise set it to the exact string: {NOT_PROVIDED}\n\n"
#             "Section: recommendations\n"
#             "{\n"
#             '  "updates": {\n'
#             '    "recommendations": {\n'
#             '      "pruning": { "narrative": string, "scope": string, "limitations": string, "notes": string },\n'
#             '      "removal": { "narrative": string, "scope": string, "limitations": string, "notes": string },\n'
#             '      "continued_maintenance": { "narrative": string, "scope": string, "limitations": string, "notes": string },\n'
#             '      "narratives": array\n'
#             "    }\n"
#             "  }\n"
#             "}\n\n"
#             "Rules: Do not guess; no extra keys; 'narratives' is an array.\n\n"
#             f"User message:\n{user_text}\n"
#         )
#
#     def extract_dict(self, user_text: str, **kwargs) -> Dict[str, Any]:
#         resp = self.extract(user_text, **kwargs)
#         parsed = resp["parsed"].model_dump(exclude_none=False)
#         presence = compute_presence(parsed)
#         return {"result": parsed, "provided_fields": presence}
# ---- Targets extractor ----
class TargetItemStrict(BaseModel):
    label: str = Field(...)
    damage_modes: List[str] = Field(...)
    proximity_note: str = Field(...)
    occupied_frequency: str = Field(...)
    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


class TargetsSectionStrict(BaseModel):
    items: List[TargetItemStrict] = Field(...)
    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


class UpdatesTargets(BaseModel):
    targets: TargetsSectionStrict = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnTargets(BaseModel):
    updates: UpdatesTargets = Field(...)
    model_config = ConfigDict(extra="forbid")


class TargetExtractor(BaseExtractor):
    schema_cls = ExtractorReturnTargets
    def build_prompt(self, user_text: str) -> str:
        base = build_prompt(
            section_name="targets",
            role_hint="No first-person mapping; copy values that appear verbatim.",
            fields=[],
            list_notes={
                "items": "Array of target objects; [] if none",
                "narratives": "Array of section-level notes; [] if none",
            },
            user_text=user_text,
        )
        item_shape = (
            "Each element of 'items' MUST be an object with exactly these keys and types:\n"
            '{ "label": string, "damage_modes": array, "proximity_note": string, '
            '"occupied_frequency": string, "narratives": array }\n'
            "- For arrays, output [] if none.\n"
            f"- If a scalar value is not present in the user message, use the exact string {NOT_PROVIDED}.\n"
        )
        arrays_detail = (
            "Array element rules:\n"
            "- damage_modes: each entry is a string from the user text; do not synthesize.\n"
            "- narratives: each entry is a verbatim snippet from the user text; [] if none.\n"
        )
        return base + "\n" + item_shape + "\n" + arrays_detail



# ---- AreaDescription extractor ----
# !!! New !!!
# The state expects arrays for `context`, `other_context_note`, `site_use`, and `narratives`.
# The previous schema used `str` for the first three and omitted `narratives`, which
# would cause type mismatches during ReportState.merge (string vs List[str]).
# Commenting out the old schema and replacing it with list-typed fields.

# class AreaDescriptionStrict(BaseModel):
#     # ❌ MISMATCH: state expects List[str] for these three fields.
#     context: str = Field(...)
#     other_context_note: str = Field(...)
#     site_use: str = Field(...)
#     # ✅ This one is scalar in state; keep as str.
#     foot_traffic_level: str = Field(...)
#     model_config = ConfigDict(extra="forbid")

# from typing import List  # ensure this import is present at top of file

class AreaDescriptionStrict(BaseModel):
    # ✅ Match ReportState: arrays of strings; extractor must return [] when none.
    context: List[str] = Field(...)
    other_context_note: List[str] = Field(...)
    site_use: List[str] = Field(...)
    # ✅ Scalar string; use exact NOT_PROVIDED when absent.
    foot_traffic_level: str = Field(...)
    # ✅ Present in ReportState; include here to keep schemas aligned.
    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


# No shape changes here; this remains a wrapper around the section payload.
# Kept for clarity, but noting the reason to avoid accidental edits.
class UpdatesArea(BaseModel):
    area_description: AreaDescriptionStrict = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnArea(BaseModel):
    updates: UpdatesArea = Field(...)
    model_config = ConfigDict(extra="forbid")


class AreaDescriptionExtractor(BaseExtractor):
    schema_cls: Type[BaseModel] = ExtractorReturnArea

    def build_prompt(self, user_text: str) -> str:
        # Update the schema description to reflect arrays for context/other_context_note/site_use/narratives,
        # and the scalar for foot_traffic_level. Arrays must be [] when none; scalars use NOT_PROVIDED.
        return (
            "VERBATIM-ONLY MODE.\n"
            "You must output a JSON object matching the schema exactly. All fields are REQUIRED.\n"
            "Rules:\n"
            f"  • If a value appears in the user message (case-insensitive substring), COPY it verbatim.\n"
            f"  • Otherwise, set scalar fields to the exact string: {NOT_PROVIDED}\n"
            "  • For arrays, output [] when no values are present (do NOT use null or strings).\n"
            "  • Do not guess or paraphrase. Do not invent values.\n"
            "  • Disallow extra keys; output only the JSON object.\n\n"
            "Section: area_description\n"
            "First-person policy: no special mapping; copy values that appear.\n\n"
            "Schema:\n"
            "{\n"
            "  \"updates\": {\n"
            "    \"area_description\": {\n"
            "      \"context\": array,\n"
            "      \"other_context_note\": array,\n"
            "      \"site_use\": array,\n"
            "      \"foot_traffic_level\": string,\n"
            "      \"narratives\": array\n"
            "    }\n"
            "  }\n"
            "}\n\n"
            f"User message:\n{user_text}\n"
        )

# ---- TreeDescription extractor ----

# PREVIOUS EXTRACTOR SCHEMA (MISMATCHED):
# - These fields were all strings, but state expects many of them to be List[str].
# - Keeping here commented for traceability.
#
# class TreeDescription(BaseModel):
#     type_common: str = Field(...)
#     type_scientific: str = Field(...)
#     height_ft: str = Field(...)
#     canopy_width_ft: str = Field(...)
#     crown_shape: str = Field(...)
#     dbh_in: str = Field(...)
#     trunk_notes: str = Field(...)                      # ❌ state expects List[str]
#     roots: str = Field(...)                            # ❌ List[str]
#     defects: str = Field(...)                          # ❌ List[str]
#     general_observations: str = Field(...)             # ❌ List[str]
#     health_overview: str = Field(...)                  # ❌ List[str]
#     pests_pathogens_observed: str = Field(...)         # ❌ List[str]
#     physiological_stress_signs: str = Field(...)       # ❌ List[str]
#     narratives: str = Field(...)                       # ❌ List[str]
#     model_config = ConfigDict(extra="forbid")

from typing import List  # ensure present at top of file

class TreeDescription(BaseModel):
    # ✅ Scalars (match state): use exact NOT_PROVIDED when absent.
    type_common: str = Field(...)
    type_scientific: str = Field(...)
    height_ft: str = Field(...)        # numeric-as-string
    canopy_width_ft: str = Field(...)  # numeric-as-string
    crown_shape: str = Field(...)
    dbh_in: str = Field(...)           # numeric-as-string

    # ✅ Lists (match state): extractor must output [] when none.
    trunk_notes: List[str] = Field(...)
    roots: List[str] = Field(...)
    defects: List[str] = Field(...)
    general_observations: List[str] = Field(...)

    health_overview: List[str] = Field(...)
    pests_pathogens_observed: List[str] = Field(...)
    physiological_stress_signs: List[str] = Field(...)

    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


# Wrapper types remain the same; updated to reference the corrected schema.
class UpdatesTree(BaseModel):
    tree_description: TreeDescription = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnTree(BaseModel):
    updates: UpdatesTree = Field(...)
    model_config = ConfigDict(extra="forbid")


class TreeDescriptionExtractor(BaseExtractor):
    schema_cls = ExtractorReturnTree

    def build_prompt(self, user_text: str) -> str:
        # Update prompt to:
        # - Keep scalars in 'fields' (strings with NOT_PROVIDED fallback).
        # - Declare list fields in 'list_notes' so the LLM returns arrays (or [] when none).
        return build_prompt(
            section_name="tree_description",
            role_hint="No first-person mapping; copy attributes verbatim.",
            fields=[
                ("type_common", "common species name"),
                ("type_scientific", "scientific name"),
                ("height_ft", "numeric string as stated (e.g. '60', '60 ft')"),
                ("canopy_width_ft", "numeric string as stated"),
                ("crown_shape", "shape term"),
                ("dbh_in", "numeric string as stated (e.g. '24', '24 in')"),
            ],
            list_notes={
                "trunk_notes": "Array of verbatim trunk notes; [] if none",
                "roots": "Array of root condition notes; [] if none",
                "defects": "Array of defect phrases (e.g. cavities, cracks); [] if none",
                "general_observations": "Array of other observations; [] if none",
                "health_overview": "Array of health/vigor snippets; [] if none",
                "pests_pathogens_observed": "Array of named pests/diseases; [] if none",
                "physiological_stress_signs": "Array of stress indicators; [] if none",
                "narratives": "Array of section-level notes; [] if none",
            },
            user_text=user_text,
        )
# ---- Targets extractor ----
# Note: This schema already matches ReportState:
# - Item-level scalars use NOT_PROVIDED when absent.
# - Item-level arrays and section-level arrays return [] (never None / "Not provided").

class TargetItemStrict(BaseModel):
    label: str = Field(...)
    damage_modes: List[str] = Field(...)
    proximity_note: str = Field(...)
    occupied_frequency: str = Field(...)
    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


class TargetsSectionStrict(BaseModel):
    items: List[TargetItemStrict] = Field(...)
    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


class UpdatesTargets(BaseModel):
    targets: TargetsSectionStrict = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnTargets(BaseModel):
    updates: UpdatesTargets = Field(...)
    model_config = ConfigDict(extra="forbid")


class TargetExtractor(BaseExtractor):
    schema_cls = ExtractorReturnTargets

    def build_prompt(self, user_text: str) -> str:
        base = build_prompt(
            section_name="targets",
            role_hint="No first-person mapping; copy values that appear verbatim.",
            fields=[],  # all scalars live inside each item; see item_shape below
            list_notes={
                "items": "Array of target objects; [] if none",
                "narratives": "Array of section-level notes; [] if none",
            },
            user_text=user_text,
        )
        item_shape = (
            "Each element of 'items' MUST be an object with exactly these keys and types:\n"
            '{ "label": string, "damage_modes": array, "proximity_note": string, '
            '"occupied_frequency": string, "narratives": array }\n'
            "- For arrays, output [] if none.\n"
            f"- If a scalar value is not present in the user message, use the exact string {NOT_PROVIDED}.\n"
        )
        arrays_detail = (
            "Array element rules:\n"
            "- damage_modes: each entry is a string from the user text; do not synthesize.\n"
            "- narratives: each entry is a verbatim snippet from the user text; [] if none.\n"
        )
        return base + "\n" + item_shape + "\n" + arrays_detail

# ---- Risks extractor ----

# Previous schema (mismatched): item lacked `narratives`, section lacked top-level `narratives`.
# Keeping here commented for traceability.
#
# class RiskItem(BaseModel):
#     description: str = Field(...)
#     likelihood: str = Field(...)
#     severity: str = Field(...)
#     rationale: str = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
# class RisksSection(BaseModel):
#     items: List[RiskItem] = Field(...)
#     model_config = ConfigDict(extra="forbid")

# from typing import List  # ensure present near top of file

class RiskItemStrict(BaseModel):
    # ✅ Scalars: use exact NOT_PROVIDED when absent (enforced by prompt).
    description: str = Field(...)
    likelihood: str = Field(...)
    severity: str = Field(...)
    rationale: str = Field(...)
    # ✅ Match ReportState: item-level narratives is an array; [] when none.
    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


class RisksSectionStrict(BaseModel):
    items: List[RiskItemStrict] = Field(...)
    # ✅ Match ReportState: section-level narratives; [] when none.
    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


class UpdatesRisks(BaseModel):
    risks: RisksSectionStrict = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnRisks(BaseModel):
    updates: UpdatesRisks = Field(...)
    model_config = ConfigDict(extra="forbid")


class RisksExtractor(BaseExtractor):
    schema_cls = ExtractorReturnRisks

    def build_prompt(self, user_text: str) -> str:
        # Keep scalars implicit within each item; declare arrays in list_notes
        # so the LLM returns [] when none. Scalars use NOT_PROVIDED.
        base = build_prompt(
            section_name="risks",
            role_hint="Copy risks verbatim; arrays are [] when none.",
            fields=[],  # per-item scalars are specified in item_shape below
            list_notes={
                "items": "Array of risk objects; [] if none",
                "narratives": "Array of section-level notes; [] if none",
            },
            user_text=user_text,
        )
        item_shape = (
            "Each element of 'items' MUST be an object with exactly these keys and types:\n"
            '{ "description": string, "likelihood": string, "severity": string, '
            '"rationale": string, "narratives": array }\n'
            "- For arrays, output [] if none.\n"
            f"- For missing scalars, use the exact string {NOT_PROVIDED}.\n"
        )
        arrays_detail = (
            "Array element rules:\n"
            "- narratives: each entry is a verbatim snippet from the user text; [] if none.\n"
        )
        return base + "\n" + item_shape + "\n" + arrays_detail

# ---- Recommendations extractor ----

# Previous mismatch examples (kept for traceability):
# - Item-level fields correct as scalars, but section-level `narratives` missing
#   OR modeled as a string.
#
# class RecommendationDetail(BaseModel):
#     narrative: str = Field(...)
#     scope: str = Field(...)
#     limitations: str = Field(...)
#     notes: str = Field(...)
#     model_config = ConfigDict(extra="forbid")
#
# class RecommendationsSection(BaseModel):
#     pruning: RecommendationDetail = Field(...)
#     removal: RecommendationDetail = Field(...)
#     continued_maintenance: RecommendationDetail = Field(...)
#     # ❌ MISMATCH: `narratives` missing or typed as str
#     # narratives: str = Field(...)
#     model_config = ConfigDict(extra="forbid")

# from typing import List  # ensure present near top of file

class RecommendationDetailStrict(BaseModel):
    # ✅ All scalars; use exact NOT_PROVIDED when not present in user text.
    narrative: str = Field(...)
    scope: str = Field(...)
    limitations: str = Field(...)
    notes: str = Field(...)
    model_config = ConfigDict(extra="forbid")


class RecommendationsSectionStrict(BaseModel):
    pruning: RecommendationDetailStrict = Field(...)
    removal: RecommendationDetailStrict = Field(...)
    continued_maintenance: RecommendationDetailStrict = Field(...)
    # ✅ Match state: section-level narratives is a list; [] when none.
    narratives: List[str] = Field(...)
    model_config = ConfigDict(extra="forbid")


class UpdatesRecommendations(BaseModel):
    recommendations: RecommendationsSectionStrict = Field(...)
    model_config = ConfigDict(extra="forbid")


class ExtractorReturnRecommendations(BaseModel):
    updates: UpdatesRecommendations = Field(...)
    model_config = ConfigDict(extra="forbid")


class RecommendationsExtractor(BaseExtractor):
    schema_cls = ExtractorReturnRecommendations

    def build_prompt(self, user_text: str) -> str:
        # Scalars get NOT_PROVIDED when absent; arrays must be [] (never null or strings).
        base = build_prompt(
            section_name="recommendations",
            role_hint="Copy recommendations verbatim; do not infer.",
            fields=[],  # all scalars live inside the three detail objects; see object_shape below
            list_notes={
                "narratives": "Array of section-level notes; [] if none",
            },
            user_text=user_text,
        )
        object_shape = (
            "Each of 'pruning', 'removal', and 'continued_maintenance' MUST be an object "
            "with exactly these keys (all strings):\n"
            f'{{ "narrative": string, "scope": string, "limitations": string, "notes": string }}\n'
            f"- For any missing scalar value, use the exact string {NOT_PROVIDED}.\n"
        )
        arrays_detail = (
            "Array rules:\n"
            "- recommendations.narratives: array of verbatim snippets; [] if none.\n"
        )
        return base + "\n" + object_shape + "\n" + arrays_detail

# Canonical envelope returned to Coordinator
class ServiceRouteEnvelope(BaseModel):
    """
    Canonical envelope for the service router backstop.

    NOTE:
      - 'result' is the flattened subset the Coordinator reads.
      - 'tokens' and 'model' are promoted for token accounting/telemetry.
    """
    result: ServiceRouteOutput = Field(...)
    tokens: TokenDict = Field(default_factory=lambda: {"in": 0, "out": 0})
    model: str = Field(default="outlines-structured")
    model_config = ConfigDict(extra="forbid")


def _router_prompt(text: str) -> str:
    """
    Build a concise classification prompt for Outlines structured call.
    Keep deterministic, few clear rules, and small few-shots.
    """
    return (
        "You classify a single user request into a service and optional section.\n"
        "Output MUST match the schema exactly. Do not add fields.\n\n"
        "Services:\n"
        "  - SECTION_SUMMARY  (summarize one section)\n"
        "  - OUTLINE          (outline one section)\n"
        "  - MAKE_REPORT_DRAFT (write whole-report draft; section MUST be null)\n"
        "  - MAKE_CORRECTION  (apply a correction to one section)\n"
        "  - CLARIFY          (reserved; do not emit; use NONE instead for ambiguity)\n"
        "  - NONE             (insufficient signal or mixed/ambiguous intent)\n\n"
        "Sections (when applicable):\n"
        "  area_description | tree_description | targets | risks | recommendations\n\n"
        "Rules:\n"
        "  • 'outline' → OUTLINE (+section if stated, else null)\n"
        "  • 'summary/recap/overview/tl;dr' → SECTION_SUMMARY (+section if stated, else null)\n"
        "  • 'draft/full report/write the report' → MAKE_REPORT_DRAFT (section MUST be null)\n"
        "  • 'fix/correct/change/update/amend/revise' → MAKE_CORRECTION (+section if stated)\n"
        "  • If ambiguous or mixed without a clear priority → NONE with low confidence\n"
        "  • Never invent non-canonical sections.\n"
        "  • Confidence: 0.0–1.0 (higher when explicit).\n\n"
        "Few-shots (conceptual):\n"
        "  Input: 'Summarize the risks'\n"
        "  → service=SECTION_SUMMARY, section=risks, confidence≈0.85\n"
        "  Input: 'Outline tree description'\n"
        "  → service=OUTLINE, section=tree_description, confidence≈0.90\n"
        "  Input: 'Make a full report draft'\n"
        "  → service=MAKE_REPORT_DRAFT, section=null, confidence≈0.90\n"
        "  Input: 'Overview please'\n"
        "  → service=NONE, section=null, confidence≈0.40\n"
        "  Input: 'Fix DBH to 30 in'\n"
        "  → service=MAKE_CORRECTION, section=tree_description, confidence≈0.75\n\n"
        f"User text:\n{text}\n"
        "Return the JSON object matching the schema exactly."
    )


class ServiceRouterExtractor(BaseExtractor):
    """
    LLM-backstop router using Outlines structured calling via ModelFactory.
    This is only called when deterministic routing returned NONE.

    Returns (envelope shape expected by Coordinator):
        {
          "result": {"service": ..., "section": ..., "confidence": ...},
          "tokens": {"in": int, "out": int},
          "model": "<model-name>"
        }
    """

    schema_cls = ServiceRouteEnvelope

    def extract_dict(
        self,
        text: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> Dict[str, Any]:
        prompt = _router_prompt(text or "")
        try:
            sm = ModelFactory.get()  # StructuredModel singleton
            call = sm(prompt, output_type=ServiceRouteOutput, temperature=float(temperature))
            parsed: ServiceRouteOutput = call["parsed"]
            tokens: TokenDict = call.get("tokens", {"in": 0, "out": 0})
            model_name: str = call.get("model", "outlines-structured")

            # Coordinator expects 'result' to contain only core routing fields.
            result = {
                "service": parsed.service,
                "section": parsed.section,
                "confidence": float(parsed.confidence),
            }
            return {"result": result, "tokens": tokens, "model": model_name}

        except SystemExit:
            # ModelFactory raised due to missing API key; safe fallback so Coordinator can CLARIFY
            return {
                "result": {"service": "NONE", "section": None, "confidence": 0.0},
                "tokens": {"in": 0, "out": 0},
                "model": "router-unavailable",
            }
        except Exception:
            # Any structured-call/validation error → safe fallback
            return {
                "result": {"service": "NONE", "section": None, "confidence": 0.0},
                "tokens": {"in": 0, "out": 0},
                "model": "router-error",
            }
