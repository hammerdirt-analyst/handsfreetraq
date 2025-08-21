"""
config.py — author: roger erismann
Minimal runtime configuration flags.
"""

import os


def _to_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


USE_LLM_EXTRACTOR: bool = _to_bool(os.getenv("USE_LLM_EXTRACTOR"), default=False)

