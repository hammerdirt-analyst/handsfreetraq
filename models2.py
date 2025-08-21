# section_extractors.py
# Reusable extractors for arborist_agent — Outlines 1.2.3 + OpenAI v1
from __future__ import annotations

import os
import json
from functools import lru_cache
from typing import Dict, List, Tuple, Type, Any

import outlines
import openai
from pydantic import BaseModel, Field, ConfigDict

# ======================
# Shared constants
# ======================
NOT_PROVIDED = "Not provided"


# ======================
# Model wiring (Outlines)
# ======================
class ModelFactory:
    @staticmethod
    @lru_cache(maxsize=1)
    def get():
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("ERROR: set OPENAI_API_KEY")
        model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        client = openai.OpenAI()
        return outlines.from_openai(client, model_name)


# ======================
# STRICT schemas (LLM-facing)
# - all required; extra=forbid
# - Envelope: {"updates": {"<section>": {...}}}
# ======================

class Address(BaseModel):
    street: str = Field(..., description="Street line or 'Not provided'")
    city: str = Field(..., description="City or 'Not provided'")
    state: str = Field(..., description="State or 'Not provided'")
    postal_code: str = Field(..., description="ZIP or 'Not provided'")
    country: str = Field(..., description="Country or 'Not provided'")
    model_config = ConfigDict(extra="forbid")


# Arborist
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


# Customer
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


# Tree (numeric-as-string policy)
class TreeDescription(BaseModel):
    type_common: str = Field(...)
    type_scientific: str = Field(...)
    height_ft: str = Field(..., description="Numeric string or 'Not provided'")
    canopy_width_ft: str = Field(..., description="Numeric string or 'Not provided'")
    crown_shape: str = Field(...)
    dbh_in: str = Field(..., description="Numeric string or 'Not provided'")
    trunk_notes: str = Field(...)
    model_config = ConfigDict(extra="forbid")

class UpdatesTree(BaseModel):
    tree_description: TreeDescription = Field(...)
    model_config = ConfigDict(extra="forbid")

class ExtractorReturnTree(BaseModel):
    updates: UpdatesTree = Field(...)
    model_config = ConfigDict(extra="forbid")


# Risks with list
class RiskItem(BaseModel):
    description: str = Field(...)
    likelihood: str = Field(...)
    severity: str = Field(...)
    rationale: str = Field(...)
    model_config = ConfigDict(extra="forbid")

class RisksSection(BaseModel):
    items: List[RiskItem] = Field(..., description="[] if none")
    model_config = ConfigDict(extra="forbid")

class UpdatesRisks(BaseModel):
    risks: RisksSection = Field(...)
    model_config = ConfigDict(extra="forbid")

class ExtractorReturnRisks(BaseModel):
    updates: UpdatesRisks = Field(...)
    model_config = ConfigDict(extra="forbid")


# ======================
# Prompt builder (shared)
# ======================
def build_prompt(
    *,
    section_name: str,
    role_hint: str,
    fields: List[Tuple[str, str]],
    list_notes: Dict[str, str] | None,
    user_text: str,
) -> str:
    """
    fields: [(name, short_desc)], string fields only (lists described via list_notes)
    list_notes: {"field_name": "explain array behavior"} for list fields
    """
    field_lines = []
    for fname, fdesc in fields:
        field_lines.append(f'      "{fname}": string  # {fdesc}')
    if list_notes:
        for fname, note in list_notes.items():
            field_lines.append(f'      "{fname}": array  # {note}')

    rules_extra = []
    if list_notes:
        rules_extra.append(
            "- For list fields, return a JSON array of verbatim strings; if none, return []."
        )

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
        "- Disallow extra keys. Output only the JSON object.\n"
        + ("\n".join(rules_extra) + "\n" if rules_extra else "")
        + "\n"
        f"User message:\n{user_text}\n"
    )
    return prompt


# ======================
# Base extractor + presence report
# ======================
class BaseExtractor:
    schema_cls: Type[BaseModel]

    def build_prompt(self, user_text: str) -> str:  # override
        raise NotImplementedError

    def extract(self, user_text: str, *, temperature: float = 0.0, max_tokens: int = 300) -> BaseModel:
        model = ModelFactory.get()
        prompt = self.build_prompt(user_text)
        raw = model(prompt, self.schema_cls, temperature=temperature, max_tokens=max_tokens)
        return self.schema_cls.model_validate_json(raw)

    def extract_dict(self, user_text: str, **kwargs) -> Dict[str, Any]:
        parsed = self.extract(user_text, **kwargs).model_dump()
        # Add a presence report so Coordinator knows what was actually provided
        presence = compute_presence(parsed)
        return {"result": parsed, "provided_fields": presence}


def compute_presence(parsed_envelope: Dict[str, Any]) -> List[str]:
    """
    Flatten updated fields that are actually provided (not 'Not provided' and not empty list).
    Returns dotted paths under updates.<section>....
    """
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
                # list counts as provided if non-empty
                if len(obj) > 0:
                    out.append(prefix)
            else:
                # scalar string provided if != NOT_PROVIDED
                if isinstance(obj, str) and obj != NOT_PROVIDED:
                    out.append(prefix)
        if isinstance(payload, dict):
            walk(section, payload)
    return sorted(set(out))


# ======================
# Concrete extractors
# ======================
class ArboristInfoExtractor(BaseExtractor):
    schema_cls = ExtractorReturnArborist

    def build_prompt(self, user_text: str) -> str:
        fields = [
            ("name", "full name or 'Not provided'"),
            ("company", "company name or 'Not provided'"),
            ("phone", "phone number or 'Not provided'"),
            ("email", "email or 'Not provided'"),
            ("license", "license code or 'Not provided'"),
            ("address.street", "street line or 'Not provided'"),
            ("address.city", "city or 'Not provided'"),
            ("address.state", "state or 'Not provided'"),
            ("address.postal_code", "ZIP code or 'Not provided'"),
            ("address.country", "country or 'Not provided'"),
        ]
        # Flattened field descriptions in prompt; model still outputs nested address object.
        # To keep the schema echo simple we list keys directly under section block plus address object.
        role_hint = "First-person statements (e.g., 'my name is…', 'my phone is…') refer to the ARBORIST."
        # For schema echo we need object with address subobject — we’ll inject the correct shape:
        prompt = build_prompt(
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
        # Append the nested address shape explicitly to avoid confusion:
        address_block = (
            "Also include the nested object exactly as follows inside arborist_info:\n"
            '"address": {\n'
            '  "street": string,\n'
            '  "city": string,\n'
            '  "state": string,\n'
            '  "postal_code": string,\n'
            '  "country": string\n'
            "}\n"
        )
        return prompt + "\n" + address_block


class CustomerInfoExtractor(BaseExtractor):
    schema_cls = ExtractorReturnCustomer

    def build_prompt(self, user_text: str) -> str:
        role_hint = (
            "First-person refers to the CUSTOMER only when explicitly indicated "
            "(e.g., 'the customer says my name is…'). Otherwise, prefer third-person phrases "
            "like 'customer name is…'."
        )
        prompt = build_prompt(
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
            "Also include the nested object exactly as follows inside customer_info:\n"
            '"address": {\n'
            '  "street": string,\n'
            '  "city": string,\n'
            '  "state": string,\n'
            '  "postal_code": string,\n'
            '  "country": string\n'
            "}\n"
        )
        return prompt + "\n" + address_block


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
            ],
            list_notes=None,
            user_text=user_text,
        )


class RisksExtractor(BaseExtractor):
    schema_cls = ExtractorReturnRisks

    def build_prompt(self, user_text: str) -> str:
        role_hint = "Copy risks verbatim; use an array of items. If none, items = []."
        # For lists, we instruct array behavior via list_notes; schema already expects items[].
        base = build_prompt(
            section_name="risks",
            role_hint=role_hint,
            fields=[],  # risks has only the items list at the top-level of the section
            list_notes={"items": "Array of objects with fields description, likelihood, severity, rationale"},
            user_text=user_text,
        )
        # Add explicit nested item shape:
        items_shape = (
            "Each element of 'items' must be an object with exactly these string fields:\n"
            "{ \"description\": string, \"likelihood\": string, \"severity\": string, \"rationale\": string }\n"
            "If no risks are present, return \"items\": [].\n"
        )
        return base + "\n" + items_shape

# -----------------------------
# Area / Targets / Recommendations (verbatim-friendly)
# -----------------------------

class AreaDescription(BaseModel):
    """
    Verbatim-friendly area section. All fields are required at schema level in
    extractors, but default to NOT_PROVIDED in state.
    """
    context: str = NOT_PROVIDED                 # e.g., 'urban' | 'suburban' | 'rural' | ...
    other_context_note: str = NOT_PROVIDED
    site_use: str = NOT_PROVIDED
    foot_traffic_level: str = NOT_PROVIDED
    narratives: List[str] = Field(default_factory=list)


class TargetItem(BaseModel):
    """
    A potential target near the tree (people, property, utilities).
    """
    label: str = Field(default=NOT_PROVIDED)     # e.g., 'playground', 'sidewalk', 'house'
    damage_modes: List[str] = Field(default_factory=list)  # verbatim list (or empty)
    proximity_note: str = Field(default=NOT_PROVIDED)
    occupied_frequency: str = Field(default=NOT_PROVIDED)
    narratives: List[str] = Field(default_factory=list)


class TargetsSection(BaseModel):
    items: List[TargetItem] = Field(default_factory=list)
    narratives: List[str] = Field(default_factory=list)


class RecommendationDetail(BaseModel):
    """
    Structured recommendation bucket (pruning / removal / continued_maintenance).
    """
    narrative: str = Field(default=NOT_PROVIDED)
    scope: str = Field(default=NOT_PROVIDED)
    limitations: str = Field(default=NOT_PROVIDED)
    notes: str = Field(default=NOT_PROVIDED)


class RecommendationsSection(BaseModel):
    pruning: RecommendationDetail = Field(default_factory=RecommendationDetail)
    removal: RecommendationDetail = Field(default_factory=RecommendationDetail)
    continued_maintenance: RecommendationDetail = Field(default_factory=RecommendationDetail)
    narratives: List[str] = Field(default_factory=list)
