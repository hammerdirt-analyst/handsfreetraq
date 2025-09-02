"""
Project: Arborist Agent
File: service_classifier.py
Author: roger erismann

LLM-backed service classifier used as a backstop when the deterministic
router returns NONE. Produces a structured (service, section?, confidence) result
via the same ModelFactory used by extractors.

Methods & Classes
- Pydantic types:
  - ServiceName (Literal), SectionName (Literal)
  - class ServiceRouteResult: {service, section?, confidence}
  - class ExtractorReturnServiceRoute: {result: ServiceRouteResult}
- class ServiceRouterClassifier(BaseExtractor)
  - schema_cls = ExtractorReturnServiceRoute
  - build_prompt(user_text: str) -> str: constrained JSON-only prompt for classification.
  - extract_dict(user_text: str, *, temperature=0.0, max_tokens=256) -> dict: run via ModelFactory and return plain dict.
  - classify(user_text: str) -> tuple[ServiceName, Optional[SectionName], float]: convenience tuple result.

Dependencies
- Internal: models.ModelFactory, models.BaseExtractor
- External: pydantic
- Stdlib: typing
"""

from __future__ import annotations

from typing import Optional, Literal, Tuple
from pydantic import BaseModel, Field, ConfigDict

# Reuse your existing factory/extractor base
from models import ModelFactory
from models import BaseExtractor


# =========================
# Schema (Pydantic)
# =========================

ServiceName = Literal[
    "MAKE_CORRECTION",
    "SECTION_SUMMARY",
    "QUICK_SUMMARY",
    "MAKE_REPORT_DRAFT",
    "NONE"
]

SectionName = Literal[
    "tree_description",
    "risks",
    "targets",
    "area_description",
    "recommendations",
]

class ServiceRouteResult(BaseModel):
    """
    The LLM must fill these fields. Confidence is a 0.0–1.0 float (string or float accepted).
    """
    service: ServiceName = Field(...)
    section: Optional[SectionName] = Field(default=None)
    confidence: float = Field(..., ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class ExtractorReturnServiceRoute(BaseModel):
    """
    We mirror your extractor output contract: a top-level 'result' object.
    """
    result: ServiceRouteResult

    model_config = ConfigDict(extra="forbid")


# =========================
# Classifier Extractor
# =========================

class ServiceRouterClassifier(BaseExtractor):
    """
    LLM-backed service router. Plug into your coordinator the same way
    you invoke other extractors: call .extract_dict(user_text, ...).
    """
    schema_cls = ExtractorReturnServiceRoute

    def build_prompt(self, user_text: str) -> str:
        """
        Keep this tightly constrained: classification only, no free-form text.
        """
        return f"""You are a strict classifier for a tree-report assistant. 
Classify the user's request into EXACTLY ONE of these services:
- MAKE_CORRECTION      (user asks to change/fix/update a captured value)
- SECTION_SUMMARY      (user wants a summary of ONE section)
- QUICK_SUMMARY        (user wants a brief overall/quick summary of the whole state)
- MAKE_REPORT_DRAFT    (user wants a report draft generated)
- NONE                 (no service request)

If the service is SECTION_SUMMARY or MAKE_CORRECTION, also pick a section from:
- tree_description | risks | targets | area_description | recommendations
Else set section = null.

Set confidence between 0.0 and 1.0 (low → unsure, high → very sure). 
Return ONLY JSON with fields: result.service, result.section, result.confidence.

Guidance:
- Correction cues: change, correct, fix, adjust, edit, update, amend, set, replace, switch, alter
- Section-summary cues: summary/overview/tldr/recap/breakdown/outline/synopsis + a section name
- Quick-summary cues: quick/overall/executive/at a glance/status/fast/brief/condensed
- Report draft cues: make/produce/build/construct/assemble/compile/generate/draft report

User text:
{user_text}
"""

    def extract_dict(
        self,
        user_text: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> dict:
        """
        Run the classification through the same ModelFactory the other extractors use.
        Return a plain dict like your other extractors do.
        """
        model = ModelFactory.get()  # same lazy-init + caching as your extractors
        prompt = self.build_prompt(user_text)

        # With Outlines-style structured calling: model(self.schema_cls, prompt)
        # Adapt if your factory returns a slightly different callable.
        parsed: ExtractorReturnServiceRoute = model(self.schema_cls, prompt, temperature=temperature, max_tokens=max_tokens)

        # Normalize to dict for coordinator
        return {"result": parsed.model_dump(exclude_none=False)}

    # Optional tiny helper for direct use in tests/CLI (tuple form)
    def classify(self, user_text: str) -> Tuple[ServiceName, Optional[SectionName], float]:
        out = self.extract_dict(user_text)
        res = out["result"]
        return res["service"], res.get("section"), float(res["confidence"])
