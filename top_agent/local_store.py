# top_agent/local_store.py
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from arborist_report.report_context import ReportContext
from arborist_report.report_state import ReportState


@dataclass(frozen=True)
class _Paths:
    root: Path
    job: str

    @property
    def report_dir(self) -> Path:
        return self.root / "reports" / self.job

    @property
    def inbox_dir(self) -> Path:
        return self.root / "inbox"

    @property
    def outbox_dir(self) -> Path:
        return self.root / "outbox" / self.job

    @property
    def attachments_dir(self) -> Path:
        return self.inbox_dir / "attachments"

    @property
    def canvas_dir(self) -> Path:
        return self.report_dir / "canvas"

    @property
    def context_json(self) -> Path:
        return self.report_dir / "context.json"

    @property
    def state_json(self) -> Path:
        return self.report_dir / "state.json"

    @property
    def turn_log_jsonl(self) -> Path:
        return self.report_dir / "turn_log.jsonl"

    @property
    def outline_stub(self) -> str:
        return "outline_{section}.md"

    @property
    def report_md(self) -> Path:
        return self.canvas_dir / "report.md"

    # Inbox canonical file (if present)
    @property
    def inbox_pending_jsonl(self) -> Path:
        return self.inbox_dir / "pending_jobs.jsonl"


class LocalStore:
    """
    Local, job-first storage for arborist agent.

    PUBLIC API (job-first, controller-facing):
    ------------------------------------------
      read_context(job) -> ReportContext
      read_state(job)   -> ReportState
      write_state(job, state) -> None
      append_turn_log(job, packet) -> None

      write_outline(job, *, section, text) -> str | None
      write_report(job, *, text) -> str | None
      export_report(job, *, fmt: "md" | "pdf") -> str

      list_reports() -> List[Dict[str, Any]]
      read_inbox_jobs() -> List[Dict[str, Any]]
      is_accepted(job) -> bool
      accept_job(job_obj_or_id, *, force=False) -> Tuple[bool, str]
      accept_all(filter_customer: Optional[str], *, force=False) -> List[Tuple[str, str]]
      merge_inbox_file(path, *, replace: bool, meta: Dict[str, Any]) -> None

    INTERNALS:
      - On-disk layout is private to LocalStore.
      - All filesystem logic lives here; the controller never constructs paths.
    """

    def __init__(self, root: str | Path = "local_store") -> None:
        self.root = Path(root)
        (self.root / "reports").mkdir(parents=True, exist_ok=True)
        (self.root / "inbox").mkdir(parents=True, exist_ok=True)
        (self.root / "outbox").mkdir(parents=True, exist_ok=True)

    # ------------------------------- helpers ---------------------------------

    def _p(self, job: str | int) -> _Paths:
        return _Paths(root=self.root, job=str(job))

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected object in {path}, got {type(data)}")
        return data

    @staticmethod
    def _write_json_atomic(path: Path, obj: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    @staticmethod
    def _maybe_read_last_jsonl_line(path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                last = None
                for line in f:
                    line = line.strip()
                    if line:
                        last = line
                return json.loads(last) if last else None
        except Exception:
            return None

    # ------------------------------ core I/O ----------------------------------

    def read_context(self, job: str | int) -> ReportContext:
        p = self._p(job)
        if not p.context_json.exists():
            raise FileNotFoundError(f"context.json not found for job {job} at {p.context_json}")
        raw = self._read_json(p.context_json)
        # allow both shapes: {"context": {...}} or {...}
        ctx_payload = raw.get("context", raw)
        return ReportContext.model_validate(ctx_payload)

    def read_state(self, job: str | int) -> ReportState:
        p = self._p(job)
        if not p.state_json.exists():
            # First-time: initialize an empty/default ReportState
            return ReportState()
        raw = self._read_json(p.state_json)
        # allow both shapes: {"state": {...}} or {...}
        state_payload = raw.get("state", raw)
        return ReportState.model_validate(state_payload)

    def write_state(self, job: str | int, state: ReportState) -> None:
        p = self._p(job)
        payload = {"state": state.model_dump()}
        self._write_json_atomic(p.state_json, payload)

    def append_turn_log(self, job: str | int, packet: Dict[str, Any]) -> None:
        p = self._p(job)
        # ensure minimal timestamp field in packet for list_reports freshness
        pkt = dict(packet)
        pkt.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self._append_jsonl(p.turn_log_jsonl, pkt)

    # ------------------------------ canvas I/O --------------------------------

    def write_outline(self, job: str | int, *, section: str, text: str) -> Optional[str]:
        """Writes canvas/outline_{section}.md (replace-on-write)."""
        p = self._p(job)
        p.canvas_dir.mkdir(parents=True, exist_ok=True)
        out = p.canvas_dir / p.outline_stub.format(section=section)
        out.write_text(text or "", encoding="utf-8")
        return str(out)

    def write_report(self, job: str | int, *, text: str) -> Optional[str]:
        """Writes canvas/report.md (replace-on-write)."""
        p = self._p(job)
        p.canvas_dir.mkdir(parents=True, exist_ok=True)
        p.report_md.write_text(text or "", encoding="utf-8")
        return str(p.report_md)

    # -------------------------------- export ----------------------------------

    def export_report(self, job: str | int, *, fmt: str) -> str:
        """
        Export the current job's report to outbox/<job>/.

        fmt: "md" | "pdf"
        - For "md": copies canvas/report.md if present; else synthesizes a minimal
          markdown from state. Returns the path of the exported artifact.
        - For "pdf": creates a simple placeholder PDF (text-only) if a true PDF
          renderer is not integrated. The goal is to place a file for operator flow.
        """
        fmt = fmt.lower()
        if fmt not in {"md", "pdf"}:
            raise ValueError("fmt must be 'md' or 'pdf'")
        p = self._p(job)
        p.outbox_dir.mkdir(parents=True, exist_ok=True)

        # Ensure we have some markdown content
        md_src = p.report_md
        if not md_src.exists():
            # synthesize a minimal draft from state
            state = self.read_state(job)
            synthesized = self._synthesize_markdown_from_state(state)
            self.write_report(job, text=synthesized)

        # refresh md_src pointer
        md_src = p.report_md
        if fmt == "md":
            dest = p.outbox_dir / "report.md"
            shutil.copyfile(md_src, dest)
            return str(dest)

        # naive "pdf": wrap text in a simple header; store as .pdf (placeholder)
        if fmt == "pdf":
            dest = p.outbox_dir / "report.pdf"
            # If a real PDF pipeline exists elsewhere, swap this out.
            content = md_src.read_text(encoding="utf-8")
            wrapper = f"*** ARBORIST REPORT (Job {job}) ***\n\n" + content
            dest.write_bytes(wrapper.encode("utf-8"))
            return str(dest)

        # unreachable because we validated fmt, but keep for clarity
        raise ValueError("unsupported format")

    @staticmethod
    def _synthesize_markdown_from_state(state: ReportState) -> str:
        """Very small, deterministic markdown from state for export fallback."""
        # Keep this deliberately minimal and stable.
        data = state.model_dump()
        return "# Arborist Report (Draft)\n\n" + "```json\n" + json.dumps(
            data, ensure_ascii=False, indent=2
        ) + "\n```"

    # ----------------------------- listings / inbox ----------------------------

    def list_reports(self) -> List[Dict[str, Any]]:
        """
        Return a compact list of accepted reports with friendly fields:
        [{"job_id": "...", "customer_name": "...", "address": "...", "last_turn_at": "..."}]
        """
        reports_root = self.root / "reports"
        out: List[Dict[str, Any]] = []
        if not reports_root.exists():
            return out
        for d in sorted([p for p in reports_root.iterdir() if p.is_dir()], key=lambda p: p.name):
            job = d.name
            p = self._p(job)
            if not p.context_json.exists():
                continue
            try:
                ctx = self.read_context(job)
            except Exception:
                continue
            cust_name = getattr(ctx.customer, "name", "") if getattr(ctx, "customer", None) else ""
            address = ""
            loc = getattr(ctx, "location", None)
            if loc:
                address = getattr(loc, "address_line", "") or getattr(loc, "address", "") or ""
            last_pkt = self._maybe_read_last_jsonl_line(p.turn_log_jsonl)
            last_ts = (last_pkt or {}).get("timestamp", "")
            out.append({
                "job_id": job,
                "customer_name": cust_name,
                "address": address,
                "last_turn_at": last_ts,
            })
        return out

    def read_inbox_jobs(self) -> List[Dict[str, Any]]:
        """
        Read staged jobs from inbox. Supports:
          - inbox/pending_jobs.jsonl (canonical)
          - any *.jsonl (one JSON object per line)
          - any *.json  (array or object)
        Returns a list of dicts; each should include at least job_id, customer, location.
        """
        inbox = self.root / "inbox"
        if not inbox.exists():
            return []
        jobs: List[Dict[str, Any]] = []

        # Preferred canonical file
        canon = inbox / "pending_jobs.jsonl"
        if canon.exists():
            jobs.extend(self._read_jsonl_list(canon))
            return jobs

        # Aggregate others
        for p in sorted(inbox.glob("*.jsonl")):
            jobs.extend(self._read_jsonl_list(p))
        for p in sorted(inbox.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    jobs.extend([o for o in data if isinstance(o, dict)])
                elif isinstance(data, dict):
                    jobs.append(data)
            except Exception:
                continue
        return jobs

    @staticmethod
    def _read_jsonl_list(path: Path) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            out.append(obj)
                    except Exception:
                        continue
        except FileNotFoundError:
            pass
        return out

    def is_accepted(self, job: str | int) -> bool:
        return self._p(job).report_dir.exists()

    def accept_job(self, job_obj_or_id: Any, *, force: bool = False) -> Tuple[bool, str]:
        """
        Promote an inbox job to reports/<job>/ with context.json scaffold.
        job_obj_or_id:
          - dict from read_inbox_jobs()
          - or a job_id (int/str) if the inbox entry is not needed.
        """
        # Resolve job number + context payload
        if isinstance(job_obj_or_id, dict):
            job_id = job_obj_or_id.get("job_id")
            if job_id is None:
                return False, "missing job_id"
            context_payload = job_obj_or_id.get("context", job_obj_or_id)
        else:
            job_id = str(job_obj_or_id)
            # If only an id is provided, we cannot infer a context structure; fail clearly.
            return False, "context payload required"

        p = self._p(job_id)
        p.report_dir.mkdir(parents=True, exist_ok=True)

        # If already accepted
        if p.context_json.exists() and not force:
            return True, "already accepted (use --force to overwrite context.json)"

        # Validate or store context
        try:
            # ensure it's convertible to our ReportContext
            ReportContext.model_validate(context_payload)
        except Exception as e:
            # Store as-is but warn; controller will surface error on read
            pass

        # Backup if overwriting
        if p.context_json.exists() and force:
            backup = p.context_json.with_suffix(".json.bak")
            shutil.copyfile(p.context_json, backup)

        self._write_json_atomic(p.context_json, {"context": context_payload})

        # Ensure minimal state scaffold if none exists
        if not p.state_json.exists():
            self.write_state(job_id, ReportState())

        return True, f"Accepted job {job_id}"

    def accept_all(self, filter_customer: Optional[str] = None, *, force: bool = False) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        filt = (filter_customer or "").lower().strip()
        for job in self.read_inbox_jobs():
            cust_name = ((job.get("customer") or {}).get("name") or "")
            if filt and filt not in cust_name.lower():
                continue
            ok, msg = self.accept_job(job, force=force)
            out.append((str(job.get("job_id")), msg))
        return out

    def merge_inbox_file(self, path: str | Path, *, replace: bool, meta: Dict[str, Any]) -> None:
        """
        Merge or replace inbox with a server-produced JSONL/JSON.
        - If replace=True, writes to inbox/pending_jobs.jsonl.
        - If append, appends to pending_jobs.jsonl (creating it if absent).
        """
        src = Path(path)
        inbox = self.root / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        dest = inbox / "pending_jobs.jsonl"

        def _yield_objs() -> Iterable[Dict[str, Any]]:
            if src.suffix.lower() == ".jsonl":
                with src.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            if isinstance(obj, dict):
                                yield obj
                        except Exception:
                            continue
            else:
                data = json.loads(src.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for o in data:
                        if isinstance(o, dict):
                            yield o
                elif isinstance(data, dict):
                    yield data

        if replace or not dest.exists():
            tmp = dest.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                for obj in _yield_objs():
                    f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            tmp.replace(dest)
        else:
            with dest.open("a", encoding="utf-8") as f:
                for obj in _yield_objs():
                    f.write(json.dumps(obj, ensure_ascii=False) + "\n")
