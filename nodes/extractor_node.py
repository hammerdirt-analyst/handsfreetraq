from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

class ExtractorOutput(BaseModel):
    updates: Dict[str, Any] = Field(default_factory=dict)
    narrate_paths: List[str] = Field(default_factory=list)
    declined_paths: List[str] = Field(default_factory=list)
    utterance_intent: Literal[
        "PROVIDE_DATA",
        "ASK_FIELD",
        "WHAT_IS_LEFT",
        "REQUEST_SUMMARY",
        "REQUEST_REPORT",
        "CORRECTION",
        "CONTROL",
        "SMALL_TALK"
    ]
    ask_field_targets: Optional[List[str]] = None
    guidance_candidates: Optional[List[dict]] = None
    confirmation_stub: str = ""

class MockExtractor:
    def extract(self, utterance: str) -> ExtractorOutput:
        text = (utterance or "").strip()
        low = text.lower()

        targets: Optional[List[str]] = None

        # intents
        if "report" in low:
            intent = "REQUEST_REPORT"
        elif "summary" in low:
            intent = "REQUEST_SUMMARY"
        elif "what's left" in low or "what is left" in low or "whats left" in low:
            intent = "WHAT_IS_LEFT"
        elif low.startswith("what ") and "name" in low:
            intent = "ASK_FIELD"
            targets = ["arborist_info.name"]
        elif low.startswith("what ") and "phone" in low:
            intent = "ASK_FIELD"
            targets = ["arborist_info.phone"]
        elif "species" in low or "tree type" in low:
            intent = "ASK_FIELD"
            targets = ["tree_description.type_common"]
        else:
            intent = "PROVIDE_DATA"

        narr_paths: List[str] = []
        # simple narrative routing
        if any(k in low for k in ["my name is", "arborist"]):
            narr_paths.append("arborist_info.narratives")
        if any(k in low for k in ["customer", "homeowner", "client"]):
            narr_paths.append("customer_info.narratives")
        if any(k in low for k in ["branch", "defect", "damage", "risk"]):
            narr_paths.append("risks.narratives")
        if any(k in low for k in ["target", "patio", "roof", "driveway"]):
            narr_paths.append("targets.narratives")
        if any(k in low for k in ["park", "school", "urban", "rural", "suburban", "site "]):
            narr_paths.append("area_description.narratives")
        if any(k in low for k in ["prune", "remove", "maintenance"]):
            narr_paths.append("recommendations.narratives")

        updates: Dict[str, Any] = {}
        # demo capture: arborist name
        if "my name is" in low:
            try:
                name = text.split("my name is", 1)[1].strip()
                updates = {"arborist_info": {"name": name}}
            except Exception:
                updates = {"arborist_info": {"name": text}}

        stub = "Noted." if (updates or narr_paths) else ""

        return ExtractorOutput(
            updates=updates,
            narrate_paths=sorted(set(narr_paths)),
            declined_paths=[],
            utterance_intent=intent,
            ask_field_targets=targets,
            guidance_candidates=None,
            confirmation_stub=stub,
        )
