"""
models.py — author: roger erismann
Pydantic models for structured arborist report state, with normalization and validation.
"""

from __future__ import annotations
from pydantic import field_validator, ValidationInfo
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator

NOT_PROVIDED = "NOT_PROVIDED"
# ---- Issue tracking ---------------------------------------------------------
class Issue(BaseModel):
    path: str
    action: str   # "normalized" | "rejected" | "coerced"
    detail: str

    # allow dict-like access used by tests
    def get(self, key: str, default=None):
        return getattr(self, key, default)

class IssueBucket(BaseModel):
    items: List[Issue] = Field(default_factory=list)

    def add(self, path: str, action: str, detail: str):
        self.items.append(Issue(path=path, action=action, detail=detail))

# ---- Enum synonym maps ------------------------------------------------------
_CONTEXT_MAP = {
    "residential": "suburban",
    "residential subdivision": "suburban",
    "neighborhood": "suburban",
    "city": "urban",
    "downtown": "urban",
    "central business district": "urban",
    "rural area": "rural",
}
_ALLOWED_CONTEXT = {"urban","suburban","rural","park","school","public_buildings","other"}
_NORMALIZE_CONTEXT = {
    "suburuban": "suburban",
    "suburuban ": "suburban",
    "suburuban neighborhood": "suburban",
    "city": "urban",
    "countryside": "rural",
}

_TRAFFIC_MAP = {
    "light": "low",
    "low": "low",
    "mod": "medium",
    "moderate": "medium",
    "medium": "medium",
    "high": "high",
    "heavy": "high",
}
_ALLOWED_TRAFFIC = {"low", "medium", "high"}

# ---- helpers ---------------------------------------------------------------
def _trim(v: Optional[str]) -> str:
    if v is None:
        return NOT_PROVIDED
    v = " ".join(str(v).strip().split())
    return v if v else NOT_PROVIDED

def _normalize_numeric_str(v: Optional[str]) -> str:
    if v is None:
        return NOT_PROVIDED
    s = str(v)
    # keep digits, dot, minus; drop units like "ft", "in", "~"
    import re
    s = re.sub(r"[^\d\.\-]", " ", s)
    s = " ".join(s.split())
    if not s:
        return NOT_PROVIDED
    try:
        x = float(s)
    except Exception:
        return NOT_PROVIDED
    # keep canonical string (no trailing .0 unless integer)
    return str(int(x)) if abs(x - int(x)) < 1e-9 else str(x)

def _bounded_number_as_str(v: Optional[str], lo: float, hi: float,
                           ib: "IssueBucket | None", path: str) -> str:
    raw = _normalize_numeric_str(v)
    if raw == NOT_PROVIDED:
        return NOT_PROVIDED
    x = float(raw)
    if x < lo or x > hi:
        if ib: ib.add(path, "rejected", f"value {x} out of range [{lo}, {hi}]")
        return NOT_PROVIDED
    if str(v).strip() != raw:
        if ib: ib.add(path, "coerced", f"'{v}' → {raw}")
    return raw

def _enum_map(v: Optional[str], mapping: Dict[str, str], allowed: set[str],
              ib: "IssueBucket | None", path: str) -> str:
    t = _trim(v)
    if t == NOT_PROVIDED:
        return t
    norm = mapping.get(t.lower(), t.lower())
    if norm not in allowed:
        if ib: ib.add(path, "rejected", f"'{t}' not in {sorted(allowed)}")
        return NOT_PROVIDED
    if norm != t.lower():
        if ib: ib.add(path, "normalized", f"'{t}' → '{norm}'")
    return norm

# Simple validators
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DIGIT_STRIP = re.compile(r"\D+")
_US_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
_US_STATE_RE = re.compile(r"^[A-Za-z]{2}$")


def _normalize_numeric_str(v: str) -> str:
    if v == NOT_PROVIDED:
        return v
    try:
        s = str(v).strip()
        # Support inputs like "42 ft" -> "42" by stripping non-number suffix/prefix
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return NOT_PROVIDED
        num = float(m.group(0))
        if abs(num - int(num)) < 1e-9:
            return str(int(num))
        return str(round(num, 2))
    except Exception:
        return NOT_PROVIDED


# -----------------------------
# Shared / primitive components
# -----------------------------

class Address(BaseModel):
    street: str = Field(default=NOT_PROVIDED)
    city: str = Field(default=NOT_PROVIDED)
    state: str = Field(default=NOT_PROVIDED)
    postal_code: str = Field(default=NOT_PROVIDED)
    country: str = Field(default="US")

    @field_validator("state")
    @classmethod
    def _validate_state(cls, v: str) -> str:
        if v == NOT_PROVIDED:
            return v
        vv = v.strip().upper()
        return vv if _US_STATE_RE.match(vv) else NOT_PROVIDED

    @field_validator("postal_code")
    @classmethod
    def _validate_zip(cls, v: str) -> str:
        if v == NOT_PROVIDED:
            return v
        vv = v.strip()
        return vv if _US_ZIP_RE.match(vv) else NOT_PROVIDED


# -----------------------------
# Section models
# -----------------------------

class ArboristInfo(BaseModel):
    name: str = Field(default=NOT_PROVIDED)
    company: str = Field(default=NOT_PROVIDED)
    phone: str = Field(default=NOT_PROVIDED)
    email: str = Field(default=NOT_PROVIDED)
    address: Address = Field(default_factory=Address)
    license: str = Field(default=NOT_PROVIDED)
    narratives: List[str] = Field(default_factory=list)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        if v == NOT_PROVIDED:
            return v
        digits = _DIGIT_STRIP.sub("", v)
        return v.strip() if len(digits) >= 10 else NOT_PROVIDED

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        if v == NOT_PROVIDED:
            return v
        return v.strip() if _EMAIL_RE.match(v.strip()) else NOT_PROVIDED


class CustomerInfo(BaseModel):
    name: str = Field(default=NOT_PROVIDED)
    company: str = Field(default=NOT_PROVIDED)
    phone: str = Field(default=NOT_PROVIDED)
    email: str = Field(default=NOT_PROVIDED)
    address: Address = Field(default_factory=Address)
    narratives: List[str] = Field(default_factory=list)

    @field_validator("phone")
    @classmethod
    def _c_validate_phone(cls, v: str) -> str:
        if v == NOT_PROVIDED:
            return v
        digits = _DIGIT_STRIP.sub("", v)
        return v.strip() if len(digits) >= 10 else NOT_PROVIDED

    @field_validator("email")
    @classmethod
    def _c_validate_email(cls, v: str) -> str:
        if v == NOT_PROVIDED:
            return v
        return v.strip() if _EMAIL_RE.match(v.strip()) else NOT_PROVIDED


from pydantic import field_validator, ValidationInfo

class TreeDescription(BaseModel):
    type_common: str = NOT_PROVIDED
    type_scientific: str = NOT_PROVIDED
    height_ft: str = NOT_PROVIDED
    canopy_width_ft: str = NOT_PROVIDED
    crown_shape: str = NOT_PROVIDED
    dbh_in: str = NOT_PROVIDED
    trunk_notes: str = NOT_PROVIDED

    @field_validator("dbh_in", mode="before")
    @classmethod
    def _dbh_trim(cls, v, info: ValidationInfo):
        ib: IssueBucket | None = (info.context or {}).get("issues") if info else None
        if v is None:
            return NOT_PROVIDED
        s = str(v).strip()
        if s != str(v):
            if ib is not None:
                ib.add("tree_description.dbh_in", "coerced", f"trimmed whitespace -> '{s}'")
        return s or NOT_PROVIDED

    @field_validator("height_ft", mode="before")
    @classmethod
    def _height_bounds(cls, v, info: ValidationInfo):
        ib: IssueBucket | None = (info.context or {}).get("issues") if info else None
        if v is None or str(v).strip() == "":
            return NOT_PROVIDED
        try:
            val = float(str(v).strip())
        except Exception:
            if ib is not None:
                ib.add("tree_description.height_ft", "rejected", f"non-numeric value '{v}'")
            return NOT_PROVIDED

        if not (1 <= val <= 350):
            if ib is not None:
                ib.add("tree_description.height_ft", "rejected", f"value {val} out of range [1, 350]")
            return NOT_PROVIDED

        # keep original textual field but normalized formatting
        sval = str(int(val)) if val.is_integer() else str(val)
        if str(v).strip() != sval and ib is not None:
            ib.add("tree_description.height_ft", "coerced", f"'{v}' -> '{sval}'")
        return sval





class AreaDescription(BaseModel):
    context: str = NOT_PROVIDED
    other_context_note: str = NOT_PROVIDED
    site_use: str = NOT_PROVIDED
    foot_traffic_level: str = NOT_PROVIDED

    @field_validator("context", mode="before")
    @classmethod
    def _ctx(cls, v, info: ValidationInfo):
        ib: IssueBucket | None = (info.context or {}).get("issues") if info else None
        if v is None or (isinstance(v, str) and not v.strip()):
            return NOT_PROVIDED
        s = str(v).strip().lower()

        if s in _NORMALIZE_CONTEXT:
            norm = _NORMALIZE_CONTEXT[s]
            if ib is not None:
                ib.add("area_description.context", "normalized", f"'{s}' -> '{norm}'")
            return norm

        if s not in _ALLOWED_CONTEXT:
            if ib is not None:
                ib.add("area_description.context", "rejected", f"'{s}' not in {sorted(_ALLOWED_CONTEXT)}")
            return NOT_PROVIDED

        return s



class TargetItem(BaseModel):
    label: str = Field(default=NOT_PROVIDED)
    damage_modes: List[str] = Field(default_factory=list)
    proximity_note: str = Field(default=NOT_PROVIDED)
    occupied_frequency: str = Field(default=NOT_PROVIDED)
    narratives: List[str] = Field(default_factory=list)


class TargetsSection(BaseModel):
    items: List[TargetItem] = Field(default_factory=list)
    narratives: List[str] = Field(default_factory=list)


class RiskItem(BaseModel):
    description: str = Field(default=NOT_PROVIDED)
    likelihood: str = Field(default=NOT_PROVIDED)
    severity: str = Field(default=NOT_PROVIDED)
    rationale: str = Field(default=NOT_PROVIDED)
    narratives: List[str] = Field(default_factory=list)


class RisksSection(BaseModel):
    items: List[RiskItem] = Field(default_factory=list)
    narratives: List[str] = Field(default_factory=list)


class RecommendationDetail(BaseModel):
    narrative: str = Field(default=NOT_PROVIDED)
    scope: str = Field(default=NOT_PROVIDED)
    limitations: str = Field(default=NOT_PROVIDED)
    notes: str = Field(default=NOT_PROVIDED)


class RecommendationsSection(BaseModel):
    pruning: RecommendationDetail = Field(default_factory=RecommendationDetail)
    removal: RecommendationDetail = Field(default_factory=RecommendationDetail)
    continued_maintenance: RecommendationDetail = Field(default_factory=RecommendationDetail)
    narratives: List[str] = Field(default_factory=list)


# -----------------------------
# Meta & root state
# -----------------------------

class Meta(BaseModel):
    declined_paths: List[str] = Field(default_factory=list)
    issues: List[Issue] = Field(default_factory=list)

class ReportState(BaseModel):
    # raw utterance last heard
    current_text: str = Field(default="")

    # Sections (definitive list)
    arborist_info: ArboristInfo = Field(default_factory=ArboristInfo)
    customer_info: CustomerInfo = Field(default_factory=CustomerInfo)
    tree_description: TreeDescription = Field(default_factory=TreeDescription)
    area_description: AreaDescription = Field(default_factory=AreaDescription)
    targets: TargetsSection = Field(default_factory=TargetsSection)
    risks: RisksSection = Field(default_factory=RisksSection)
    recommendations: RecommendationsSection = Field(default_factory=RecommendationsSection)

    # Global meta
    meta: Meta = Field(default_factory=Meta)

    # --- Utility: shallow merge updates dict (keys mirror the model structure) ---
    def model_merge_updates(self, updates: dict | BaseModel | None, issues: IssueBucket | None = None) -> "ReportState":
        # Normalize updates to a plain dict (accept None and Pydantic models)
        if updates is None:
            updates_dict = {}
        elif hasattr(updates, "model_dump"):
            updates_dict = updates.model_dump(exclude_none=True)
        elif isinstance(updates, dict):
            updates_dict = updates
        else:
            updates_dict = {}

        data = self.model_dump()

        # 2) Shallow recursive merge
        def _merge(dst, src):
            for k, v in (src or {}).items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    _merge(dst[k], v)
                else:
                    dst[k] = v

        _merge(data, updates_dict)

        # 3) Validate with an IssueBucket (provided or temporary)
        ib = issues if issues is not None else IssueBucket()
        new_state = self.__class__.model_validate(data, context={"issues": ib})

        # 4) Append any issues gathered during validation into meta.issues
        try:
            if getattr(ib, "items", None):
                # normalize to list[dict]
                payload = []
                for it in ib.items:
                    if isinstance(it, dict):
                        payload.append(it)
                    elif hasattr(it, "model_dump"):
                        payload.append(it.model_dump())
                    else:
                        payload.append({
                            "path": str(getattr(it, "path", "?")),
                            "action": str(getattr(it, "action", "?")),
                            "detail": str(getattr(it, "detail", it)),
                        })
                if payload:
                    # ensure list exists
                    if not hasattr(new_state.meta, "issues") or new_state.meta.issues is None:
                        new_state.meta.issues = []
                    new_state.meta.issues.extend(payload)
        except Exception:
            # never let issue reporting break validation/merge
            pass

        return new_state


