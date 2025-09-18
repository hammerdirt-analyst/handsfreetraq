"""
Live routing accuracy evaluation (isolated from Coordinator execution).

- Uses the shared labeled corpus from tests/TEST_CORPUS.py (tuples OR dicts).
- Deterministic sampling by stable hash of the text; results don’t jiggle.
- Runs deterministic router first; falls back to the LLM backstop (temp=0.0) only if needed.
- Also writes a row-by-row log + summary to coordinator_logs/coordinator-tests.txt.
- Skips unless RUN_LIVE=1 to keep CI deterministic.

Env knobs:
- RUN_LIVE=1                         → enable the test
- ROUTING_SAMPLE_SIZE=100            → number of labeled rows to evaluate
- ROUTING_MIN_SERVICE_ACC=0.90       → min acceptable service accuracy
- ROUTING_MIN_JOINT_ACC=0.85         → min acceptable joint accuracy
- ROUTING_BACKSTOP_MIN_CONF=0.70     → confidence threshold to count as "clarify" when backstop is used
"""
from __future__ import annotations

import os
import json
import hashlib
import collections
from datetime import datetime
import pytest

import service_router
import service_classifier

# Pull the shared corpus. Expect a labeled list of either tuples or dicts.
# Tuples: (text, service, section) OR (text, service) with section inferred as None.
# Dicts:  {"text": ..., "service": ..., "section": ...}
from tests.TEST_CORPUS import TEST_CORPUS  # shared across the project

RUN_LIVE = os.getenv("RUN_LIVE") == "1"
SAMPLE_SIZE = int(os.getenv("ROUTING_SAMPLE_SIZE", "100"))
MIN_SERVICE_ACC = float(os.getenv("ROUTING_MIN_SERVICE_ACC", "0.90"))
MIN_JOINT_ACC = float(os.getenv("ROUTING_MIN_JOINT_ACC", "0.85"))
BACKSTOP_MIN_CONF = float(os.getenv("ROUTING_BACKSTOP_MIN_CONF", "0.70"))

ALLOWED_SERVICES = {
    "MAKE_CORRECTION",
    "SECTION_SUMMARY",
    "OUTLINE",
    "MAKE_REPORT_DRAFT",
    "NONE",
}

# ------------------------------
# Logging setup (shared log file)
# ------------------------------
try:
    import coordinator_agent  # reuses the same log path your other tests use
    LOG_PATH = getattr(coordinator_agent, "COORD_LOG", None)
except Exception:
    coordinator_agent = None
    LOG_PATH = None

if not LOG_PATH:
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    LOG_DIR = os.path.join(PROJECT_ROOT, "coordinator_logs")
    os.makedirs(LOG_DIR, exist_ok=True)
    LOG_PATH = os.path.join(LOG_DIR, "coordinator-tests.txt")
    if coordinator_agent is not None:
        coordinator_agent.COORD_LOG = LOG_PATH  # make visible to others

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def _log(kind: str, payload: dict) -> None:
    """Append a single JSON record to the shared coordinator log."""
    rec = {"ts": _now_iso(), "kind": kind, **payload}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# ------------------------------
# Helpers
# ------------------------------
def _stable_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def _normalize_row(row):
    """Accept either tuple/list or dict; return dict(text, service, section) or None to skip."""
    if isinstance(row, dict):
        text = row.get("text")
        service = row.get("service")
        section = row.get("section", None)
    elif isinstance(row, (tuple, list)):
        if len(row) == 3:
            text, service, section = row
        elif len(row) == 2:
            text, service = row
            section = None
        else:
            return None
    else:
        return None

    if not text or not service:
        return None
    if isinstance(section, str) and section.lower() in {"none", "null", ""}:
        section = None
    if service not in ALLOWED_SERVICES:
        return None
    return {"text": str(text), "service": str(service), "section": section}

pytestmark = pytest.mark.live

@pytest.mark.skipif(not RUN_LIVE, reason="Set RUN_LIVE=1 to run live routing accuracy eval")
def test_routing_accuracy_live():
    assert isinstance(TEST_CORPUS, (list, tuple)) and TEST_CORPUS, "TEST_CORPUS must be a non-empty list/tuple"

    # Normalize + filter to labeled examples
    rows = []
    for r in TEST_CORPUS:
        n = _normalize_row(r)
        if n is not None:
            rows.append(n)
    assert rows, "No labeled rows found in TEST_CORPUS"

    # Deterministic sampling by hash of text
    rows = sorted(rows, key=lambda r: _stable_key(r["text"]))
    subset = rows[: max(1, min(SAMPLE_SIZE, len(rows)))]

    # Counters
    det_hits = 0
    backstop_calls = 0
    clarify_count = 0  # backstop used but low confidence or none
    service_hits = 0
    joint_hits = 0
    conf_mat = collections.Counter()  # (gold_service, pred_service) -> count

    clf = service_classifier.ServiceRouterClassifier()

    _log("routing_eval_start", {"n": len(subset), "sample_size": SAMPLE_SIZE})

    for row in subset:
        text = row["text"]
        gold_service = row["service"]
        gold_section = row.get("section", None)

        # Deterministic first
        det_service, det_section = service_router.classify_service(text)
        route_path = "deterministic"
        pred_conf = None

        if det_service != "NONE":
            det_hits += 1
            pred_service, pred_section = det_service, det_section
        else:
            route_path = "llm_backstop"
            backstop_calls += 1
            out = clf.extract_dict(text, temperature=0.0, max_tokens=128)
            res = out["result"]
            pred_service = res["service"]
            pred_section = res.get("section")
            pred_conf = float(res.get("confidence") or 0.0)
            if pred_service == "NONE" or pred_conf < BACKSTOP_MIN_CONF:
                clarify_count += 1

        pass_service = (pred_service == gold_service)
        pass_joint = pass_service and (pred_section == gold_section)

        if pass_service:
            service_hits += 1
        if pass_joint:
            joint_hits += 1
        conf_mat[(gold_service, pred_service)] += 1

        # Per-row log record
        _log(
            "routing_eval_row",
            {
                "text": text,
                "expected": {"service": gold_service, "section": gold_section},
                "predicted": {"service": pred_service, "section": pred_section, "confidence": pred_conf},
                "route_path": route_path,
                "pass_service": pass_service,
                "pass_joint": pass_joint,
            },
        )

    n = len(subset)
    service_acc = service_hits / n
    joint_acc = joint_hits / n

    # Summary log
    _log(
        "routing_eval_summary",
        {
            "n": n,
            "deterministic_hits": det_hits,
            "llm_backstop_calls": backstop_calls,
            "clarify_count": clarify_count,
            "service_acc": round(service_acc, 4),
            "joint_acc": round(joint_acc, 4),
            "thresholds": {
                "min_service_acc": MIN_SERVICE_ACC,
                "min_joint_acc": MIN_JOINT_ACC,
                "backstop_min_conf": BACKSTOP_MIN_CONF,
            },
            "confusion_by_service": [{"gold": g, "pred": p, "count": c} for (g, p), c in sorted(conf_mat.items())],
        },
    )

    # Console printouts for local dev
    print("\nRouting accuracy (service only):", f"{service_acc:.3f}")
    print("Routing accuracy (service + section):", f"{joint_acc:.3f}")
    print("Deterministic hits:", det_hits, "/", n)
    print("LLM backstop calls:", backstop_calls)
    print("Clarify count:", clarify_count)
    print("Confusion (service-level):")
    for (gold, pred), c in sorted(conf_mat.items()):
        print(f"  gold={gold:17s} pred={pred:17s} : {c}")

    # Assertions
    assert service_acc >= MIN_SERVICE_ACC, f"Service accuracy {service_acc:.3f} < {MIN_SERVICE_ACC} (n={n})"
    assert joint_acc >= MIN_JOINT_ACC, f"Joint accuracy {joint_acc:.3f} < {MIN_JOINT_ACC} (n={n})"
