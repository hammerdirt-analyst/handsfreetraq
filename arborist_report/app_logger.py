# arborist_report/app_logger.py
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Keep the JSON lines small, stable, and machine-friendly
def _json_dumps(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

class _JsonlFormatter(logging.Formatter):
    """
    JSONL formatter with UTC timestamps and a tiny set of stable top-level fields.
    """
    # Ensure all timestamps are in UTC (avoid localtime drift in multi-host/log shipper setups)
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%SZ"),
            "lvl": record.levelname,
            "event": getattr(record, "event", None),
            "cid": getattr(record, "correlation_id", None),  # correlation id (turn/agent)
            "job_id": getattr(record, "job_id", None),
            "msg": record.getMessage() or None,
        }
        # Optional structured fields
        payload = getattr(record, "payload", None)
        if isinstance(payload, dict) and payload:
            base["payload"] = payload
        # Router/intent hints (optional)
        for k in ("intent", "service"):
            v = getattr(record, k, None)
            if v is not None:
                base[k] = v
        return _json_dumps(base)

_configured = False
_logger: Optional[logging.Logger] = None

def configure(
    *,
    root_dir: str | Path = "logs",
    filename: str = "app.jsonl",
    level: str | int = None,
    to_stdout: bool = True,
) -> None:
    """
    Global, one-time logger configuration.
    - Writes newline-delimited JSON to logs/app.jsonl (by default).
    - Also mirrors to stdout (INFO+), unless disabled.

    Env overrides:
      LOG_DIR, LOG_FILE, LOG_LEVEL
    """
    global _configured, _logger
    if _configured:
        return

    log_dir = Path(os.getenv("LOG_DIR", str(root_dir)))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / os.getenv("LOG_FILE", filename)

    lvl = level or os.getenv("LOG_LEVEL", "INFO")
    if isinstance(lvl, str):
        lvl = getattr(logging, lvl.upper(), logging.INFO)

    logger = logging.getLogger("arborist")
    logger.setLevel(lvl)
    logger.propagate = False  # avoid duplicate lines if root logger is configured elsewhere

    fmt = _JsonlFormatter()

    # File handler (append JSONL)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(lvl)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Optional stdout mirror
    if to_stdout:
        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    _logger = logger
    _configured = True

def get() -> logging.Logger:
    """Return the singleton arborist logger (auto-configure with defaults if needed)."""
    if not _configured:
        configure()
    return _logger  # type: ignore[return-value]

# ------------------------- Convenience entry points -------------------------

def log_event(
    event: str,
    payload: Dict[str, Any],
    *,
    correlation_id: Optional[str] = None,
    job_id: Optional[str] = None,
    level: int = logging.INFO,
    intent: Optional[str] = None,
    service: Optional[str] = None,
) -> None:
    """
    Generic structured event logger.
    Writes one JSON line with minimal stable keys + your payload.
    """
    get().log(
        level,
        event,
        extra={
            "event": event,
            "payload": payload,
            "correlation_id": correlation_id,
            "job_id": job_id,
            "intent": intent,
            "service": service,
        },
    )

def log_turn_packet(
    packet: Dict[str, Any],
    *,
    correlation_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> None:
    """
    Specialized helper for Coordinator/TopAgent to log a TurnPacket exactly once.
    Keeps the log schema consistent across the app.
    """
    intent = packet.get("intent")
    service = (packet.get("result") or {}).get("service")
    log_event(
        "TURN",
        packet,
        correlation_id=correlation_id or packet.get("correlation_id"),
        job_id=job_id,
        level=logging.INFO,
        intent=intent,
        service=service,
    )

def log_error_event(
    event: str,
    error_obj: Dict[str, Any],
    *,
    correlation_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> None:
    """
    Error-line helper that mirrors the error_handler envelope.
    """
    log_event(
        event,
        error_obj,
        correlation_id=correlation_id or error_obj.get("correlation_id"),
        job_id=job_id,
        level=logging.ERROR,
    )

# ------------------------- Coordinator-focused helpers -------------------------

def log_coordinator_event(
    event: str,
    payload: Dict[str, Any],
    *,
    correlation_id: Optional[str] = None,
    job_id: Optional[str] = None,
    level: int = logging.INFO,
) -> None:
    """
    Namespaced helper for Coordinator internal events.
    Produces an 'event' like 'Coordinator.CONTEXT_LOADED', etc.
    """
    log_event(f"Coordinator.{event}", payload, correlation_id=correlation_id, job_id=job_id, level=level)

def log_context_loaded(
    *,
    arborist_loaded: bool,
    customer_loaded: bool,
    location_loaded: bool,
    correlation_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> None:
    """
    Canonical 'context loaded' line, called from Coordinator.__init__.
    """
    log_coordinator_event(
        "CONTEXT_LOADED",
        {
            "arborist_loaded": bool(arborist_loaded),
            "customer_loaded": bool(customer_loaded),
            "location_loaded": bool(location_loaded),
        },
        correlation_id=correlation_id,
        job_id=job_id,
        level=logging.INFO,
    )
