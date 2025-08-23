#!/usr/bin/env python3
# runners.py — Drive Coordinator with phrases + (optional) expectations.
# Logs:
#  - runners.log                      (JSONL per phrase with verdicts)
#  - state_logs/state-YYYYMMDD.jsonl  (state snapshots after each turn)
#  - coordinator-tests.txt            (from Coordinator itself)

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

# ----- Your modules -----
from report_agent import Coordinator, classify_data_domains_llm
from intent_llm import classify_intent_llm
from report_state import ReportState
from report_context import _build_context_from_testdata

# ---- Fixtures ----
from test_data import PHRASES, EXPECTATIONS

# ------------- paths -------------
RUNNERS_LOG = "runners.log"


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _today_tag() -> str:
    return datetime.utcnow().strftime("%Y%m%d")


def _load_lines(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f.readlines() if ln.strip()]


def _load_phrases(path: Optional[str]) -> List[str]:
    if path and os.path.exists(path):
        return _load_lines(path)
    # fallback: test_data fixtures
    return PHRASES


def _load_expectations(path: Optional[str]) -> Dict[str, Any]:
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            if path.endswith(".json"):
                return json.load(f)
            try:
                import yaml  # type: ignore
                return yaml.safe_load(f)
            except Exception:
                return json.load(f)
    # fallback: test_data fixtures
    return EXPECTATIONS


def _exp_for(utterance: str, expectations: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return expectations.get(utterance)


def _write_jsonl(path: str, obj: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _state_log_path() -> str:
    os.makedirs("state_logs", exist_ok=True)
    return os.path.join("state_logs", f"state-{_today_tag()}.jsonl")


def _snapshot_state(state: ReportState) -> Dict[str, Any]:
    dmp = state.model_dump(exclude_none=False)
    return {
        "ts": _now_iso(),
        "provided_fields": sorted(state.meta.provided_fields),
        # Report-only sections (context lives outside ReportState)
        "tree_description": dmp.get("tree_description", {}),
        "area_description": dmp.get("area_description", {}),
        "risks": dmp.get("risks", {}),
        "recommended": dmp.get("recommended", {}),
    }


def _domains_match_expected(expected: Optional[List[str]], actual: List[str]) -> Optional[bool]:
    """
    Domain verdict logic:

    - If expectations omit 'domains' (None): return None (no check).
    - If expectations specify an empty list: require actual == [].
    - If expectations specify a non-empty list: success if ANY overlap with actual.
    """
    if expected is None:
        return None
    if isinstance(expected, list) and len(expected) == 0:
        return actual == []
    if isinstance(expected, list):
        return any(d in actual for d in expected)
    # If a single string accidentally provided, treat as exact membership
    return expected in actual  # type: ignore[arg-type]


def run(phrases_file: Optional[str], expectations_file: Optional[str]) -> int:
    phrases = _load_phrases(phrases_file)
    expectations = _load_expectations(expectations_file) or {}

    coord = Coordinator(_build_context_from_testdata())

    passes = 0
    fails = 0

    print(f"[info] Loaded {len(phrases)} phrases")

    for utt in phrases:
        ts = _now_iso()

        # ---------- direct intent ----------
        try:
            intent_direct = classify_intent_llm(utt).intent
            intent_err = None
        except Exception as e:
            intent_direct = "INTENT_ERROR"
            intent_err = str(e)

        # (Optional) direct domain probe for debugging only:
        domains_direct = None
        dom_err = None
        if intent_direct == "PROVIDE_STATEMENT":
            try:
                domains_direct = classify_data_domains_llm(utt)
            except Exception as e:
                dom_err = str(e)

        # ---------- coordinator ----------
        result = coord.handle_turn(utt)
        coord_domains = ((result.get("result") or {}).get("domains")) or []

        # ---------- expectations + verdicts ----------
        exp = _exp_for(utt, expectations)
        verdict = {
            "intent_match": None,
            "domains_match": None,
            "expectations_ok": None,
            "phrase_ok": None,
        }

        if exp:
            # Intent check (compare to direct intent label)
            if "intent" in exp:
                verdict["intent_match"] = (intent_direct == exp["intent"])

            # Domains check (compare expectations to coordinator domains)
            verdict["domains_match"] = _domains_match_expected(exp.get("domains"), coord_domains)

            # Provided fields containment (optional)
            exp_pf = exp.get("provided_contains") or []
            if exp_pf and result.get("result"):
                got_pf = set((result["result"].get("provided_fields") or []))
                verdict["expectations_ok"] = all(p in got_pf for p in exp_pf)

            # Phrase OK if all specified checks are True
            checks = [
                v for v in [
                    verdict["intent_match"],
                    verdict["domains_match"],
                    verdict["expectations_ok"],
                ] if v is not None
            ]
            verdict["phrase_ok"] = all(checks) if checks else True
        else:
            # If no explicit expectation, we consider the coordinator run OK unless it hard-failed
            verdict["phrase_ok"] = bool(result.get("ok") is not False and result.get("error") is None)

        if verdict["phrase_ok"]:
            passes += 1
        else:
            fails += 1

        # ---------- log one line ----------
        line = {
            "ts": ts,
            "utterance": utt,
            "direct": {
                "intent": intent_direct,
                "domains": domains_direct,
                "intent_error": intent_err,
                "domain_error": dom_err,
            },
            "coordinator": {
                "intent": result.get("intent"),
                "domains": coord_domains,
                "ok": result.get("ok"),
                "result": result.get("result"),
                "error": result.get("error"),
            },
            "expectations": exp,
            "verdicts": verdict,
        }
        _write_jsonl(RUNNERS_LOG, line)

        # ---------- state snapshot ----------
        _write_jsonl(_state_log_path(), _snapshot_state(coord.state))

        # console echo (show coordinator domains, not direct)
        print(json.dumps({
            "utterance": utt,
            "intent_direct": intent_direct,
            "domains_coord": coord_domains,
            "ok": result.get("ok"),
            "provided_fields": (result.get("result") or {}).get("provided_fields"),
            "verdict": verdict["phrase_ok"],
        }, indent=2, ensure_ascii=False))

    print(f"\nSummary: {passes} passed / {fails} failed / {len(phrases)} total")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phrases-file", help="Optional override: one utterance per line")
    ap.add_argument("--expectations-file", help="Optional override: YAML/JSON expectations")
    args = ap.parse_args()
    raise SystemExit(run(args.phrases_file, args.expectations_file))
