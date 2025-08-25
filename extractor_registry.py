# extractor_registry.py
from __future__ import annotations
from typing import Dict, Type
import logging

# import your concrete extractors
from models import (
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
