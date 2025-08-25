#!/usr/bin/env python3
# router_test.py
#
# Validates the coordinator’s multi-scope routing without hitting any LLMs.
# Adds: per-turn state diff logging (before → after) in compact JSON.

from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any, Dict, List, Optional

# We import the module (not just the class) so we can patch its globals that Coordinator uses.
import report_agent as _ra
from report_state import ReportState  # ensures current_section exists
from report_context import ReportContext

# ----------------------- Intent stub (LLM-free) -----------------------

class _IntentObj:
    def __init__(self, intent: str):
        self.intent = intent

_SERVICE_HINTS = (
    "summary", "summarize", "draft", "report",
    "what's left", "whats left", "q&a", "qa", "question"
)

def _classify_intent_stub(text: str):
    t = (text or "").lower()
    if any(h in t for h in _SERVICE_HINTS):
        return _IntentObj("REQUEST_SERVICE")
    return _IntentObj("PROVIDE_STATEMENT")

# ----------------------- Spy/Stub registry ----------------------------

SECTION_TO_NAME = {
    "tree_description": "TreeDescriptionExtractor",
    "area_description": "AreaDescriptionExtractor",
    "risks": "RisksExtractor",
    "targets": "TargetExtractor",
    "recommendations": "RecommendationsExtractor",
}

class _SpyExtractor:
    """
    Wraps a real (or fake) extractor. In 'stub' mode, returns deterministic
    captures; in 'spy' mode, calls the real extractor. Always records the
    intended extractor name to calls_log (matching expectations).
    """
    def __init__(self, section_id: str, real_cls: Any = None,
                 mode: str = "stub", calls_log: Optional[List[str]] = None):
        self.section_id = section_id
        self.real = real_cls() if (real_cls and mode == "spy") else None
        self.mode = mode
        self.calls_log = calls_log
        self.display_name = (real_cls.__name__ if (real_cls and mode == "spy")
                             else SECTION_TO_NAME[section_id])

    def extract_dict(self, text: str, **kwargs) -> Dict[str, Any]:
        # Record the name we expect in tests
        if self.calls_log is not None:
            self.calls_log.append(self.display_name)

        # Spy → call the real extractor
        if self.mode == "spy" and self.real is not None:
            return self.real.extract_dict(text, **kwargs)

        # Stub → deterministic capture keyed by section
        t = (text or "").lower()
        provided: List[str] = []
        updates: Dict[str, Any] = {}

        if self.section_id == "tree_description":
            if "dbh" in t:
                provided = ["tree_description.dbh_in"]
                updates = {"tree_description": {"dbh_in": "24"}}
            elif "height" in t:
                provided = ["tree_description.height_ft"]
                updates = {"tree_description": {"height_ft": "55"}}
            elif "canopy" in t:
                provided = ["tree_description.canopy_width_ft"]
                updates = {"tree_description": {"canopy_width_ft": "40"}}

        elif self.section_id == "area_description":
            if "foot traffic" in t:
                provided = ["area_description.foot_traffic_level"]
                updates = {"area_description": {"foot_traffic_level": "high"}}
            elif "site use" in t or "context" in t:
                provided = ["area_description.site_use"]
                updates = {"area_description": {"site_use": "school"}}

        elif self.section_id == "risks":
            if "risk" in t or "severity" in t or "likelihood" in t:
                provided = ["risks.items"]
                updates = {"risks": {"items": [{"description": text.strip()}]}}
        elif self.section_id == "targets":
            if any(k in t for k in ("target", "strike potential", "dwellings", "people", "property", "properties")):
                provided = ["targets.items"]
                updates = {"targets": {"items": [{"label": text.strip()}]}}

        elif self.section_id == "recommendations":
            if "prune" in t:
                provided = ["recommendations.pruning.narrative"]
                updates = {"recommendations": {"pruning": {"narrative": text.strip()}}}
            elif "remove" in t:
                provided = ["recommendations.removal.narrative"]
                updates = {"recommendations": {"removal": {"narrative": text.strip()}}}
            elif "maintenance" in t:
                provided = ["recommendations.continued_maintenance.narrative"]
                updates = {"recommendations": {"continued_maintenance": {"narrative": text.strip()}}}

        return {"provided_fields": provided, "result": {"updates": updates}}

class _SpyRegistry:
    def __init__(self, real_required_map: Dict[str, Any],
                 mode: str = "stub", calls_log: Optional[List[str]] = None):
        self.real_required_map = real_required_map  # section_id -> real class
        self.mode = mode
        self.calls_log = calls_log

    def get(self, section: str):
        real = self.real_required_map.get(section)
        return _SpyExtractor(section, real_cls=real, mode=self.mode, calls_log=self.calls_log)

def _install_monkeypatches(mode: str, calls_log: List[str]) -> None:
    """
    Patch the symbols that Coordinator actually uses inside report_agent.
    Must be called BEFORE instantiating Coordinator.
    """
    # 1) Intent
    _ra.classify_intent_llm = _classify_intent_stub  # Coordinator uses this symbol

    # 2) Registry factory
    import extractor_registry as _reg_mod
    real_required = getattr(_reg_mod, "REQUIRED_SECTIONS", {
        "tree_description": None,
        "area_description": None,
        "risks": None,
        "recommendations": None,
        "targets": None,  # NEW
    })

    def _default_registry_stub():
        return _SpyRegistry(real_required_map=real_required, mode=mode, calls_log=calls_log)

    _ra.default_registry = _default_registry_stub  # Coordinator uses this symbol

# ----------------------- Helpers: state snapshot & diff ----------------------

def _snapshot_state(state: ReportState) -> Dict[str, Any]:
    """
    Returns a plain dict snapshot of the ReportState.
    Works with Pydantic v2 model_dump(); falls back to __dict__ shallow copy.
    """
    try:
        return state.model_dump()  # type: ignore[attr-defined]
    except Exception:
        # best-effort; shallow copy is fine for comparisons here
        return copy.deepcopy(getattr(state, "__dict__", {}))

def _walk(obj: Any, prefix: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            newp = f"{prefix}.{k}" if prefix else k
            yield from _walk(v, newp)
    elif isinstance(obj, list):
        yield (prefix, obj)
    else:
        yield (prefix, obj)

def _diff_state(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Produces a list of {path, before, after} for any changed leaf (or non-empty list) value.
    """
    b_map = dict(_walk(before))
    a_map = dict(_walk(after))
    paths = sorted(set(b_map.keys()) | set(a_map.keys()))
    diffs: List[Dict[str, Any]] = []
    for p in paths:
        b = b_map.get(p, None)
        a = a_map.get(p, None)
        if b != a:
            diffs.append({"path": p, "before": b, "after": a})
    return diffs

def _filter_diffs_to_expected(diffs: List[Dict[str, Any]], expected_paths: List[str] | None) -> List[Dict[str, Any]]:
    if not expected_paths:
        return diffs
    exp = set(expected_paths)
    # Keep exact matches, and also keep parent/child relationships for visibility.
    out: List[Dict[str, Any]] = []
    for d in diffs:
        p = d["path"]
        if p in exp:
            out.append(d)
            continue
        # Parent of expected or child of expected also useful
        if any(p.startswith(e + ".") or e.startswith(p + ".") for e in exp):
            out.append(d)
    return out

def _fmt_segments(segments: Optional[List[Dict[str, Any]]]) -> str:
    if not segments:
        return "[]"
    return "[" + ",".join(f"{s.get('section')}:{s.get('note')}" for s in segments) + "]"

# ----------------------- Loader / Context -----------------------------------

def _load_spec(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Spec must be a JSON array of test cases.")
    return data

def _mk_context() -> ReportContext:
    """
    Build a valid ReportContext for tests.
    Prefer the repo’s helper; otherwise fall back to a tiny literal.
    """
    try:
        from report_context import _build_context_from_testdata
        return _build_context_from_testdata()
    except Exception:
        from report_context import ArboristInfoCtx, CustomerInfoCtx, AddressCtx, LocationCtx
        return ReportContext(
            arborist=ArboristInfoCtx(
                name="Test Arborist", company="Test Co", phone="000-000-0000",
                email="arb@test.com", license="TEST-000",
                address=AddressCtx(street="1 Test St", city="Testville", state="CA",
                                   postal_code="00000", country="US"),
            ),
            customer=CustomerInfoCtx(
                name="Test Customer", phone="111-111-1111", email="cust@test.com",
                address=AddressCtx(street="2 Client Ave", city="Client City", state="CA",
                                   postal_code="11111", country="US"),
            ),
            location=LocationCtx(latitude=38.6732, longitude=-121.4520),
        )

# ----------------------- Runner ---------------------------------------------

def run(spec_path: str, mode: str) -> int:
    cases = _load_spec(spec_path)
    calls_log: List[str] = []

    # Patch BEFORE creating Coordinator
    _install_monkeypatches(mode=mode, calls_log=calls_log)

    ctx = _mk_context()
    coord = _ra.Coordinator(context=ctx)  # instantiate AFTER patches

    failures = 0
    for i, case in enumerate(cases, 1):
        # Reset per-case call log
        del calls_log[:]

        utter = case["utterance"]
        cursor_before = case["cursor_before"]
        expect = case["expect"]

        # Set cursor before the turn
        coord.state.current_section = cursor_before

        # --- snapshot before
        state_before = _snapshot_state(coord.state)

        out = coord.handle_turn(utter)

        # --- snapshot after + diff
        state_after = _snapshot_state(coord.state)
        full_diff = _diff_state(state_before, state_after)
        expected_paths = list((expect.get("fields") or {}).keys())
        diff_filtered = _filter_diffs_to_expected(full_diff, expected_paths or None)

        got_intent = out.get("intent")
        result = out.get("result") or {}
        routed = out.get("routed_to") or ""

        # Observed
        got_segments = result.get("segments") or []
        obs_sections = [s.get("section") for s in got_segments]
        got_final = result.get("final_section")

        ok = True
        exp_intent = expect.get("intent")

        if got_intent != exp_intent:
            ok = False
            print(f"[FAIL {i:02d}] intent mismatch: exp={exp_intent} got={got_intent}  utter={utter}")

        if exp_intent == "PROVIDE_STATEMENT":
            exp_dom = expect.get("domain") or {}
            exp_segments = exp_dom.get("segments") or []
            exp_final = exp_dom.get("final_section")
            exp_extractors = expect.get("extractor") or []
            exp_notes = expect.get("segment_notes")

            if obs_sections != exp_segments:
                ok = False
                print(f"[FAIL {i:02d}] segments mismatch: exp={exp_segments} got={obs_sections}  utter={utter}")

            if exp_final != got_final:
                ok = False
                print(f"[FAIL {i:02d}] final_section mismatch: exp={exp_final} got={got_final}  utter={utter}")

            if calls_log != exp_extractors:
                ok = False
                print(f"[FAIL {i:02d}] extractors mismatch: exp={exp_extractors} got={calls_log}  utter={utter}")

            if exp_notes is not None:
                got_notes = [s.get("note") for s in got_segments]
                if got_notes != exp_notes:
                    ok = False
                    print(f"[FAIL {i:02d}] segment notes mismatch: exp={exp_notes} got={got_notes}  utter={utter}")

        elif exp_intent == "REQUEST_SERVICE":
            # Service: no extractor calls; must not look like provide path
            if calls_log:
                ok = False
                print(f"[FAIL {i:02d}] service path invoked extractors unexpectedly: {calls_log}  utter={utter}")
            if routed == "cursor → extractor (with explicit-scope segments)":
                ok = False
                print(f"[FAIL {i:02d}] expected service path, but routed_to indicates provide-statement. utter={utter}")

        else:
            ok = False
            print(f"[FAIL {i:02d}] unknown expected intent: {exp_intent}  utter={utter}")

        # Existing summary line per case
        seg_view = _fmt_segments(got_segments)
        head = "OK" if ok else "FAIL"
        print(f"[{head:>4} {i:02d}] intent={got_intent} final={got_final} segs={seg_view} ex={calls_log}")

        # --- Append concise state diff JSON line for inspection
        print(json.dumps({
            "idx": i,
            "utterance": utter,
            "state_diff": diff_filtered if expected_paths else full_diff
        }, ensure_ascii=False))

        failures += (0 if ok else 1)

    total = len(cases)
    print(f"\nSummary: {total - failures} passed / {failures} failed / {total} total (mode={mode})")
    return 0 if failures == 0 else 1

# ----------------------- CLI ------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="Path to JSON spec with test cases.")
    ap.add_argument("--mode", choices=["stub", "spy"], default="stub",
                    help="Extractor mode: 'stub' for deterministic captures (default), 'spy' to call real extractors.")
    args = ap.parse_args()
    sys.exit(run(args.spec, args.mode))
