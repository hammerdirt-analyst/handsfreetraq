"""
Project: Arborist Agent
File: extractor_registry.py
Author: roger erismann
Assistant: chatGPT5
code review: chatGPT5

Validating registry that maps canonical section ids to extractor classes and
returns fresh extractor instances. Ensures required sections exist and catches typos.

For each section of the report there is an extractor. Each extractor has pydantic model
that defines the fields and types.

Methods & Classes
- REQUIRED_SECTIONS: canonical mapping of section -> extractor class.
- class ExtractorRegistry(mapping: dict[str, Type])
  - __init__(mapping): copy & validate mapping.
  - _validate() -> None: assert required sections present, no unknown keys, correct subclassing.
  - get(section: str): instantiate and return extractor for a canonical section id.
- default_registry() -> ExtractorRegistry: factory for the validated default mapping.

Dependencies
- Internal: models.TreeDescriptionExtractor, AreaDescriptionExtractor, TargetExtractor,
            RisksExtractor, RecommendationsExtractor
- Stdlib: logging, typing
"""

from __future__ import annotations
from typing import Dict, Type
import logging

# import your concrete extractors
from arborist_report.models import (
    TreeDescriptionExtractor,
    AreaDescriptionExtractor,
    TargetExtractor,
    RisksExtractor,
    RecommendationsExtractor,

)

LOGGER = logging.getLogger("arb.registry")

REQUIRED_SECTIONS = {
    "tree_description": TreeDescriptionExtractor,
    "area_description": AreaDescriptionExtractor,
    "targets": TargetExtractor,
    "risks": RisksExtractor,
    "recommendations": RecommendationsExtractor,
}

class ExtractorRegistry:
    def __init__(self, mapping: Dict[str, Type]):
        self._mapping = dict(mapping)
        self._validate()

    def _validate(self) -> None:
        # 1) all required sections present with the correct class types
        missing = [s for s in REQUIRED_SECTIONS if s not in self._mapping]
        wrong = [
            s for s, cls in self._mapping.items()
            if s in REQUIRED_SECTIONS and not issubclass(cls, REQUIRED_SECTIONS[s])
        ]
        if missing or wrong:
            LOGGER.error(
                "extractor_registry_invalid",
                extra={"missing": missing, "wrong": wrong},
            )
            raise RuntimeError(f"Extractor registry invalid. missing={missing} wrong={wrong}")

        # 2) no stray unknown sections (helps catch typos like 'recommendation')
        unknown = [s for s in self._mapping if s not in REQUIRED_SECTIONS]
        if unknown:
            LOGGER.error("extractor_registry_unknown_sections", extra={"unknown": unknown})
            raise RuntimeError(f"Unknown sections in registry: {unknown}")

        LOGGER.info("extractor_registry_validated", extra={"sections": sorted(self._mapping)})

    def get(self, section: str):
        """Return an *instance* of the extractor for a canonical section id."""
        cls = self._mapping.get(section)
        if not cls:
            LOGGER.error("extractor_not_found", extra={"section": section})
            raise KeyError(f"No extractor for section: {section}")
        try:
            inst = cls()
            LOGGER.debug("extractor_instantiated", extra={"section": section, "class": cls.__name__})
            return inst
        except Exception as e:
            LOGGER.exception("extractor_init_failed", extra={"section": section, "class": cls.__name__})
            raise

# factory to create the default, validated registry
def default_registry() -> ExtractorRegistry:
    return ExtractorRegistry(REQUIRED_SECTIONS)
