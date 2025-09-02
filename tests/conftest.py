"""
tests/conftest.py

Purpose
-------
Global pytest configuration for the entire test suite.

What this does
--------------
1) Loads `.env` values at session start so environment variables like
   OPENAI_API_KEY and OPENAI_MODEL are available for all tests.
2) Ensures `coordinator_agent.COORD_LOG` points to a canonical log path
   under `coordinator_logs/coordinator-tests.txt`.
   - This means all tests (unit, integration, full) can assume the same
     coordinator log location.
3) Provides a sensible fallback for `OPENAI_MODEL` ("gpt-4o-mini") if not
   set in the environment, so tests run even without manual config.

Why
---
- Keeps test configuration DRY: all tests see the same env + log setup.
- Prevents each test from writing logs in different locations.
- Ensures coordinator-agent code never explodes due to missing env vars.

File / module dependencies
--------------------------
- coordinator_agent (system under test; log path patched here)
- dotenv (loads local .env for dev convenience)
- pytest (fixture system)
- os, pathlib (path resolution / setup)
"""

import os
from pathlib import Path
import pytest

# load env once
try:
    import dotenv
    dotenv.load_dotenv()
except Exception:
    pass

import coordinator_agent  # renamed module

@pytest.fixture(scope="session", autouse=True)
def configure_coord_log_root():
    """
    Set the coordinator log path for ALL tests (unit/integration/full).
    We do NOT truncate here; the full/ suite will truncate at session start.
    """
    project_root = Path(__file__).resolve().parents[1]  # tests/ -> project root
    log_dir = project_root / "coordinator_logs"
    log_dir.mkdir(exist_ok=True)

    log_path = log_dir / "coordinator-tests.txt"
    coordinator_agent.COORD_LOG = str(log_path)

    os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
    yield
