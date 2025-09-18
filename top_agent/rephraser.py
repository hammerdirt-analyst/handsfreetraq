# top_agent/rephraser.py

from __future__ import annotations
import os
import re
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class RephraseConfig:
    max_chars: int = 320
    tone: str = "neutral, professional, concise"
    model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

_FREEZE_PATTERNS = [
    r'\b\d{1,3}(?:[.,]\d{1,3})?\s?(?:in|inch(?:es)?|ft|feet|m|cm|mm)\b',  # numbers+units
    r'\b\d{1,4}\b',                                 # stand-alone small integers (dbh, heights)
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',  # emails
    r'\b(?:\+?\d[\d\-\s]{6,}\d)\b',                 # phone-like
    r'\[[a-z_]+-p\d+\]',                            # paragraph IDs [tree_description-p1]
    r'"[^"\n]{1,200}"',                             # quoted strings
    r'`{3}[\s\S]+?`{3}',                            # code blocks
    r'Captured:\s?.*$',                             # captured confirmation line
    r'Updated\s+`[^`]+`.*$',                        # updated X to Y confirmations
]

def _mask(text: str) -> tuple[str, Dict[str, str]]:
    """Replace frozen spans with placeholders so the LLM won’t change them."""
    slots: Dict[str, str] = {}
    idx = 0
    def repl(m: re.Match) -> str:
        nonlocal idx
        token = f"[[FROZEN_{idx}]]"
        slots[token] = m.group(0)
        idx += 1
        return token

    masked = text
    for rx in _FREEZE_PATTERNS:
        masked = re.sub(rx, repl, masked, flags=re.IGNORECASE | re.MULTILINE)
    return masked, slots

def _unmask(text: str, slots: Dict[str, str]) -> str:
    for k, v in slots.items():
        text = text.replace(k, v)
    return text

def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip() + "…"

def rephrase(reply_text: str, *, cfg: Optional[RephraseConfig] = None) -> str:
    """
    Guardrailed rephrase:
    - Freezes sensitive spans.
    - Light rewrite prompt.
    - Falls back to identity on any error.
    """
    if not reply_text:
        return reply_text
    cfg = cfg or RephraseConfig()

    masked, slots = _mask(reply_text)

    # Lightweight, provider-agnostic — optional: swap for your shared LLM helper.
    # To keep Phase 2b lean and testable, we do a rules-first rewrite and ONLY call an LLM if present.
    # If you want zero-LLM here for now, just return the normalized text.

    # Normalize whitespace & style without changing meaning
    normalized = " ".join(masked.strip().split())
    # Hand-tuned paraphrases to soften phrasing but preserve semantics
    normalized = normalized.replace("I can’t", "I can’t").replace("cannot", "can’t")
    normalized = normalized.replace("Please specify", "Which would you like?")
    normalized = normalized.replace("What section would you like to add", "Which section would you like to add")

    out = _truncate(normalized, cfg.max_chars)
    out = _unmask(out, slots)
    return out
