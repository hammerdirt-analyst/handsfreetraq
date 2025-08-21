#!/usr/bin/env python3
# runners.py — Drive Coordinator with phrases + (optional) expectations.
# Logs:
#  - runners.log                (JSONL per phrase with verdicts)
#  - state_logs/state-YYYYMMDD.jsonl  (state snapshots after each turn)
#  - coordinator-tests.txt      (from Coordinator itself)

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

# ----- Your modules -----
from report_agent import Coordinator, classify_data_domains_llm  # adjust import if file name differs
from intent_llm import classify_intent_llm
from report_state import ReportState

# ------------- paths -------------
RUNNERS_LOG = "runners.log"

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _today_tag() -> str:
    return datetime.utcnow().strftime("%Y%m%d")

def _load_lines(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f.readlines() if ln.strip()]

def _load_expectations(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    if not os.path.exists(path):
        print(f"[warn] expectations file not found: {path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith(".json"):
            return json.load(f)
        # tiny YAML subset: list of dicts
        try:
            import yaml  # optional
            return yaml.safe_load(f)
        except Exception:
            # fallback: treat as JSON if yaml unavailable
            return json.load(f)

def _exp_for(utterance: str, expectations: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for e in expectations or []:
        if (e.get("text") or "").strip() == utterance.strip():
            return e
    return None

def _write_jsonl(path: str, obj: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def _state_log_path() -> str:
    os.makedirs("state_logs", exist_ok=True)
    return os.path.join("state_logs", f"state-{_today_tag()}.jsonl")

def _snapshot_state(state: ReportState) -> Dict[str, Any]:
    # Keep snapshot small but useful
    dmp = state.model_dump(exclude_none=False)
    return {
        "ts": _now_iso(),
        "provided_fields": sorted(state.meta.provided_fields),
        "arborist_info": dmp.get("arborist_info", {}),
        "customer_info": dmp.get("customer_info", {}),
        "tree_description": dmp.get("tree_description", {}),
        "area_description": dmp.get("area_description", {}),
        "risks": dmp.get("risks", {}),
        "recommendations": dmp.get("recommendations", {}),
    }

def run(phrases_file: str, expectations_file: Optional[str]) -> int:
    phrases = _load_lines(phrases_file)
    expectations_list = _load_expectations(expectations_file) or []
    if isinstance(expectations_list, dict):
        expectations_list = expectations_list.get("cases", [])

    coord = Coordinator()

    passes = 0
    fails = 0

    for utt in phrases:
        ts = _now_iso()

        # ---------- direct classifiers ----------
        try:
            intent_direct = classify_intent_llm(utt).intent
        except Exception as e:
            intent_direct = "INTENT_ERROR"
            intent_err = str(e)
        else:
            intent_err = None

        domains_direct = None
        dom_err = None
        if intent_direct == "PROVIDE_DATA":
            try:
                domains_direct = classify_data_domains_llm(utt)
            except Exception as e:
                dom_err = str(e)

        # ---------- coordinator ----------
        result = coord.handle_turn(utt)
        # Try to mirror domains from coordinator result (if any)
        coord_domains = (result.get("result") or {}).get("domains")

        # ---------- expectations + verdicts ----------
        exp = _exp_for(utt, expectations_list)
        verdict = {
            "intent_match": None,
            "domains_match": None,
            "expectations_ok": None,
            "phrase_ok": None,
        }

        if exp:
            # intent check
            if "intent" in exp:
                verdict["intent_match"] = (intent_direct == exp["intent"])
            # domain check
            if "domains" in exp:
                expected = sorted(exp["domains"])
                actual = sorted(domains_direct or [])
                verdict["domains_match"] = (expected == actual)
            # provided_fields_contains (optional)
            exp_pf = exp.get("provided_contains") or []
            if exp_pf and result.get("result"):
                got_pf = set((result["result"].get("provided_fields") or []))
                verdict["expectations_ok"] = all(p in got_pf for p in exp_pf)
            # overall
            checks = [v for v in [verdict["intent_match"], verdict["domains_match"], verdict["expectations_ok"]] if v is not None]
            verdict["phrase_ok"] = all(checks) if checks else True
        else:
            # no expectations — consider as pass if coordinator didn’t crash
            verdict["phrase_ok"] = bool(result.get("ok") is not False or result.get("error") is None)

        if verdict["phrase_ok"]:
            passes += 1
        else:
            fails += 1

        # ---------- log one line to runners.log ----------
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

        # Echo to console (compact)
        print(json.dumps({
            "utterance": utt,
            "intent": intent_direct,
            "domains": domains_direct,
            "ok": result.get("ok"),
            "provided_fields": (result.get("result") or {}).get("provided_fields"),
            "verdict": verdict["phrase_ok"],
        }, indent=2, ensure_ascii=False))

    # final summary
    print(f"\nSummary: {passes} passed / {fails} failed / {len(phrases)} total")
    return 0 if fails == 0 else 1

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--phrases-file", default="phrases.txt", help="One utterance per line")
    ap.add_argument("--expectations-file", default="expectations.yml", help="YAML or JSON expectations (optional)")
    args = ap.parse_args()
    raise SystemExit(run(args.phrases_file, args.expectations_file))
