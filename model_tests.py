#!/usr/bin/env python3
# run_model_tests.py
#
# Runs two phrases per extractor and logs Expected vs Got to model_tests.txt.
# Requires:
#   export OPENAI_API_KEY=...
#   export OPENAI_MODEL=gpt-4o-mini   # or your model
#
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Dict, Tuple

# As requested:
from models import (
    ArboristInfoExtractor,
    CustomerInfoExtractor,
    TreeDescriptionExtractor,
    RisksExtractor,
)

LOG_PATH = "model_tests.txt"
NOT_PROVIDED = "Not provided"


def write_header(f):
    f.write("=" * 72 + "\n")
    f.write(f"Arborist Agent — Extractor Smoke Tests  [{datetime.now().isoformat()}]\n")
    f.write("=" * 72 + "\n\n")


def fmt_block(title: str, body: str) -> str:
    line = "-" * 72
    return f"{title}\n{line}\n{body}\n\n"


def run_one(
    section_name: str,
    extractor,
    cases: List[Tuple[str, List[str]]],
) -> str:
    """
    cases: list of (phrase, expected_provided_fields)
    expected_provided_fields: dotted paths under updates.<section>...
    """
    out = []
    out.append(f"[SECTION] {section_name}")
    out.append("")

    for i, (phrase, expected_fields) in enumerate(cases, start=1):
        try:
            result = extractor.extract_dict(phrase, temperature=0.0, max_tokens=300)
            provided = result.get("provided_fields", [])
            payload = result.get("result", {})

            ok = set(provided) == set(expected_fields)

            body = {
                "phrase": phrase,
                "expected_provided_fields": expected_fields,
                "got_provided_fields": provided,
                "match": ok,
                "json_result": payload,
            }
            out.append(fmt_block(f"Case {i}", json.dumps(body, indent=2, ensure_ascii=False)))
        except Exception as e:
            body = {
                "phrase": phrase,
                "error": str(e),
            }
            out.append(fmt_block(f"Case {i} — ERROR", json.dumps(body, indent=2, ensure_ascii=False)))

    return "\n".join(out)


def main():
    # Build extractors
    arb = ArboristInfoExtractor()
    cust = CustomerInfoExtractor()
    tree = TreeDescriptionExtractor()
    risks = RisksExtractor()

    # --------------------------
    # Test phrases & expectations
    # NOTE: expectations list the dotted paths that should appear in
    # extractor.compute_presence() output (i.e., actually provided).
    # --------------------------

    # Arborist info
    arb_cases = [
        (
            "my name is roger erismann and my phone is 415-555-1212.",
            [
                "arborist_info.name",
                "arborist_info.phone",
            ],
        ),
        (
            "I'm Alex Tree, license CA-1234; email alex@trees.io; company Redwood Care.",
            [
                "arborist_info.name",
                "arborist_info.license",
                "arborist_info.email",
                "arborist_info.company",
            ],
        ),
    ]

    # Customer info
    cust_cases = [
        (
            "Customer name is Sam Patel, address 12 Oak Ave, San Jose CA 95112.",
            [
                "customer_info.name",
                "customer_info.address.street",
                "customer_info.address.city",
                "customer_info.address.state",
                "customer_info.address.postal_code",
            ],
        ),
        (
            "The client company is Green Roots LLC; contact email client@roots.com.",
            [
                "customer_info.company",
                "customer_info.email",
            ],
        ),
    ]

    # Tree description (numeric as strings; we don’t normalize here)
    tree_cases = [
        (
            "Species coast live oak (Quercus agrifolia). DBH 24 in, height about 60 ft, canopy 40 ft, crown oval. Notes: minor trunk wound.",
            [
                "tree_description.type_common",
                "tree_description.type_scientific",
                "tree_description.dbh_in",
                "tree_description.height_ft",
                "tree_description.canopy_width_ft",
                "tree_description.crown_shape",
                "tree_description.trunk_notes",
            ],
        ),
        (
            "It's a pine; DBH 32; height 70.",
            [
                "tree_description.type_common",
                "tree_description.dbh_in",
                "tree_description.height_ft",
            ],
        ),
    ]

    # Risks (array)
    risks_cases = [
        (
            "Risks: falling branches (likelihood medium, severity high, rationale over walkway).",
            [
                # items (list) is considered provided if non-empty; presence will include "risks.items"
                "risks.items",
            ],
        ),
        (
            "No particular risks identified.",
            [
                # Expect no provided fields, because items should be []
                # (compute_presence treats empty list as not provided)
            ],
        ),
    ]

    sections = [
        ("arborist_info", arb, arb_cases),
        ("customer_info", cust, cust_cases),
        ("tree_description", tree, tree_cases),
        ("risks", risks, risks_cases),
    ]

    # Run and write the log
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        write_header(f)
        for name, ex, cases in sections:
            block = run_one(name, ex, cases)
            f.write(block)
            f.write("\n")

    print(f"Wrote test log to {LOG_PATH}")


if __name__ == "__main__":
    main()
