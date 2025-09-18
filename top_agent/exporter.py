from __future__ import annotations
from pathlib import Path
from datetime import datetime

class Exporter:
    """
    Exports always go to: local_store/outbox/<job_number>/
    """
    def __init__(self, *, outbox_job_dir: Path):
        self.dir = outbox_job_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def write_md(self, markdown: str) -> str:
        out = self.dir / f"report_{self._ts()}.md"
        out.write_text(markdown, encoding="utf-8")
        return str(out)

    def write_pdf(self, markdown: str) -> str:
        # Placeholder: writes a .pdf file with markdown as content.
        # Replace with real md->pdf pipeline later.
        out = self.dir / f"report_{self._ts()}.pdf"
        out.write_text(markdown, encoding="utf-8")
        return str(out)

    def _ts(self) -> str:
        return datetime.utcnow().strftime("%Y%m%d_%H%M%S")
