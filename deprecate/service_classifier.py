"""
Project: Arborist Agent
File: service_classifier.py
Author: roger erismann (updated for OUTLINE)

LLM-backed service classifier used as a backstop when the deterministic
router returns NONE. Produces a structured (service, section, confidence) result
via the same ModelFactory used by extractors.

Policy notes:
- Replaced QUICK_SUMMARY with OUTLINE.
- “outline” is the ONLY cue for OUTLINE.
- Phrases like “recap / brief summary / overview / executive summary” imply prose and map
  to SECTION_SUMMARY ONLY when a section is specified; otherwise prefer NONE (Coordinator clarifies).
- If user says “outline” with a section → SECTION_SUMMARY (that section); Coordinator renders outline mode.
- If “outline” without a section → OUTLINE with section = null (Coordinator may use current_section).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict
from arborist_report.models import ModelFactory, ServiceRouteOutput, ServiceName, SectionName

class ServiceRouteResult(BaseModel):
    """
    The LLM must fill these fields. Confidence is a 0.0–1.0 float (string or float accepted).

    NOTE: `section` is REQUIRED-BUT-NULLABLE to satisfy OpenAI's strict JSON schema.
    This ensures the key is always present (and thus listed in `required`) but may be null.
    """
    service: ServiceName = Field(...)
    section: SectionName | None = Field(
        ...,
        description="Present in all cases; null when not applicable.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")


class ExtractorReturnServiceRoute(BaseModel):
    """
    Mirror extractor output contract: a top-level 'result' object.
    """
    result: ServiceRouteResult

    model_config = ConfigDict(extra="forbid")


# =========================
# Classifier Extractor
# =========================

class ServiceRouterClassifier:
    """
    LLM-backed service router. Plug into your coordinator the same way
    you invoke other extractors: call .extract_dict(user_text, ...).
    """
    schema_cls = ExtractorReturnServiceRoute

    def build_prompt(self, user_text: str) -> str:
        """
        Constrained JSON-only prompt for classification.
        """
        return f"""You are a strict classifier for a tree-report assistant.
Classify the user's request into EXACTLY ONE of these services:
- MAKE_CORRECTION      (user asks to change/fix/update/add/remove something already captured)
- SECTION_SUMMARY      (user wants a summary of ONE section; prose by default)
- OUTLINE              (user explicitly asks for an "outline"; section may be omitted)
- MAKE_REPORT_DRAFT    (user wants a report draft generated)
- NONE                 (no service request or too ambiguous)

If the service is SECTION_SUMMARY or MAKE_CORRECTION, also pick a section from:
- tree_description | risks | targets | area_description | recommendations
Else set section = null.

POLICY & CUE RULES (must follow exactly):
- OUTLINE is ONLY chosen when the user explicitly uses the word "outline".
- If "outline" + a specific section is present → service=SECTION_SUMMARY, that section.
- If "outline" appears without a section → service=OUTLINE, section=null.
- Words like "recap", "brief summary", "summary", "overview", "synopsis", "executive summary" imply prose.
  • If a section is named → service=SECTION_SUMMARY for that section.
  • If no section is named → service=NONE (ambiguous; the app will clarify).
- Draft cues: make/generate/build/construct/assemble/compile/write/prepare/start + the word "report" → MAKE_REPORT_DRAFT.
- Corrections: change/correct/fix/adjust/edit/update/amend/set/replace/switch/alter/add/append/insert/remove/delete
  • Prefer MAKE_CORRECTION ONLY if a section or field/assignment is clearly indicated; otherwise NONE.

Return ONLY JSON with fields: result.service, result.section, result.confidence.

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
        LLM backstop classification using ModelFactory.
        Returns:
          {
            "result": {"service": <str>, "section": <str|None>, "confidence": <float>},
            "tokens": {"in": int, "out": int},
            "model": "<model-name>",
          }
        """
        prompt = self.build_prompt(user_text)

        mdl = ModelFactory.get()  # returns our StructuredModel wrapper
        out = mdl(prompt, output_type=self.schema_cls, temperature=temperature, max_tokens=max_tokens)

        parsed = out["parsed"]  # Outer schema (ExtractorReturnServiceRoute)
        tokens = out["tokens"]  # {"in": ..., "out": ...}  (ensure ModelFactory uses this key)
        model_name = out["model"]

        inner = parsed.result  # ServiceRouteResult instance
        return {
            "result": {
                "service": inner.service,
                "section": getattr(inner, "section", None),
                "confidence": float(inner.confidence),
            },
            "tokens": tokens,
            "model": model_name,
        }

    def classify(self, user_text: str):
        """
        Convenience wrapper used by Coordinator backstop.
        Returns a small namespace with .service, .section, .confidence, .tokens, .model
        """
        out = self.extract_dict(user_text)
        r = out["result"]
        from types import SimpleNamespace
        return SimpleNamespace(
            service=r["service"],
            section=r.get("section"),
            confidence=float(r["confidence"]),
            tokens=out.get("tokens", {"in": 0, "out": 0}),
            model=out.get("model"),
        )

