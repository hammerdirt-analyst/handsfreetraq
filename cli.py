#!/usr/bin/env python3
"""
Arborist Agent CLI

Purpose
-------
Operate Arborist report jobs locally and drive a conversational session with
the Coordinator / TopChatAgent.

What changed (UX-overview)
--------------------------
- Once you start `chat` on a job, you can run *all* useful actions as slash
  commands inside the same session — no more re-running `python cli.py <cmd>`.
- New in-chat commands cover summaries, outlines, drafts, corrections, navigation,
  and exports. These commands map to routed intents so they behave exactly like
  natural language messages, but save typing and reduce ambiguity.

Top-level entrypoints (unchanged)
---------------------------------
- reports list [--customer STR]
- reports create --context CONTEXT.json|yaml [--model NAME] [--no-rephrase]
- jobs inbox [--customer STR]
- jobs accept [--job ID ...] [--customer STR] [--all] [--force]
- jobs merge --file PATH [--append] [--source LABEL]
- chat [--job ID | --context CONTEXT.json|yaml] [--model NAME] [--no-rephrase]
- ask  (--job ID | --context CONTEXT) --text "MESSAGE" [--json] [--model NAME] [--no-rephrase]
- export --job ID --fmt md|pdf

New/expanded in-session slash commands
--------------------------------------
(available only after `chat` starts on a job)

- /help
    Show available commands and short examples.

- /summary <section>
    Ask for a prose section summary. Example: `/summary risks`

- /outline [section|current]
    Ask for an outline of a section. Example: `/outline tree_description`
    If omitted or `current`, uses the coordinator's current section cursor.

- /draft
    Request a full report draft.

- /correct <section>: <text>
    Apply a correction (overwrite semantics). Example:
      `/correct risks: replace item 2 with "Dead limb over driveway"`

- /go <section>
    Move the coordinator's cursor to a section for subsequent free-form input.
    Example: `/go targets`

- /export md|pdf
    Export the report artifact.

- /show packet
    Print the last TurnPacket (for debugging/inspection).

- /jobs
    Show inbox jobs.

- /accept <job_id>
    Accept an inbox job into local reports.

- /quit
    Exit the chat session.

Notes
-----
- The new slash commands simply call the same `TopChatAgent.handle(...)` path with
  canonical phrasings (e.g., "outline <section>", "make a full report draft"),
  so they exercise the exact same routing logic and thresholds as natural text.
- `/go <section>` updates the Coordinator's cursor so unscoped statements you send
  right after will be treated as belonging to that section.

"""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from arborist_report.report_context import ReportContext
from top_agent.local_store import LocalStore
from top_agent.controller import TopChatAgent

# ---------------- utils ----------------

def _load_context_from_file(p: str | Path) -> ReportContext:
    import json as _json
    try:
        import yaml as _yaml
    except Exception:
        _yaml = None
    p = Path(p)
    raw: Dict[str, Any]
    if _yaml and p.suffix.lower() in (".yaml", ".yml"):
        raw = _yaml.safe_load(p.read_text(encoding="utf-8"))
    else:
        raw = _json.loads(p.read_text(encoding="utf-8"))
    return ReportContext.model_validate(raw)  # pydantic v2

def _fmt_inbox_line(job: Dict[str, Any], accepted: bool) -> str:
    j = job.get("job_id")
    cust = ((job.get("customer") or {}).get("name") or "")
    addr_state = ((job.get("customer") or {}).get("address") or {})
    addr = addr_state.get("street","")
    flag = "[accepted]" if accepted else ""
    return f"{str(j):>6} | {cust[:24]:24} | {addr[:28]:28} {flag}"

def _print_chat_help():
    print(
        "Commands:\n"
        "  /help                               Show this help\n"
        "  /summary <section>                  Prose summary for a section (e.g., risks)\n"
        "  /outline [section|current]          Outline for a section (or current cursor)\n"
        "  /draft                              Full report draft\n"
        "  /correct <section>: <text>          Overwrite-style correction\n"
        "  /go <section>                       Set current section cursor\n"
        "  /export md|pdf                      Export report artifact\n"
        "  /show packet                        Show last TurnPacket\n"
        "  /jobs                               List inbox jobs\n"
        "  /accept <job_id>                    Accept an inbox job\n"
        "  /quit                               Exit\n"
    )

# ---------------- reports ----------------

def cmd_reports_list(args):
    store = LocalStore()
    rows = store.list_reports()
    if args.customer:
        rows = [r for r in rows if args.customer.lower() in (r.get("customer_name","").lower())]
    if not rows:
        print("No accepted reports.")
        return 0
    # NB: LocalStore.list_reports returns 'job_id'
    for r in rows:
        print(f"{str(r.get('job_id','')):>6} | {r.get('customer_name','')[:24]:24} | {r.get('address','')[:28]:28} | {r.get('last_turn_at','')}")
    return 0

def cmd_reports_create(args):
    if not args.context:
        print("--context is required", file=sys.stderr)
        return 2
    ctx = _load_context_from_file(args.context)
    job = getattr(ctx, "job_id", None) or ctx.model_dump().get("job_id")
    if job is None:
        print("Context must include 'job_id'", file=sys.stderr)
        return 2
    store = LocalStore()
    agent = TopChatAgent(store, rephrased=not args.no_rephrase)
    agent.open_or_create(job_number=job, context=ctx)
    print(f"Report created: {job}")
    return 0

# ---------------- jobs (inbox) ----------------

def cmd_jobs_inbox(args):
    store = LocalStore()
    jobs = store.read_inbox_jobs()
    if args.customer:
        jobs = [j for j in jobs if args.customer.lower() in ((j.get("customer") or {}).get("name","").lower())]
    if not jobs:
        print("Inbox empty.")
        return 0
    for j in jobs:
        print(_fmt_inbox_line(j, store.is_accepted(j.get("job_id"))))
    return 0

def cmd_jobs_accept(args):
    store = LocalStore()
    if args.all:
        out = store.accept_all(filter_customer=args.customer, force=args.force)
        if not out:
            print("Nothing to accept.")
            return 0
        for job, msg in out:
            print(f"{job}: {msg}")
        return 0

    if not args.job and not args.customer:
        print("Provide --job <id> (repeatable) or --customer <substr>, or use --all", file=sys.stderr)
        return 2

    if args.job:
        for j in args.job:
            matches = [o for o in store.read_inbox_jobs() if str(o.get("job_id")) == str(j)]
            if not matches:
                print(f"{j}: not in inbox", file=sys.stderr)
                continue
            ok, msg = store.accept_job(matches[0], force=args.force)
            print(f"{j}: {msg}")

    if args.customer and not args.all:
        for job, msg in store.accept_all(filter_customer=args.customer, force=args.force):
            print(f"{job}: {msg}")
    return 0

def cmd_jobs_merge(args):
    store = LocalStore()
    store.merge_inbox_file(args.file, replace=not args.append, meta={"source": args.source or "local"})
    print("Inbox updated.")
    return 0

# ---------------- chat / ask / export ----------------

def _run_canned(agent: TopChatAgent, text: str) -> Dict[str, Any]:
    """Send a canonical command text through the same handle() path."""
    return agent.handle(text)

def cmd_chat(args):
    store = LocalStore()
    agent = TopChatAgent(store, rephrased=not args.no_rephrase)

    if args.job:
        try:
            agent.open_by_job(job_number=args.job)
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        job = args.job
    elif args.context:
        ctx = _load_context_from_file(args.context)
        job = getattr(ctx, "job_id", None) or ctx.model_dump().get("job_id")
        if job is None:
            print("Context must include 'job_id'", file=sys.stderr)
            return 2
        agent.open_or_create(job_number=job, context=ctx)
    else:
        print("Provide --job or --context", file=sys.stderr)
        return 2

    print(f"Chatting on job {job}. Type '/help' for commands. Natural text is fine too.")

    last_packet: Optional[Dict[str, Any]] = None
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not line:
            continue

        if line.startswith("/"):
            cmd = line[1:].strip().split(" ", 1)
            name = cmd[0].lower()
            arg = cmd[1].strip() if len(cmd) > 1 else ""

            if name == "quit":
                break

            elif name == "help":
                _print_chat_help()
                continue

            elif name == "export":
                fmt = (arg or "").lower()
                if fmt not in {"md","pdf"}:
                    print("usage: /export md|pdf"); continue
                out = agent.export(fmt)
                print(f"Exported to {out['path']}")
                continue

            elif name == "show":
                if arg != "packet":
                    print("usage: /show packet"); continue
                print(json.dumps(last_packet or {"note":"(no packet yet)"}, indent=2, ensure_ascii=False))
                continue

            elif name == "jobs":
                jobs = store.read_inbox_jobs()
                if not jobs:
                    print("Inbox empty.")
                else:
                    for j in jobs:
                        print(_fmt_inbox_line(j, store.is_accepted(j.get("job_id"))))
                continue

            elif name == "accept":
                target = (arg or "").strip()
                if not target:
                    print("usage: /accept <job_id>"); continue
                matches = [o for o in store.read_inbox_jobs() if str(o.get("job_id")) == str(target)]
                if not matches:
                    print(f"{target}: not in inbox"); continue
                ok, msg = store.accept_job(matches[0], force=False)
                print(f"{target}: {msg}")
                continue

            # ----- Conversational shortcuts -----

            elif name == "summary":
                section = arg.strip()
                if not section:
                    print("usage: /summary <section>"); continue
                pkt = _run_canned(agent, f"Summarize the {section} section.")
                last_packet = pkt["packet"]; print(pkt["reply"])
                if pkt.get("footer"): print(pkt["footer"])
                continue

            elif name == "outline":
                section = arg.strip()
                if not section or section.lower() == "current":
                    # Use current cursor; Coordinator will resolve if missing.
                    pkt = _run_canned(agent, "outline")
                else:
                    pkt = _run_canned(agent, f"outline {section}")
                last_packet = pkt["packet"]; print(pkt["reply"])
                if pkt.get("footer"): print(pkt["footer"])
                continue

            elif name == "draft":
                pkt = _run_canned(agent, "make a full report draft")
                last_packet = pkt["packet"]; print(pkt["reply"])
                if pkt.get("footer"): print(pkt["footer"])
                continue

            elif name == "correct":
                # Expect "<section>: <text>"
                if ":" not in arg:
                    print("usage: /correct <section>: <text>")
                    continue
                sec, txt = [x.strip() for x in arg.split(":", 1)]
                if not sec or not txt:
                    print("usage: /correct <section>: <text>")
                    continue
                pkt = _run_canned(agent, f"Correct the {sec} section: {txt}")
                last_packet = pkt["packet"]; print(pkt["reply"])
                if pkt.get("footer"): print(pkt["footer"])
                continue

            elif name == "go":
                sec = arg.strip().lower().replace(" ", "_")
                if sec not in {"area_description","tree_description","targets","risks","recommendations"}:
                    print("usage: /go <section> (area_description|tree_description|targets|risks|recommendations)")
                    continue
                # Update the Coordinator cursor in-place (safe to do)
                if not agent.coordinator:
                    print("internal: no coordinator available"); continue
                agent.coordinator.state.current_section = sec
                print(f"(cursor) current section → {sec}")
                continue

            else:
                print("Unknown command. Type /help for options.")
                continue

        # Natural language fall-through
        out = agent.handle(line)
        last_packet = out["packet"]
        print(out["reply"])
        if out.get("footer"):
            print(out["footer"])

    return 0

def cmd_ask(args):
    store = LocalStore()
    agent = TopChatAgent(store, rephrased=not args.no_rephrase)

    if args.context:
        ctx = _load_context_from_file(args.context)
        job = getattr(ctx, "job_id", None) or ctx.model_dump().get("job_id")
        if job is None:
            print("Context must include 'job_id'", file=sys.stderr)
            return 2
        agent.open_or_create(job_number=job, context=ctx)
    else:
        if not args.job:
            print("Provide --job or --context", file=sys.stderr); return 2
        try:
            agent.open_by_job(job_number=args.job)
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr); return 2
        job = args.job

    out = agent.handle(args.text)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(out["reply"])
        if out.get("footer"):
            print(out["footer"])
    return 0

def cmd_export(args):
    store = LocalStore()
    agent = TopChatAgent(store)
    try:
        agent.open_by_job(job_number=args.job)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr); return 2
    out = agent.export(args.fmt)
    print(out["path"])
    return 0

# ---------------- parser ----------------

def build_parser():
    p = argparse.ArgumentParser(prog="arborist")
    sub = p.add_subparsers(dest="cmd")

    # reports
    p_reports = sub.add_parser("reports", help="accepted reports (local)")
    sub_reports = p_reports.add_subparsers(dest="sub")
    pr_list = sub_reports.add_parser("list", help="list accepted reports")
    pr_list.add_argument("--customer", help="filter by customer substring")
    pr_list.set_defaults(func=cmd_reports_list)

    pr_create = sub_reports.add_parser("create", help="create a report from a context file")
    pr_create.add_argument("--context", required=True, help="path to context JSON/YAML (must include job_id)")
    pr_create.add_argument("--no-rephrase", action="store_true")
    pr_create.set_defaults(func=cmd_reports_create)

    # jobs (inbox)
    p_jobs = sub.add_parser("jobs", help="server-pushed jobs inbox")
    sub_jobs = p_jobs.add_subparsers(dest="sub")

    pj_inbox = sub_jobs.add_parser("inbox", help="list current inbox jobs")
    pj_inbox.add_argument("--customer", help="filter by customer substring")
    pj_inbox.set_defaults(func=cmd_jobs_inbox)

    pj_accept = sub_jobs.add_parser("accept", help="accept jobs from inbox into local reports")
    pj_accept.add_argument("--job", action="append", help="job_id (repeatable)")
    pj_accept.add_argument("--customer", help="filter by customer substring")
    pj_accept.add_argument("--all", action="store_true", help="accept all inbox jobs")
    pj_accept.add_argument("--force", action="store_true", help="overwrite existing context.json (backup old)")
    pj_accept.set_defaults(func=cmd_jobs_accept)

    pj_merge = sub_jobs.add_parser("merge", help="merge/replace inbox from a JSONL file")
    pj_merge.add_argument("--file", required=True, help="path to JSONL")
    pj_merge.add_argument("--append", action="store_true", help="append instead of replace")
    pj_merge.add_argument("--source", help="meta source label")
    pj_merge.set_defaults(func=cmd_jobs_merge)

    # chat
    p_chat = sub.add_parser("chat", help="interactive chat for a job")
    p_chat.add_argument("--job", help="job_id (use after accept/create)")
    p_chat.add_argument("--context", help="path to context JSON/YAML (first run)")
    p_chat.add_argument("--no-rephrase", action="store_true")
    p_chat.set_defaults(func=cmd_chat)

    # ask
    p_ask = sub.add_parser("ask", help="one-shot turn for a job")
    p_ask.add_argument("--job", help="job_id")
    p_ask.add_argument("--context", help="path to context JSON/YAML")
    p_ask.add_argument("--text", required=True)
    p_ask.add_argument("--json", action="store_true")
    p_ask.add_argument("--no-rephrase", action="store_true")
    p_ask.set_defaults(func=cmd_ask)

    # export
    p_exp = sub.add_parser("export", help="export report")
    p_exp.add_argument("--job", required=True)
    p_exp.add_argument("--fmt", required=True, choices=["md","pdf"])
    p_exp.set_defaults(func=cmd_export)

    return p

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    if args.cmd in ("reports","jobs") and not getattr(args, "sub", None):
        parser.parse_args([args.cmd, "-h"])
        return 0
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
