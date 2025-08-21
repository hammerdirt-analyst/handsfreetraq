# main.py — add a --backend flag and banner
import argparse
from agent_graph import Coordinator
import os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["auto", "openai", "hf"], default=os.getenv("LLM_BACKEND", "auto"))
    args = parser.parse_args()
    os.environ["LLM_BACKEND"] = args.backend

    print("Arborist Agent (Phase 1) — type 'exit' to quit.")
    coord = Coordinator()

    while True:
        try:
            user = input("You: ")
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.strip().lower() in {"exit", ":q"}:
            break
        reply = coord.handle_turn(user)
        print(f"Agent: {reply}")

if __name__ == "__main__":
    main()