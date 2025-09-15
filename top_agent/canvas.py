from __future__ import annotations
from pathlib import Path
from typing import Dict, Optional

SECTION_TO_FILENAME = {
    "area_description": "outline_area_description.md",
    "tree_description": "outline_tree_description.md",
    "targets": "outline_targets.md",
    "risks": "outline_risks.md",
    "recommendations": "outline_recommendations.md",
}

class Canvas:
    def __init__(self, canvas_dir: Path):
        self.canvas_dir = canvas_dir

    def write_outline(self, section: str, text: str) -> str:
        fname = SECTION_TO_FILENAME.get(section, f"outline_{section}.md")
        p = self.canvas_dir / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text or "", encoding="utf-8")
        return str(p)

    def write_report(self, text: str) -> str:
        p = self.canvas_dir / "report.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text or "", encoding="utf-8")
        return str(p)
