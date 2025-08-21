#!/usr/bin/env python3
# runner.py — Harness to test intent + domain routing + Coordinator behavior

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ---- Project imports (adjust paths if your files are elsewhere) -------------
from agentgraph2 import Coordinator, classify_data_domains_llm  # domain LLM
from intent_llm import classify_intent_llm                      # intent LLM

# -----------------------------------------------------------------------------
HUMAN_LOG = "intent_domain_tests.txt"
JSONL_LOG = "runner_results.jsonl"


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _write_human_header(env: Dict[str, Any]) -> None:
    with open(HUMAN_LOG, "w", encoding="utf-8") as f:
        f.write("=" * 66 + "\n")
        f.write("Arborist Agent — Intent/Domain/Coordinator Runner\n")
        f.write(f"Started: {_now_iso()}\n")
        for k, v in env.items():
            f.write(f"{k}: {v}\n")
        f.write("=" * 66 + "\n\n")


def _append_human_block(block: str) -> None:
    with open(HUMAN_LOG, "a", encoding="utf-8") as f:
        f.write(block)
        if not block.endswith("\n"):
            f.write("\n")


def _reset_jsonl() -> None:
    with open(JSONL_LOG, "w", encoding="utf-8"):
        pass  # truncate


def _append_jsonl(obj: Dict[str, Any]) -> None:
    with open(JSONL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load_phrases(path: Optional[str]) -> List[str]:
    if not path:
        # Default built-in phrases
        return [
            "my name is roger erismann",
            "customer address is 12 oak ave, san jose ca 95112",
            "dbh is 24 inches and height 60 ft",
            "give me a short summary",
            "what's left?",
            "thanks!",
        ]
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.readlines()]
    return [ln for ln in lines if ln]


def _load_expectations(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _summarize_fields(provided: List[str], limit: int = 10) -> str:
    provided = sorted(set(provided))
    if not provided:
        return "none"
    if len(provided) <= limit:
        return ", ".join(provided)
    return ", ".join(provided[:limit]) + f" … (+{len(provided) - limit} more)"


def _verdict_line(ok: bool, msg: str) -> str:
    tag = "OK" if ok else "MISMATCH"
    return f"[{tag}] {msg}\n"


def _compare_sets(a: Optional[List[str]], b: Optional[List[str]]) -> Tuple[bool, str]:
    sa, sb = set(a or []), set(b or [])
    if sa == sb:
        return True, "sets match"
    add = ", ".join(sorted(sb - sa)) or "–"
    rmv = ", ".join(sorted(sa - sb)) or "–"
    return False, f"direct→coord add: {add} | drop: {rmv}"


def run(phrases_file: Optional[str], expectations_file: Optional[str]) -> int:
    # Environment snapshot
    env = {
        "LLM_BACKEND": os.getenv("LLM_BACKEND", "openai"),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", ""),
        "OUTLINES_VERSION": _safe_import_version("outlines"),
        "PYTHON": sys.version.split()[0],
    }

    _write_human_header(env)
    _reset_jsonl()

    phrases = _load_phrases(phrases_file)
    expectations = _load_expectations(expectations_file)

    coord = Coordinator()

    total = 0
    ok_count = 0
    mismatches: List[str] = []

    for phrase in phrases:
        total += 1
        block_lines: List[str] = []
        block_lines.append("=" * 64)
        block_lines.append(f"[{_now_iso()}] PHRASE")
        block_lines.append("-" * 64)
        block_lines.append(f'Utterance: "{phrase}"')

        # ---- Direct intent
        try:
            direct_intent = classify_intent_llm(phrase).intent
        except Exception as e:
            direct_intent = "INTENT_ERROR"
            block_lines.append(_verdict_line(False, f"direct intent error: {e}"))

        block_lines.append(f"Intent (direct): {direct_intent}")

        # ---- Direct domains (only if direct intent says PROVIDE_DATA)
        direct_domains: Optional[List[str]] = None
        if direct_intent == "PROVIDE_DATA":
            try:
                direct_domains = classify_data_domains_llm(phrase)
                block_lines.append(f"Domains (direct): {direct_domains}")
            except Exception as e:
                block_lines.append(_verdict_line(False, f"direct domain error: {e}"))

        # ---- Coordinator turn
        result = coord.handle_turn(phrase)  # prints its own JSON & logs internally
        coord_intent = result.get("intent")
        coord_ok = bool(result.get("ok"))
        coord_domains = None
        coord_updates = None
        coord_provided = None
        if result.get("result"):
            coord_domains = result["result"].get("domains")
            coord_updates = result["result"].get("updates")
            coord_provided = result["result"].get("provided_fields")

        block_lines.append(f"Intent (coordinator): {coord_intent}")
        if coord_domains is not None:
            block_lines.append(f"Domains (coordinator): {coord_domains}")

        # ---- Verdicts
        # Intent verdict
        intent_ok = (direct_intent == coord_intent)
        block_lines.append(_verdict_line(intent_ok, "intent match"))

        # Domain verdict (compare sets) when both are ProvideData
        domains_ok, domains_msg = True, "n/a"
        if direct_intent == "PROVIDE_DATA" and coord_intent == "PROVIDE_DATA":
            domains_ok, domains_msg = _compare_sets(direct_domains, coord_domains)
            block_lines.append(_verdict_line(domains_ok, f"domains — {domains_msg}"))
        else:
            block_lines.append(_verdict_line(True, "domains — skipped (non PROVIDE_DATA)"))

        # Provided fields summary
        if coord_intent == "PROVIDE_DATA":
            block_lines.append(
                f"Provided fields (coordinator): {_summarize_fields(coord_provided or [])}"
            )

        # Expectations check (optional)
        exp_ok = True
        exp_detail = "n/a"
        exp = expectations.get(phrase)
        if exp:
            # expected intent
            if "intent" in exp and exp["intent"] != coord_intent:
                exp_ok = False
                exp_detail = f"expected intent={exp['intent']} got={coord_intent}"

            # expected domains (set compare)
            if exp_ok and "domains" in exp and coord_domains is not None:
                s_ok, s_msg = _compare_sets(exp["domains"], coord_domains)
                if not s_ok:
                    exp_ok = False
                    exp_detail = f"domains mismatch: {s_msg}"

            # expected fields (any)
            if exp_ok and "expects_fields_any" in exp and coord_provided is not None:
                need_any = set(exp["expects_fields_any"])
                have = set(coord_provided)
                if need_any and need_any.isdisjoint(have):
                    exp_ok = False
                    exp_detail = f"none of expected fields present: {sorted(need_any)}"

            block_lines.append(_verdict_line(exp_ok, f"expectations — {exp_detail}"))

        # Aggregate verdict for this phrase
        this_ok = intent_ok and domains_ok and (coord_ok or coord_intent != "PROVIDE_DATA")
        if exp is not None:
            this_ok = this_ok and exp_ok

        if this_ok:
            ok_count += 1
            block_lines.append(_verdict_line(True, "PHRASE OK"))
        else:
            mismatches.append(phrase)
            block_lines.append(_verdict_line(False, "PHRASE MISMATCH"))

        block_lines.append("")  # spacer
        _append_human_block("\n".join(block_lines))

        # JSONL record
        rec = {
            "ts": _now_iso(),
            "utterance": phrase,
            "direct": {"intent": direct_intent, "domains": direct_domains},
            "coordinator": {
                "intent": coord_intent,
                "domains": coord_domains,
                "ok": coord_ok,
                "result": result.get("result"),
                "error": result.get("error"),
            },
            "expectations": exp or None,
            "verdicts": {
                "intent_match": intent_ok,
                "domains_match": domains_ok if (direct_intent == "PROVIDE_DATA" and coord_intent == "PROVIDE_DATA") else None,
                "expectations_ok": exp_ok if exp is not None else None,
                "phrase_ok": this_ok,
            },
        }
        _append_jsonl(rec)

        # Console one-liner
        if this_ok:
            short = _summarize_fields(coord_provided or [], limit=3) if coord_intent == "PROVIDE_DATA" else ""
            suffix = f" — fields: {short}" if short else ""
            print(f"[OK] {phrase!r}{suffix}")
        else:
            print(f"[MISMATCH] {phrase!r} — see {HUMAN_LOG}")

    # Final summary
    summary = f"\nSummary: {total} phrases — {ok_count} OK, {total - ok_count} with mismatches."
    _append_human_block(summary + "\n")
    print(summary)
    if mismatches:
        print("Mismatches:")
        for m in mismatches:
            print(" -", m)

    return 0 if ok_count == total else 1


def _safe_import_version(pkg: str) -> str:
    try:
        mod = __import__(pkg)
        return getattr(mod, "__version__", "?")
    except Exception:
        return "?"


def parse_args(argv: List[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run coordinator + intent/domain tests over phrases.")
    ap.add_argument("phrases_file", nargs="?", help="Optional path to a text file (one phrase per line).")
    ap.add_argument("--expect", dest="expectations_file", help="Optional JSON file with expectations per phrase.")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    sys.exit(run(args.phrases_file, args.expectations_file))
