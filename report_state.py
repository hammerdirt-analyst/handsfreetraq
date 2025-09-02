"""
Project: Arborist Agent
File: report_state.py
Author: roger erismann

Canonical report state and provenance model with merge semantics:
- list fields append, scalars last-write (guarded by "prefer_existing"),
- merges produce provenance rows only for applied fields,
- emit a single Not Found row when no fields apply for a segment.

Methods & Classes
- Section models (AddressState, ArboristInfoState, CustomerInfoState, TreeDescriptionState,
  AreaDescriptionState, TargetItemState, TargetsSectionState, RiskItemState, RisksSectionState,
  RecommendationDetailState, RecommendationsSectionState, LocationState)  # state schema
- MetaState: agent meta (declined paths, issues)
- ProvenanceEvent: per-field applied event rows
- class ReportState:
  - fields: current_text, current_section, <section models>, meta, provenance
  - _is_provided(v: Any) -> bool: providedness policy (sentinel vs empty vs None).
  - _walk_and_collect(prefix, obj, out) -> None: flatten to dotted paths.
  - _set_by_path(data, path, value) -> None: nested set by dotted path.
  - model_merge_updates(updates, *, policy="prefer_existing", turn_id, timestamp, domain, extractor, model_name, segment_text) -> ReportState
- compute_whats_left(state: ReportState) -> dict[str, list[str]]: dotted paths still “Not provided” or empty.

Dependencies
- External: pydantic
- Stdlib: typing
- Conventions: NOT_PROVIDED sentinel string; “Not Found” in provenance means extractor ran but nothing applied.
"""
from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Dict, List, Literal, Optional
import hashlib
import json


NOT_PROVIDED = "Not provided"

# Section Models (STATE)

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

    # Observations (append-only lists)
    trunk_notes: List[str] = Field(default_factory=list)
    roots: List[str] = Field(default_factory=list)
    defects: List[str] = Field(default_factory=list)
    general_observations: List[str] = Field(default_factory=list)

    # ---- Health Assessment (new)
    health_overview: str = Field(default=NOT_PROVIDED)              # e.g., “overall fair vigor; minor dieback”
    pests_pathogens_observed: List[str] = Field(default_factory=list)     # e.g., “anthracnose present” (verbatim)
    physiological_stress_signs: List[str] = Field(default_factory=list)   # e.g., “chlorosis, wilt”

    # Optional narrative bucket
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

# =========================
# Provenance (event log)
# =========================

class ProvenanceEvent(BaseModel):
    turnid: Optional[str] = None
    section: Optional[str] = None
    text: Optional[str] = None          # the scoped user text sent to the extractor
    path: str = Field(default="Not Found")   # dotted path or "Not Found"
    value: str = Field(default="Not Found")  # captured value or "Not Found"
    timestamp: Optional[str] = None
    extractor: Optional[str] = None
    model: Optional[str] = None


# =========================
# Section Summaries (replace-on-write snapshots)
# =========================
SectionName = Literal["area_description", "tree_description", "targets", "risks", "recommendations"]

class SectionSummaryInputs(BaseModel):
    """Snapshot of what the LLM saw when producing a section summary."""
    version: str = "section_payload_v1"
    section: SectionName
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    provided_paths: List[str] = Field(default_factory=list)
    reference_text: str = ""
    style: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def make(
        cls,
        *,
        section: SectionName,
        section_state: Dict[str, Any] | BaseModel,
        reference_text: str,
        provided_paths: List[str],
        style: Optional[Dict[str, Any]] = None,
    ) -> "SectionSummaryInputs":
        if hasattr(section_state, "model_dump"):
            section_state = section_state.model_dump(exclude_none=False)
        return cls(
            section=section,
            snapshot=section_state or {},
            provided_paths=list(provided_paths or []),
            reference_text=reference_text or "",
            style=style or {},
        )

class SectionSummaryState(BaseModel):
    """Per-section, replaceable summary with minimal valid defaults."""
    text: str = ""
    updated_at: str = ""  # ISO string or empty
    updated_by: Literal["llm", "human"] = "llm"  # <-- IMPORTANT: must NOT be NOT_PROVIDED
    based_on_turnid: str = ""
    inputs: SectionSummaryInputs = Field(default_factory=lambda: SectionSummaryInputs(
        section="area_description", snapshot={}, provided_paths=[], reference_text="", style={}
    ))

class SummariesState(BaseModel):
    """Container for all section summaries (valid from construction)."""
    area_description: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(section="area_description", section_state={}, reference_text="", provided_paths=[])
        )
    )
    tree_description: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(section="tree_description", section_state={}, reference_text="", provided_paths=[])
        )
    )
    targets: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(section="targets", section_state={}, reference_text="", provided_paths=[])
        )
    )
    risks: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(section="risks", section_state={}, reference_text="", provided_paths=[])
        )
    )
    recommendations: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(section="recommendations", section_state={}, reference_text="", provided_paths=[])
        )
    )

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

    # Provenance is a list of per-field events (one row per section.field attempt)
    provenance: List[ProvenanceEvent] = Field(default_factory=list)

    summaries: SummariesState = Field(default_factory=SummariesState)

    # ---------- Helpers ----------

    def set_section_summary(
        self,
        section: SectionName,
        *,
        summary: SectionSummaryState,
        turn_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> "ReportState":
        """
        Replace the per-section summary (no history). Emits ONE provenance row at:
          path = f"summaries.{section}.text"
        """
        # Start with current full-state dict
        data = self.model_dump(exclude_none=False)

        # Replace the single section summary atomically
        if "summaries" not in data or not isinstance(data["summaries"], dict):
            data["summaries"] = {}
        data["summaries"][section] = summary.model_dump(exclude_none=False)

        # Append a single provenance row for the text write
        prov = list(self.provenance)
        prov.append(ProvenanceEvent(
            turnid=turn_id,
            section=section,
            text=None,
            path=f"summaries.{section}.text",
            value=summary.text or "Not Found",
            timestamp=timestamp,
            extractor="SectionReportAgent",
            model=model_name,
        ))
        data["provenance"] = [p.model_dump(exclude_none=False) if hasattr(p, "model_dump") else p for p in prov]

        # Return a revalidated state
        return self.__class__.model_validate(data)

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
        issues: Any | None = None,  # kept for compatibility
        policy: str = "prefer_existing",  # or "last_write"
        turn_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        domain: Optional[str] = None,  # section
        extractor: Optional[str] = None,
        model_name: Optional[str] = None,
        segment_text: Optional[str] = None,  # the scoped user text routed to the extractor
    ) -> "ReportState":
        """
        Merge an `updates` envelope into state with:
          - append semantics for list fields,
          - last-write for scalars (unless policy='prefer_existing' blocks),
          - provenance rows ONLY for fields actually applied,
          - if nothing applied for the segment → ONE row with path/value = 'Not Found'.

        Notes:
        - `updates` may be { "updates": { "<section>": {...} } } or a plain section dict.
        - 'Not provided' is the state sentinel (no user input yet).
        - 'Not Found' in provenance means extractor ran for this segment but yielded no applied fields.
        """
        # Snapshot current state; start provenance accumulator with existing rows (as dicts)
        data = self.model_dump(exclude_none=False)
        prov_acc: List[Dict[str, Any]] = [
            e.model_dump(exclude_none=False) if hasattr(e, "model_dump") else e
            for e in self.provenance
        ]

        def append_prov(path: Optional[str], value: Optional[str]) -> None:
            prov_acc.append({
                "turnid": turn_id,
                "section": domain,
                "text": segment_text,
                "path": (path or "Not Found"),
                "value": ("Not Found" if value is None or value == NOT_PROVIDED else value),
                "timestamp": timestamp,
                "extractor": extractor,
                "model": model_name,
            })

        # If no updates envelope at all → single Not Found row, no state change
        if updates is None:
            append_prov("Not Found", "Not Found")
            data["provenance"] = prov_acc
            return self.__class__.model_validate(data)

        # Normalize input
        if hasattr(updates, "model_dump"):
            updates = updates.model_dump(exclude_none=False)
        if not isinstance(updates, dict):
            append_prov("Not Found", "Not Found")
            data["provenance"] = prov_acc
            return self.__class__.model_validate(data)

        upd_root = updates.get("updates") if "updates" in updates else updates
        if not isinstance(upd_root, dict) or not upd_root:
            append_prov("Not Found", "Not Found")
            data["provenance"] = prov_acc
            return self.__class__.model_validate(data)

        # Flatten incoming updates to dotted paths
        flat_updates: Dict[str, Any] = {}
        self._walk_and_collect("", upd_root, flat_updates)

        # Flatten current state for quick lookups
        cur_flat: Dict[str, Any] = {}
        self._walk_and_collect("", self, cur_flat)

        captured_any = False

        for path, new_val in flat_updates.items():
            if path == "":
                continue

            # Policy guard: if prefer_existing and existing is provided while incoming is not → skip (no provenance row)
            if policy == "prefer_existing":
                cur_val_existing = cur_flat.get(path, None)
                if self._is_provided(cur_val_existing) and not self._is_provided(new_val):
                    continue

            # Current value (from snapshot)
            cur_val = cur_flat.get(path, None)

            # List-typed path in state (append semantics)
            if isinstance(cur_val, list):
                if isinstance(new_val, list):
                    if len(new_val) > 0:
                        # append batch
                        self._set_by_path(data, path, (cur_val or []) + new_val)
                        append_prov(path, str(new_val))
                        captured_any = True
                    # else: empty incoming list → do nothing, no provenance
                # If new_val is not a list for a list field, ignore (no change)

            else:
                # Scalar path in state: write value (respecting policy already checked)
                self._set_by_path(data, path, new_val)
                if self._is_provided(new_val):
                    val_str = new_val if isinstance(new_val, str) else ("" if new_val is None else str(new_val))

                    # --- BEGIN: corrections provenance de-dup for scalars ---
                    # When doing a correction (policy='last_write'), keep only ONE active
                    # provenance row for this (section, path). Remove prior rows before appending new.
                    if policy == "last_write":
                        prov_acc = [
                            row for row in prov_acc
                            if not (
                                (row.get("section") == domain) and
                                (row.get("path") == path)
                            )
                        ]
                    # --- END

                    append_prov(path, val_str)
                    captured_any = True
                # else: not provided → do nothing, no provenance

        # If nothing applied at all for this segment, emit one Not Found row
        if not captured_any:
            append_prov("Not Found", "Not Found")

        # Persist provenance and revalidate
        data["provenance"] = prov_acc
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
