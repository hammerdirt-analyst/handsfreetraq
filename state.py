from typing import List, Optional
from pydantic import BaseModel, Field

# ---- Section models (minimal Phase 1 skeleton) ----

class ArboristInfo(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    narratives: List[str] = Field(default_factory=list)

class Inspection(BaseModel):
    date: Optional[str] = None
    location_text: Optional[str] = None
    gps: Optional[dict] = None
    narratives: List[str] = Field(default_factory=list)

class TreeDescInitial(BaseModel):
    common_name: Optional[str] = None
    scientific_name: Optional[str] = None
    dbh_in: Optional[float] = None
    height_ft: Optional[float] = None
    crown: Optional[str] = None
    narratives: List[str] = Field(default_factory=list)

class DefectsRisk(BaseModel):
    narrative: Optional[str] = None
    targets: List[str] = Field(default_factory=list)
    prior_failures: Optional[str] = None
    narratives: List[str] = Field(default_factory=list)

class SiteHistory(BaseModel):
    narratives: List[str] = Field(default_factory=list)

class FormalRisk(BaseModel):
    risk_level: Optional[str] = None
    rationale: Optional[str] = None
    narratives: List[str] = Field(default_factory=list)

class PruningRemoval(BaseModel):
    narrative: Optional[str] = None
    scope: Optional[str] = None
    limitations: Optional[str] = None
    narratives: List[str] = Field(default_factory=list)

class OpinionRecommendation(BaseModel):
    recommendation: Optional[str] = None
    narratives: List[str] = Field(default_factory=list)

# ---- Global state + meta ----

class Meta(BaseModel):
    declined_paths: List[str] = Field(default_factory=list)

class ReportState(BaseModel):
    current_text: Optional[str] = None

    arborist_info: ArboristInfo = Field(default_factory=ArboristInfo)
    inspection: Inspection = Field(default_factory=Inspection)
    tree_desc_initial: TreeDescInitial = Field(default_factory=TreeDescInitial)
    defects_risk: DefectsRisk = Field(default_factory=DefectsRisk)
    site_history: SiteHistory = Field(default_factory=SiteHistory)
    formal_risk: FormalRisk = Field(default_factory=FormalRisk)
    pruning_removal: PruningRemoval = Field(default_factory=PruningRemoval)
    opinion_recommendation: OpinionRecommendation = Field(default_factory=OpinionRecommendation)

    meta: Meta = Field(default_factory=Meta)

    def model_merge_updates(self, updates: dict) -> "ReportState":
        """
        Shallow merge of a dict shaped like ReportState into this model.
        Only present keys are applied (Phase 1 simplicity).
        """
        data = self.model_dump()
        def _merge(dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    _merge(dst[k], v)
                else:
                    dst[k] = v
        _merge(data, updates or {})
        return self.__class__.model_validate(data)

# Utility: compute a simple "what's left" list (Phase 1, minimal)
REQUIRED_FIELDS = {
    "arborist_info": ["name", "email", "phone"],
    "inspection": ["date", "location_text"],
    "tree_desc_initial": ["common_name", "dbh_in", "height_ft", "crown"],
    "defects_risk": ["narrative"],
    "site_history": [],  # narrative-only (optional)
    "formal_risk": ["risk_level", "rationale"],
    "pruning_removal": ["narrative", "scope", "limitations"],
    "opinion_recommendation": ["recommendation"],
}

def compute_whats_left(state: ReportState) -> dict:
    """
    Returns {section: [missing_field, ...]} excluding any declined paths.
    """
    declined = set(state.meta.declined_paths or [])
    remaining = {}
    for section, fields in REQUIRED_FIELDS.items():
        obj = getattr(state, section)
        missing = []
        for f in fields:
            path = f"{section}.{f}"
            if path in declined:
                continue
            val = getattr(obj, f, None)
            if val in (None, "", []):
                missing.append(f)
        if missing:
            remaining[section] = missing
    return remaining
