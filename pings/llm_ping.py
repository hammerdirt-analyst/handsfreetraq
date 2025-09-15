#!/usr/bin/env python3
"""
Quick sanity check for LangChain ChatOpenAI.

Usage:
  OPENAI_API_KEY=... python llm_ping.py "summarize this: DBH is 24 in; canopy width 30 ft"
  # or
  echo "write one sentence about trees" | OPENAI_API_KEY=... python llm_ping.py

Env:
  OPENAI_MODEL (optional, default: gpt-4o-mini)
  OPENAI_API_KEY (required)
"""
import os
import sys
import json
import dotenv

from pathlib import Path
import sys

# Resolve repo root as the parent of the `pings` folder
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

dotenv.load_dotenv()

def read_input() -> str:
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:]).strip()
    data = sys.stdin.read().strip()
    if data:
        return data
    print("No input provided on argv or stdin.", file=sys.stderr)
    sys.exit(2)

def main():
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
    except Exception as e:
        print("Import error. Install dependencies:\n  pip install -U langchain langchain-openai", file=sys.stderr)
        raise

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Missing OPENAI_API_KEY in environment.", file=sys.stderr)
        sys.exit(2)

    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    temperature = float(os.getenv("TEMP", "0.3"))

    text = read_input()

    # Minimal, safe prompts—just to exercise the path
    system_msg = SystemMessage(
        content=(
            "You are a concise assistant. Respond briefly. "
            "Do not include code fences unless asked."
        )
    )
    user_msg = HumanMessage(content=text)

    # Instantiate the LC Chat client
    llm = ChatOpenAI(model=model_name, temperature=temperature)

    # Call the model (LangChain v0.2 style)
    ai_msg = llm.invoke([system_msg, user_msg])

    # Extract text
    out_text = (ai_msg.content or "").strip()

    # Try to extract token usage (varies by LC/OpenAI versions)
    in_tok = out_tok = 0
    try:
        meta = getattr(ai_msg, "response_metadata", {}) or {}
        usage = meta.get("token_usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
    except Exception:
        pass
    if (in_tok, out_tok) == (0, 0):
        try:
            usage2 = getattr(ai_msg, "usage_metadata", {}) or {}
            in_tok = int(usage2.get("input_tokens", 0) or 0)
            out_tok = int(usage2.get("output_tokens", 0) or 0)
        except Exception:
            pass

    # Emit a compact, test-friendly JSON object to stdout
    print(json.dumps({
        "model": model_name,
        "temperature": temperature,
        "text": out_text,
        "tokens": {"in": in_tok, "out": out_tok},
        "raw_metadata": getattr(ai_msg, "response_metadata", None),
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Make failure obvious for CI/unit tests
        print(f"[llm_ping] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
