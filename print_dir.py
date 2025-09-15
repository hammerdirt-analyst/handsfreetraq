#!/usr/bin/env python3
import os

OUTPUT_FILE = "project_tree.txt"
SKIP_DIRS = {".git", "__pycache__"}


def print_tree(start_path: str, out_file, prefix: str = "") -> None:
    """Recursively print the repo tree, filtering to .py files and environment.yml."""
    def include(entry: str, path: str) -> bool:
        if os.path.isdir(path):
            return os.path.basename(path) not in SKIP_DIRS
        return entry.endswith(".py") or entry == "environment.yml"

    entries = [e for e in os.listdir(start_path)
               if include(e, os.path.join(start_path, e))]
    entries.sort()

    for i, entry in enumerate(entries):
        path = os.path.join(start_path, entry)
        connector = "└── " if i == len(entries) - 1 else "├── "
        out_file.write(prefix + connector + entry + "\n")

        if os.path.isdir(path):
            extension = "    " if i == len(entries) - 1 else "│   "
            print_tree(path, out_file, prefix + extension)


if __name__ == "__main__":
    repo_root = os.path.dirname(os.path.abspath(__file__))  # arborist-agent root
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("Project tree for arborist-agent\n")
        f.write("================================\n")
        print_tree(repo_root, f)

    print(f"Wrote directory tree to {OUTPUT_FILE}")
