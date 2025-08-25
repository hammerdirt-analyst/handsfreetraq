"""
arborist-agent/models.py
author: roger erismann
"""

# Reusable extractors for arborist_agent — Outlines 1.2.3 + OpenAI v1
from __future__ import annotations

import os
import json
from functools import lru_cache
from typing import Dict, List, Tuple, Type, Any

import outlines
import openai
from pydantic import BaseModel, Field, ConfigDict

NOT_PROVIDED = "Not provided"

class ModelFactory:
    @staticmethod
    @lru_cache(maxsize=1)
    def get():
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("ERROR: set OPENAI_API_KEY")
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        client = openai.OpenAI()
        return outlines.from_openai(client, model_name)

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

# ---- TreeDescription: +roots, +defects, +general_observations ----
class TreeDescription(BaseModel):
    # Identification & measurements
    type_common: str = Field(...)
    type_scientific: str = Field(...)
    height_ft: str = Field(..., description="Numeric string or 'Not provided'")
    canopy_width_ft: str = Field(..., description="Numeric string or 'Not provided'")
    crown_shape: str = Field(...)
    dbh_in: str = Field(..., description="Numeric string or 'Not provided'")

    # Observations
    trunk_notes: str = Field(...)
    roots: str = Field(...)
    defects: str = Field(...)
    general_observations: str = Field(...)

    # ---- Health Assessment (new) ----
    health_overview: str = Field(...)
    pests_pathogens_observed: str = Field(...)
    physiological_stress_signs: str = Field(...)

    model_config = ConfigDict(extra="forbid")

class UpdatesTree(BaseModel):
    tree_description: TreeDescription = Field(...)
    model_config = ConfigDict(extra="forbid")

class ExtractorReturnTree(BaseModel):
    updates: UpdatesTree = Field(...)
    model_config = ConfigDict(extra="forbid")


class RiskItem(BaseModel):
    description: str = Field(...)
    likelihood: str = Field(...)
    severity: str = Field(...)
    rationale: str = Field(...)
    model_config = ConfigDict(extra="forbid")

class RisksSection(BaseModel):
    items: List[RiskItem] = Field(...)
    model_config = ConfigDict(extra="forbid")

class UpdatesRisks(BaseModel):
    risks: RisksSection = Field(...)
    model_config = ConfigDict(extra="forbid")

class ExtractorReturnRisks(BaseModel):
    updates: UpdatesRisks = Field(...)
    model_config = ConfigDict(extra="forbid")

# ---- State-friendly simple models for other sections (used by ReportState) ----

class TargetItem(BaseModel):
    label: str = Field(default=NOT_PROVIDED)
    damage_modes: List[str] = Field(default_factory=list)
    proximity_note: str = Field(default=NOT_PROVIDED)
    occupied_frequency: str = Field(default=NOT_PROVIDED)
    narratives: List[str] = Field(default_factory=list)

class TargetsSection(BaseModel):
    items: List[TargetItem] = Field(default_factory=list)
    narratives: List[str] = Field(default_factory=list)

class RecommendationDetail(BaseModel):
    narrative: str = Field(default=NOT_PROVIDED)
    scope: str = Field(default=NOT_PROVIDED)
    limitations: str = Field(default=NOT_PROVIDED)
    notes: str = Field(default=NOT_PROVIDED)

class RecommendationsSection(BaseModel):
    pruning: RecommendationDetail = Field(default_factory=RecommendationDetail)
    removal: RecommendationDetail = Field(default_factory=RecommendationDetail)
    continued_maintenance: RecommendationDetail = Field(default_factory=RecommendationDetail)
    narratives: List[str] = Field(default_factory=list)

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
    def extract(self, user_text: str, *, temperature: float = 0.0, max_tokens: int = 300) -> BaseModel:
        model = ModelFactory.get()
        prompt = self.build_prompt(user_text)
        raw = model(prompt, self.schema_cls, temperature=temperature, max_tokens=max_tokens)
        return self.schema_cls.model_validate_json(raw)
    def extract_dict(self, user_text: str, **kwargs) -> Dict[str, Any]:
        parsed = self.extract(user_text, **kwargs).model_dump()
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

class TreeDescriptionExtractor(BaseExtractor):
    schema_cls = ExtractorReturnTree
    def build_prompt(self, user_text: str) -> str:
        role_hint = "No first-person mapping; copy attributes verbatim."
        return build_prompt(
            section_name="tree_description",
            role_hint=role_hint,
            fields=[
                ("type_common", "common species name"),
                ("type_scientific", "scientific name"),
                ("height_ft", "numeric string as stated (e.g., '60', '60 ft')"),
                ("canopy_width_ft", "numeric string as stated"),
                ("crown_shape", "shape term"),
                ("dbh_in", "numeric string as stated (e.g., '24', '24 in')"),
                ("trunk_notes", "free text notes"),
                ("roots", "free text notes about root conditions"),
                ("defects", "free text notes about defects (e.g., cavities, cracks)"),
                ("general_observations", "other notable observations"),
                ("health_overview", "overall health/vigor summary"),
                ("pests_pathogens_observed", "diseases/pests named in text"),
                ("physiological_stress_signs", "stress indicators (e.g., chlorosis, dieback)"),
            ],
            list_notes=None,
            user_text=user_text,
        )

class RisksExtractor(BaseExtractor):
    schema_cls = ExtractorReturnRisks
    def build_prompt(self, user_text: str) -> str:
        role_hint = "Copy risks verbatim; 'items' is an array; [] if none."
        base = build_prompt(
            section_name="risks",
            role_hint=role_hint,
            fields=[],
            list_notes={"items": "Array of objects with fields: description, likelihood, severity, rationale"},
            user_text=user_text,
        )
        items_shape = (
            "Each element of 'items' must be an object with exactly these string fields:\n"
            '{ "description": string, "likelihood": string, "severity": string, "rationale": string }\n'
        )
        return base + "\n" + items_shape

# ---- AreaDescription extractor (strict, verbatim) ---------------------------

class AreaDescriptionStrict(BaseModel):
    context: str = Field(..., description="Area context (e.g., urban/suburban/rural) or 'Not provided'")
    other_context_note: str = Field(..., description="Free text note or 'Not provided'")
    site_use: str = Field(..., description="Primary site use (e.g., playground, parking lot) or 'Not provided'")
    foot_traffic_level: str = Field(..., description="Foot traffic level (e.g., low/medium/high) or 'Not provided'")
    model_config = ConfigDict(extra="forbid")

class UpdatesArea(BaseModel):
    area_description: AreaDescriptionStrict = Field(...)
    model_config = ConfigDict(extra="forbid")

class ExtractorReturnArea(BaseModel):
    updates: UpdatesArea = Field(...)
    model_config = ConfigDict(extra="forbid")

class AreaDescriptionExtractor(BaseExtractor):
    """
    Produces:
    {
      "updates": {
        "area_description": {
          "context": string,
          "other_context_note": string,
          "site_use": string,
          "foot_traffic_level": string
        }
      }
    }
    Notes:
      - We do NOT extract 'narratives' here; that stays state-only.
      - Verbatim-only policy; unknowns => exact string Not provided.
    """
    schema_cls: Type[BaseModel] = ExtractorReturnArea

    def build_prompt(self, user_text: str) -> str:
        return (
            "VERBATIM-ONLY MODE.\n"
            "You must output a JSON object matching the schema exactly. All fields are REQUIRED.\n"
            "Rules:\n"
            f"  • If a value appears in the user message (case-insensitive substring), COPY it verbatim.\n"
            f"  • Otherwise, set the field to the exact string: {NOT_PROVIDED}\n"
            "  • Do not guess or paraphrase. Do not invent values.\n"
            "  • Disallow extra keys; output only the JSON object.\n\n"
            "Section: area_description\n"
            "First-person policy: no special mapping; copy values that appear.\n\n"
            "Schema:\n"
            "{\n"
            "  \"updates\": {\n"
            "    \"area_description\": {\n"
            "      \"context\": string,\n"
            "      \"other_context_note\": string,\n"
            "      \"site_use\": string,\n"
            "      \"foot_traffic_level\": string\n"
            "    }\n"
            "  }\n"
            "}\n\n"
            f"User message:\n{user_text}\n"
        )

# ---- Targets extractor (strict, verbatim, arrays) ---------------------------

class TargetItemStrict(BaseModel):
    label: str = Field(..., description="Target label (e.g., building, playground) or 'Not provided'")
    damage_modes: List[str] = Field(..., description="Array of damage mode strings; [] if none")
    proximity_note: str = Field(..., description="Free text proximity note or 'Not provided'")
    occupied_frequency: str = Field(..., description="e.g., low/medium/high/daily or 'Not provided'")
    narratives: List[str] = Field(..., description="Additional notes; [] if none")
    model_config = ConfigDict(extra="forbid")

class TargetsSectionStrict(BaseModel):
    items: List[TargetItemStrict] = Field(..., description="Array of targets; [] if none")
    narratives: List[str] = Field(..., description="Section-level notes; [] if none")
    model_config = ConfigDict(extra="forbid")

class UpdatesTargets(BaseModel):
    targets: TargetsSectionStrict = Field(...)
    model_config = ConfigDict(extra="forbid")

class ExtractorReturnTargets(BaseModel):
    updates: UpdatesTargets = Field(...)
    model_config = ConfigDict(extra="forbid")

class TargetExtractor(BaseExtractor):
    """
    Produces:
    {
      "updates": {
        "targets": {
          "items": [
            {
              "label": string,
              "damage_modes": [string, ...],
              "proximity_note": string,
              "occupied_frequency": string,
              "narratives": [string, ...]
            },
            ...
          ],
          "narratives": [string, ...]
        }
      }
    }
    Verbatim-only. Arrays must be present; [] if none.
    """
    schema_cls = ExtractorReturnTargets

    def build_prompt(self, user_text: str) -> str:
        # Use base helper with array notes, then specify item object shape.
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

# ---- Recommendations extractor (strict, verbatim) --------------------------

class RecommendationDetailX(BaseModel):
    narrative: str = Field(...)
    scope: str = Field(...)
    limitations: str = Field(...)
    notes: str = Field(...)
    model_config = ConfigDict(extra="forbid")

class RecommendationsSectionX(BaseModel):
    pruning: RecommendationDetailX = Field(...)
    removal: RecommendationDetailX = Field(...)
    continued_maintenance: RecommendationDetailX = Field(...)
    narratives: List[str] = Field(..., description="[] if none")
    model_config = ConfigDict(extra="forbid")

class UpdatesRecommendations(BaseModel):
    recommendations: RecommendationsSectionX = Field(...)
    model_config = ConfigDict(extra="forbid")

class ExtractorReturnRecommendations(BaseModel):
    updates: UpdatesRecommendations = Field(...)
    model_config = ConfigDict(extra="forbid")

class RecommendationsExtractor(BaseExtractor):
    schema_cls = ExtractorReturnRecommendations
    def build_prompt(self, user_text: str) -> str:
        return (
            "VERBATIM-ONLY MODE.\n"
            "Output a JSON object that matches the schema exactly. All fields are REQUIRED.\n"
            f"If a value appears in the user message (case-insensitive substring), COPY it verbatim.\n"
            f"Otherwise set it to the exact string: {NOT_PROVIDED}\n\n"
            "Section: recommendations\n"
            "{\n"
            '  "updates": {\n'
            '    "recommendations": {\n'
            '      "pruning": { "narrative": string, "scope": string, "limitations": string, "notes": string },\n'
            '      "removal": { "narrative": string, "scope": string, "limitations": string, "notes": string },\n'
            '      "continued_maintenance": { "narrative": string, "scope": string, "limitations": string, "notes": string },\n'
            '      "narratives": array  # additional verbatim notes; [] if none\n'
            "    }\n"
            "  }\n"
            "}\n\n"
            "Rules: Do not guess; no extra keys; 'narratives' is an array.\n\n"
            f"User message:\n{user_text}\n"
        )

    def extract_dict(self, user_text: str, **kwargs) -> Dict[str, Any]:
        parsed = self.extract(user_text, **kwargs).model_dump()
        presence = compute_presence(parsed)  # uses list non-empty + NOT_PROVIDED rules
        return {"result": parsed, "provided_fields": presence}
