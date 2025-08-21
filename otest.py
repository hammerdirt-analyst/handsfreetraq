#!/usr/bin/env python3
"""
structured_probe.py — Outlines 1.2.3 + OpenAI v1 reusable structured extraction

Usage:
  export OPENAI_API_KEY=sk-...
  export OPENAI_MODEL=gpt-4o-mini
  ./structured_probe.py                       # default extractor + default text
  ./structured_probe.py arborist_info "my name is roger erismann"
"""
#
# from __future__ import annotations
#
# import os
# import sys
import json
# from functools import lru_cache
# from typing import Type, Dict
#
# import outlines
# import openai
# from pydantic import BaseModel, Field, ConfigDict
# from models2 import ArboristInfo
#
#
# # =========================
# #  Shared model factory
# # =========================
#
# class ModelFactory:
#     """Creates/caches the Outlines model bound to OpenAI v1, using env vars."""
#     @staticmethod
#     @lru_cache(maxsize=1)
#     def get():
#         if not os.getenv("OPENAI_API_KEY"):
#             raise SystemExit("ERROR: set OPENAI_API_KEY in your environment")
#         model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
#         client = openai.OpenAI()  # reads key from env
#         return outlines.from_openai(client, model_name)
#
#
# # =========================
# #  Base extractor interface
# # =========================
#
# class BaseExtractor:
#     """Reusable runner: subclasses define schema_cls + build_prompt()."""
#
#     schema_cls: Type[BaseModel] = BaseModel  # override in subclasses
#
#     def build_prompt(self, user_text: str) -> str:
#         raise NotImplementedError
#
#     def extract(self, user_text: str, *, temperature: float = 0.0, max_tokens: int = 200) -> BaseModel:
#         model = ModelFactory.get()
#         prompt = self.build_prompt(user_text)
#         raw = model(prompt, self.schema_cls, temperature=temperature, max_tokens=max_tokens)
#         return self.schema_cls.model_validate_json(raw)
#
#     def extract_dict(self, user_text: str, **kwargs) -> dict:
#         return self.extract(user_text, **kwargs).model_dump()
#
#
# # =========================
# #  Example data class: Arborist Info
# #  (All fields REQUIRED; OpenAI JSON schema needs required[] + no extras)
# # =========================
#
# # class ArboristInfo(BaseModel):
# #     # REQUIRED fields; model must fill "Not provided" when unknown
# #     name: str = Field(..., description="Person's full name or 'Not provided'")
# #     company: str = Field(..., description="Company or 'Not provided'")
# #     phone: str = Field(..., description="Phone or 'Not provided'")
# #     email: str = Field(..., description="Email or 'Not provided'")
# #     license: str = Field(..., description="License or 'Not provided'")
# #
# #     # Ensure JSON Schema has "additionalProperties": false
# #     model_config = ConfigDict(extra="forbid")
#
#
# class Updates(BaseModel):
#     arborist_info: ArboristInfo = Field(...)
#
#     model_config = ConfigDict(extra="forbid")
#
#
# class ExtractorReturn(BaseModel):
#     updates: Updates = Field(...)
#
#     model_config = ConfigDict(extra="forbid")
#
#
# class ArboristInfoExtractor(BaseExtractor):
#     """Produces: { "updates": { "arborist_info": { ... } } }"""
#
#     schema_cls: Type[BaseModel] = ExtractorReturn
#
#     def build_prompt(self, user_text: str) -> str:
#         return (
#             "VERBATIM-ONLY MODE.\n"
#             "You must output a JSON object matching the schema exactly. All fields are REQUIRED.\n"
#             "Rules:\n"
#             "  • If a value appears in the user message (case-insensitive substring), COPY it verbatim.\n"
#             "  • Otherwise, set the field to the exact string: Not provided\n"
#             "  • FIRST-PERSON = ARBORIST: For first-person statements (e.g., 'my name is …', 'my phone is …'), "
#             "place values under updates.arborist_info.*\n"
#             "  • NAMES: Output only the person's name (not the words 'my name is').\n\n"
#             "Schema:\n"
#             "{\n"
#             "  \"updates\": {\n"
#             "    \"arborist_info\": {\n"
#             "      \"name\": string,\n"
#             "      \"company\": string,\n"
#             "      \"phone\": string,\n"
#             "      \"email\": string,\n"
#             "      \"license\": string\n"
#             "    }\n"
#             "  }\n"
#             "}\n\n"
#             f"User message:\n{user_text}\n"
#         )
#
#
# # =========================
# #  Registry and CLI
# # =========================
#
# EXTRACTORS: Dict[str, BaseExtractor] = {
#     "arborist_info": ArboristInfoExtractor(),
#     # Add more extractors here, e.g. "customer_info": CustomerInfoExtractor()
# }
#
# def main():
#     # CLI:
#     #   ./structured_probe.py [extractor_key] [user_text...]
#     # Defaults to 'arborist_info' and "my name is roger erismann"
#     if len(sys.argv) >= 2 and sys.argv[1] in EXTRACTORS:
#         extractor_key = sys.argv[1]
#         user_text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "my name is roger erismann"
#     else:
#         extractor_key = "arborist_info"
#         user_text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "my name is roger erismann"
#
#     result = EXTRACTORS[extractor_key].extract_dict(user_text, temperature=0.0, max_tokens=200)
#     print(json.dumps(result, indent=2, ensure_ascii=False))

from models2 import (
    ArboristInfoExtractor,
    CustomerInfoExtractor,
    TreeDescriptionExtractor,
    RisksExtractor,
)

def main():
    extractor = ArboristInfoExtractor()
    out = extractor.extract_dict("my name is roger erismann; my phone is 415-555-9999")
    print(json.dumps(out, indent=2))
if __name__ == "__main__":
    main()
