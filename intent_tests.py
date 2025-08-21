#!/usr/bin/env python3
# run_intent_tests.py
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import List, Tuple

from intent_llm import classify_intent_llm

LOG_PATH = "intent_tests.txt"

# (phrase, expected_intent)
TESTS: List[Tuple[str, str]] = [
    # PROVIDE_DATA
    ("my name is roger erismann and dbh is 24 inches", "PROVIDE_DATA"),
    ("customer address is 12 oak ave, san jose", "PROVIDE_DATA"),

    # REQUEST_SUMMARY
    ("give me a short summary", "REQUEST_SUMMARY"),
    ("can you recap what you have?", "REQUEST_SUMMARY"),

    # REQUEST_REPORT
    ("produce the full report", "REQUEST_REPORT"),
    ("export the final report text", "REQUEST_REPORT"),

    # WHAT_IS_LEFT
    ("what's left?", "WHAT_IS_LEFT"),
    ("what do you still need from me?", "WHAT_IS_LEFT"),

    # ASK_FIELD
    ("what did you capture for DBH?", "ASK_FIELD"),
    ("what is the recorded tree height?", "ASK_FIELD"),

    # ASK_QUESTION
    ("is a coast live oak suitable near sidewalks?", "ASK_QUESTION"),
    ("how fast do redwoods grow?", "ASK_QUESTION"),

    # SMALL_TALK
    ("thanks", "SMALL_TALK"),
    ("hello there", "SMALL_TALK"),
]

def main():
    lines = []
    lines.append("=" * 72)
    lines.append(f"Arborist Agent — Intent Classifier Tests  [{datetime.now().isoformat()}]")
    lines.append("=" * 72)
    lines.append("")

    for i, (phrase, expected) in enumerate(TESTS, start=1):
        try:
            out = classify_intent_llm(phrase)
            got = out.intent
            ok = (got == expected)
            rec = {
                "case": i,
                "phrase": phrase,
                "expected": expected,
                "got": got,
                "match": ok,
            }
        except Exception as e:
            rec = {
                "case": i,
                "phrase": phrase,
                "expected": expected,
                "error": str(e),
                "match": False,
            }
        lines.append(json.dumps(rec, ensure_ascii=False, indent=2))
        lines.append("")

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Wrote {LOG_PATH}")

if __name__ == "__main__":
    # Ensure env is set like your other tests:
    #   export LLM_BACKEND='openai'
    #   export OPENAI_MODEL='gpt-4o-mini'
    #   export OPENAI_API_KEY=...
    main()
