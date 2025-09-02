"""
tests/full/conftest.py

Purpose
-------
Configuration specific to the `tests/full/` suite (live, end-to-end runs).

What this does
--------------
1) Ensures `coordinator_agent.COORD_LOG` points to the canonical log file
   under `coordinator_logs/coordinator-tests.txt`.
2) Truncates the log file once per test session, so a full run always
   starts with a clean log (easier to inspect what the current run did).
3) Provides a default `OPENAI_MODEL` ("gpt-4o-mini") if not already set,
   ensuring LLM-backed tests can run without extra setup.

Why
---
- Full tests exercise the coordinator with real LLM calls and logging,
  so they need a clean log file each run to verify stability and growth.
- Separate from root conftest to avoid truncating logs for unit/integration
  runs (which sometimes want to inspect accumulation).

File / module dependencies
--------------------------
- coordinator_agent (system under test; log path patched here)
- pytest (fixture system)
- os, pathlib (path setup and file truncation)
"""

import os
from pathlib import Path
import pytest
import coordinator_agent  # renamed module

@pytest.fixture(scope="session", autouse=True)
def prepare_log_dir_and_truncate_for_full_suite():
    """
    For tests/full/*:
      - Ensure the coordinator log path is the canonical repo path
      - Truncate once per session so these runs start clean
    """
    project_root = Path(__file__).resolve().parents[2]  # tests/full -> project root
    log_dir = project_root / "coordinator_logs"
    log_dir.mkdir(exist_ok=True)

    log_path = log_dir / "coordinator-tests.txt"
    coordinator_agent.COORD_LOG = str(log_path)

    # truncate at start of full suite
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("")

    os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
    yield
