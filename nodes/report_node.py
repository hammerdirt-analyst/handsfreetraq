from typing import Literal
from models import ReportState

class ReportNode:
    """
    Phase 1 placeholder: returns a simple 'not ready' string.
    """

    def handle(self, mode: Literal["summary", "report"], state: ReportState) -> str:
        return f"You have called the Report Node in {mode} mode. It is not ready."
