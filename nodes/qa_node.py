from typing import Optional, Any
from models import ReportState

class QANode:
    def _get_by_path(self, root: Any, dotted: str) -> Optional[Any]:
        try:
            obj = root
            for part in dotted.split("."):
                if hasattr(obj, part):
                    obj = getattr(obj, part)
                elif isinstance(obj, dict):
                    obj = obj.get(part)
                else:
                    return None
            return obj
        except Exception:
            return None

    def answer_field(self, state: ReportState, path: str) -> Optional[str]:
        val = self._get_by_path(state, path)
        return val

