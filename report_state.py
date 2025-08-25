# report_state.py
# Clean state models + helpers for the arborist agent

from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field

NOT_PROVIDED = "Not provided"

# =========================
# Section Models (STATE)
# =========================

class AddressState(BaseModel):
    street: str = Field(default=NOT_PROVIDED)
    city: str = Field(default=NOT_PROVIDED)
    state: str = Field(default=NOT_PROVIDED)
    postal_code: str = Field(default=NOT_PROVIDED)
    country: str = Field(default=NOT_PROVIDED)

class ArboristInfoState(BaseModel):
    name: str = Field(default=NOT_PROVIDED)
    company: str = Field(default=NOT_PROVIDED)
    phone: str = Field(default=NOT_PROVIDED)
    email: str = Field(default=NOT_PROVIDED)
    license: str = Field(default=NOT_PROVIDED)
    address: AddressState = Field(default_factory=AddressState)
    narratives: List[str] = Field(default_factory=list)

class CustomerInfoState(BaseModel):
    name: str = Field(default=NOT_PROVIDED)
    company: str = Field(default=NOT_PROVIDED)
    phone: str = Field(default=NOT_PROVIDED)
    email: str = Field(default=NOT_PROVIDED)
    address: AddressState = Field(default_factory=AddressState)
    narratives: List[str] = Field(default_factory=list)

class TreeDescriptionState(BaseModel):
    # Identification & measurements
    type_common: str = Field(default=NOT_PROVIDED)
    type_scientific: str = Field(default=NOT_PROVIDED)
    height_ft: str = Field(default=NOT_PROVIDED)        # numeric-as-string policy
    canopy_width_ft: str = Field(default=NOT_PROVIDED)   # numeric-as-string policy
    crown_shape: str = Field(default=NOT_PROVIDED)
    dbh_in: str = Field(default=NOT_PROVIDED)            # numeric-as-string policy

    # Observations
    trunk_notes: str = Field(default=NOT_PROVIDED)
    roots: str = Field(default=NOT_PROVIDED)
    defects: str = Field(default=NOT_PROVIDED)
    general_observations: str = Field(default=NOT_PROVIDED)

    # ---- Health Assessment (new) ----
    health_overview: str = Field(default=NOT_PROVIDED)              # e.g., “overall fair vigor; minor dieback”
    pests_pathogens_observed: str = Field(default=NOT_PROVIDED)     # e.g., “anthracnose present” (verbatim)
    physiological_stress_signs: str = Field(default=NOT_PROVIDED)   # e.g., “chlorosis, wilt”

    # Optional narrative bucket (keep if you already had it)
    narratives: List[str] = Field(default_factory=list)

class AreaDescriptionState(BaseModel):
    context: str = Field(default=NOT_PROVIDED)
    other_context_note: str = Field(default=NOT_PROVIDED)
    site_use: str = Field(default=NOT_PROVIDED)
    foot_traffic_level: str = Field(default=NOT_PROVIDED)
    narratives: List[str] = Field(default_factory=list)

class TargetItemState(BaseModel):
    label: str = Field(default=NOT_PROVIDED)
    damage_modes: List[str] = Field(default_factory=list)
    proximity_note: str = Field(default=NOT_PROVIDED)
    occupied_frequency: str = Field(default=NOT_PROVIDED)
    narratives: List[str] = Field(default_factory=list)

class TargetsSectionState(BaseModel):
    items: List[TargetItemState] = Field(default_factory=list)
    narratives: List[str] = Field(default_factory=list)

class RiskItemState(BaseModel):
    description: str = Field(default=NOT_PROVIDED)
    likelihood: str = Field(default=NOT_PROVIDED)
    severity: str = Field(default=NOT_PROVIDED)
    rationale: str = Field(default=NOT_PROVIDED)
    narratives: List[str] = Field(default_factory=list)

class RisksSectionState(BaseModel):
    items: List[RiskItemState] = Field(default_factory=list)
    narratives: List[str] = Field(default_factory=list)

class RecommendationDetailState(BaseModel):
    narrative: str = Field(default=NOT_PROVIDED)
    scope: str = Field(default=NOT_PROVIDED)
    limitations: str = Field(default=NOT_PROVIDED)
    notes: str = Field(default=NOT_PROVIDED)

class RecommendationsSectionState(BaseModel):
    pruning: RecommendationDetailState = Field(default_factory=RecommendationDetailState)
    removal: RecommendationDetailState = Field(default_factory=RecommendationDetailState)
    continued_maintenance: RecommendationDetailState = Field(default_factory=RecommendationDetailState)
    narratives: List[str] = Field(default_factory=list)

class LocationState(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None

# =========================
# Meta
# =========================

class MetaState(BaseModel):
    declined_paths: List[str] = Field(default_factory=list)
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    provided_fields: List[Dict[str, Any]] = Field(default_factory=list)  # dotted paths ever provided


# =========================
# ReportState Root
# =========================

class ReportState(BaseModel):
    current_text: str = Field(default="")
    current_section: Literal["area_description", "tree_description", "targets", "risks", "recommendations"] = "area_description"

    arborist_info: ArboristInfoState = Field(default_factory=ArboristInfoState)
    customer_info: CustomerInfoState = Field(default_factory=CustomerInfoState)
    tree_description: TreeDescriptionState = Field(default_factory=TreeDescriptionState)
    area_description: AreaDescriptionState = Field(default_factory=AreaDescriptionState)
    targets: TargetsSectionState = Field(default_factory=TargetsSectionState)
    risks: RisksSectionState = Field(default_factory=RisksSectionState)
    recommendations: RecommendationsSectionState = Field(default_factory=RecommendationsSectionState)
    location: LocationState = Field(default_factory=LocationState)

    meta: MetaState = Field(default_factory=MetaState)

    # Lightweight provenance (optional):
    # path -> { turn_id, timestamp, domain, extractor, model }
    provenance: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    # ---------- Helpers ----------
    @staticmethod
    def _is_provided(v: Any) -> bool:
        if isinstance(v, str):
            return v != NOT_PROVIDED
        if isinstance(v, list):
            return len(v) > 0
        if isinstance(v, dict):
            return any(ReportState._is_provided(x) for x in v.values())
        return v is not None

    def _walk_and_collect(self, prefix: str, obj: Any, out: Dict[str, Any]) -> None:
        # normalize Pydantic models to dicts
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump(exclude_none=False)
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else k
                self._walk_and_collect(key, v, out)
        else:
            out[prefix] = obj

    @staticmethod
    def _set_by_path(data: Dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        cur = data
        for p in parts[:-1]:
            if p not in cur or not isinstance(cur[p], dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = value

    # ---------- Merge ----------
    def model_merge_updates(
        self,
        updates: Dict[str, Any] | BaseModel | None,
        issues: Any | None = None,               # kept for compatibility
        policy: str = "prefer_existing",          # or "last_write"
        turn_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        domain: Optional[str] = None,
        extractor: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> "ReportState":
        """
        Shallow merge an `updates` envelope into state.

        - `updates` can be a plain dict or Pydantic model with shape:
          { "updates": { "<section>": { ... } } }
        - `prefer_existing`: do NOT overwrite an already provided value with a
          missing placeholder ("Not provided" / empty list)
        - `last_write`: always overwrite
        - Tracks `meta.provided_fields` and `provenance`.
        """
        if updates is None:
            return self

        # normalize input
        if hasattr(updates, "model_dump"):
            updates = updates.model_dump(exclude_none=False)
        if not isinstance(updates, dict):
            return self

        upd_root = updates.get("updates") if "updates" in updates else updates
        if not isinstance(upd_root, dict):
            return self

        # current state → dict
        data = self.model_dump(exclude_none=False)

        # flatten incoming updates to dotted paths under each section
        flat_updates: Dict[str, Any] = {}
        self._walk_and_collect("", upd_root, flat_updates)

        # flatten current state for quick lookups
        cur_flat: Dict[str, Any] = {}
        self._walk_and_collect("", self, cur_flat)

        for path, new_val in flat_updates.items():
            if path == "":
                continue

            # honor policy
            if policy == "prefer_existing":
                cur_val = cur_flat.get(path, None)
                if self._is_provided(cur_val) and not self._is_provided(new_val):
                    continue  # keep existing provided value

            # actually write
            self._set_by_path(data, path, new_val)

            # track provided fields & provenance
            if self._is_provided(new_val):
                if path not in self.meta.provided_fields:
                    self.meta.provided_fields.append(path)
                self.provenance[path] = {
                    "turn_id": turn_id,
                    "timestamp": timestamp,
                    "domain": domain,
                    "extractor": extractor,
                    "model": model_name,
                }

        # return re-validated instance
        return self.__class__.model_validate(data)
    def update_provided_fields(
        self,
        captures: list[dict],
        dedupe: bool = True,
    ) -> "ReportState":
        """
        Append parsed utterance-capture objects into meta.provided_fields.

        Each capture should be shaped like:
          { "section": <str>, "text": <str>, "path": <str>, "value": <str> }

        - Uses append semantics (preserves order).
        - If dedupe=True, drops exact duplicate entries.
        """

        if not captures:
            return self

        # normalize + validate
        new_items = []
        for c in captures:
            if not isinstance(c, dict):
                continue
            if not all(k in c for k in ("section", "text", "path", "value")):
                continue
            new_items.append(c)

        if not new_items:
            return self

        # grab current
        current = list(getattr(self.meta, "provided_fields", []))

        merged = current + new_items
        if dedupe:
            seen = set()
            deduped = []
            for obj in merged:
                key = (
                    obj.get("section"),
                    obj.get("text"),
                    obj.get("path"),
                    obj.get("value"),
                )
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(obj)
            merged = deduped

        # return updated state
        data = self.model_dump(exclude_none=False)
        data["meta"]["provided_fields"] = merged
        return self.__class__.model_validate(data)

# =========================
# Whats-left
# =========================

_SKIP_TOP_LEVEL = {"meta", "provenance"}  # never include these in missing report

def compute_whats_left(state: ReportState) -> Dict[str, List[str]]:
    """
    Scan the entire state and return {section: [missing dotted paths]} for any leaf
    whose value is the placeholder (or empty list).

    Excludes `meta` and `provenance`. Includes `location` if lat/lon are None.
    """
    missing: Dict[str, List[str]] = {}

    def is_missing(val: Any) -> bool:
        if isinstance(val, str):
            return val == NOT_PROVIDED
        if isinstance(val, list):
            return len(val) == 0
        if val is None:
            return True
        return False

    # flatten full state
    flat: Dict[str, Any] = {}
    state._walk_and_collect("", state, flat)

    for path, val in flat.items():
        # path like "tree_description.dbh_in"
        if not path or path.split(".")[0] in _SKIP_TOP_LEVEL:
            continue
        if is_missing(val):
            top = path.split(".")[0]
            missing.setdefault(top, []).append(path)

    # sort lists for stable output
    for k in list(missing.keys()):
        missing[k] = sorted(set(missing[k]))

    return missing

