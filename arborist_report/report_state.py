#!/usr/bin/env python3
"""
Project: Arborist Agent
File: report_state.py
Author: roger erismann (PEP 8 cleanup)

Canonical report state and provenance model with merge semantics:
- list fields append, scalars last-write (guarded by "prefer_existing"),
- merges produce provenance rows only for applied fields,
- emit a single Not Found row when no fields apply for a segment.

Methods & Classes
- Section models (AddressState, ArboristInfoState, CustomerInfoState, TreeDescriptionState,
  AreaDescriptionState, TargetItemState, TargetsSectionState, RiskItemState, RisksSectionState,
  RecommendationDetailState, RecommendationsSectionState, LocationState)
- MetaState: agent meta (declined paths, issues)
- ProvenanceEvent: per-field applied event rows
- TokenBreakdown: cumulative token accounting
- class ReportState:
  - fields: current_text, current_section, <section models>, meta, provenance, summaries, tokens
  - add_tokens(component, usage)
  - _is_provided(v: Any) -> bool
  - _walk_and_collect(prefix, obj, out) -> None
  - _set_by_path(data, path, value) -> None
  - model_merge_updates(...)
  - set_section_summary(...)

- compute_whats_left(state: ReportState) -> dict[str, list[str]]

Conventions
- NOT_PROVIDED sentinel string; “Not Found” in provenance means extractor
  ran but nothing applied.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field

# ------------------------------------------------------------------------------
# Constants & simple helpers
# ------------------------------------------------------------------------------

NOT_PROVIDED = "Not provided"
SectionName = Literal[
    "area_description", "tree_description", "targets", "risks", "recommendations"
]
_SKIP_TOP_LEVEL = {"meta", "provenance", "tokens"}  # exclude from whats-left


def _value_is_provided(v: Any) -> bool:
    if isinstance(v, str):
        return v != NOT_PROVIDED
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, dict):
        return any(_value_is_provided(x) for x in v.values())
    return v is not None


def _walk_and_collect(prefix: str, obj: Any, out: Dict[str, Any]) -> None:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(exclude_none=False)
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            _walk_and_collect(key, v, out)
    else:
        out[prefix] = obj


def _set_by_path(data: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = data
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _append_prov(
    acc: List[Dict[str, Any]],
    *,
    turn_id: Optional[str],
    section: Optional[str],
    segment_text: Optional[str],
    path: Optional[str],
    value: Optional[str],
    timestamp: Optional[str],
    extractor: Optional[str],
    model_name: Optional[str],
) -> None:
    acc.append(
        {
            "turnid": turn_id,
            "section": section,
            "text": segment_text,
            "path": (path or "Not Found"),
            "value": ("Not Found" if value is None or value == NOT_PROVIDED else value),
            "timestamp": timestamp,
            "extractor": extractor,
            "model": model_name,
        }
    )


def _is_missing_value(val: Any) -> bool:
    if isinstance(val, str):
        return val == NOT_PROVIDED
    if isinstance(val, list):
        return len(val) == 0
    return val is None


# ------------------------------------------------------------------------------
# Telemetry (tokens)
# ------------------------------------------------------------------------------

class TokenBreakdown(BaseModel):
    total_in: int = 0
    total_out: int = 0
    # by_component example: {"intent_llm": {"in": 34, "out": 8}, "extractor:risks": {...}}
    by_component: Dict[str, Dict[str, int]] = Field(default_factory=dict)

    def add(self, component: str, usage: Dict[str, int]) -> "TokenBreakdown":
        inc_in = int(usage.get("in", 0) or 0)
        inc_out = int(usage.get("out", 0) or 0)

        data = self.model_dump(exclude_none=False)
        data["total_in"] = int(data.get("total_in", 0)) + inc_in
        data["total_out"] = int(data.get("total_out", 0)) + inc_out

        per = dict(data.get("by_component") or {})
        cur = per.get(component, {"in": 0, "out": 0})
        per[component] = {
            "in": int(cur.get("in", 0)) + inc_in,
            "out": int(cur.get("out", 0)) + inc_out,
        }
        data["by_component"] = per
        return TokenBreakdown.model_validate(data)


# ------------------------------------------------------------------------------
# Section Models (STATE)
# ------------------------------------------------------------------------------

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
    certification: str = Field(default=NOT_PROVIDED)   # <-- added
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
    type_common: str = Field(default=NOT_PROVIDED)
    type_scientific: str = Field(default=NOT_PROVIDED)
    height_ft: str = Field(default=NOT_PROVIDED)       # numeric-as-string
    canopy_width_ft: str = Field(default=NOT_PROVIDED)  # numeric-as-string
    crown_shape: str = Field(default=NOT_PROVIDED)
    dbh_in: str = Field(default=NOT_PROVIDED)           # numeric-as-string

    trunk_notes: List[str] = Field(default_factory=list)
    roots: List[str] = Field(default_factory=list)
    defects: List[str] = Field(default_factory=list)
    general_observations: List[str] = Field(default_factory=list)

    health_overview: list[str] = Field(default_factory=list)
    pests_pathogens_observed: List[str] = Field(default_factory=list)
    physiological_stress_signs: List[str] = Field(default_factory=list)

    narratives: List[str] = Field(default_factory=list)


class AreaDescriptionState(BaseModel):
    context: List[str] = Field(default_factory=list)
    other_context_note: List[str] = Field(default_factory=list)
    site_use: List[str] = Field(default_factory=list)
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

class LocationState(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None


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

# ------------------------------------------------------------------------------
# Meta & Provenance
# ------------------------------------------------------------------------------

class MetaState(BaseModel):
    declined_paths: List[str] = Field(default_factory=list)
    issues: List[Dict[str, Any]] = Field(default_factory=list)


class ProvenanceEvent(BaseModel):
    turnid: Optional[str] = None
    section: Optional[str] = None
    text: Optional[str] = None                 # scoped user text sent to extractor
    path: str = Field(default="Not Found")     # dotted path or "Not Found"
    value: str = Field(default="Not Found")    # captured value or "Not Found"
    timestamp: Optional[str] = None
    extractor: Optional[str] = None
    model: Optional[str] = None

class JobNumber(BaseModel):
    job_id: str = Field(default="Not Found")

# ------------------------------------------------------------------------------
# Section Summaries (replace-on-write snapshots)
# ------------------------------------------------------------------------------

class SectionSummaryInputs(BaseModel):
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
    text: str = ""
    updated_at: str = ""  # ISO string or empty
    updated_by: Literal["llm", "human"] = "llm"
    based_on_turnid: str = ""
    inputs: SectionSummaryInputs = Field(
        default_factory=lambda: SectionSummaryInputs(
            section="area_description",
            snapshot={},
            provided_paths=[],
            reference_text="",
            style={},
        )
    )


class SummariesState(BaseModel):
    area_description: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(
                section="area_description", section_state={}, reference_text="", provided_paths=[]
            )
        )
    )
    tree_description: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(
                section="tree_description", section_state={}, reference_text="", provided_paths=[]
            )
        )
    )
    targets: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(
                section="targets", section_state={}, reference_text="", provided_paths=[]
            )
        )
    )
    risks: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(
                section="risks", section_state={}, reference_text="", provided_paths=[]
            )
        )
    )
    recommendations: SectionSummaryState = Field(
        default_factory=lambda: SectionSummaryState(
            inputs=SectionSummaryInputs.make(
                section="recommendations", section_state={}, reference_text="", provided_paths=[]
            )
        )
    )


# ------------------------------------------------------------------------------
# ReportState Root
# ------------------------------------------------------------------------------

class ReportState(BaseModel):
    current_text: str = Field(default="")
    current_section: SectionName = "area_description"
    job_id : JobNumber = Field(default_factory=JobNumber)
    arborist_info: ArboristInfoState = Field(default_factory=ArboristInfoState)
    customer_info: CustomerInfoState = Field(default_factory=CustomerInfoState)
    tree_description: TreeDescriptionState = Field(default_factory=TreeDescriptionState)
    area_description: AreaDescriptionState = Field(default_factory=AreaDescriptionState)
    targets: TargetsSectionState = Field(default_factory=TargetsSectionState)
    risks: RisksSectionState = Field(default_factory=RisksSectionState)
    recommendations: RecommendationsSectionState = Field(default_factory=RecommendationsSectionState)
    location: LocationState = Field(default_factory=LocationState)

    meta: MetaState = Field(default_factory=MetaState)

    provenance: List[ProvenanceEvent] = Field(default_factory=list)
    summaries: SummariesState = Field(default_factory=SummariesState)

    # NEW: token accounting
    tokens: TokenBreakdown = Field(default_factory=TokenBreakdown)

    # --------------------------- Token helpers --------------------------------

    def add_tokens(self, component: str, usage: Dict[str, int]) -> "ReportState":
        """
        Accumulate token usage (uses 'in'/'out' keys) into totals and per-component buckets.
        Returns a new ReportState (immutably), consistent with other mutators.
        """
        data = self.model_dump(exclude_none=False)
        tb = self.tokens if isinstance(self.tokens, TokenBreakdown) else TokenBreakdown()
        data["tokens"] = tb.add(component, usage).model_dump(exclude_none=False)
        return self.__class__.model_validate(data)

    # ------------------------------ Summaries ---------------------------------

    def set_section_summary(
        self,
        section: SectionName,
        *,
        summary: SectionSummaryState,
        turn_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> "ReportState":
        data = self.model_dump(exclude_none=False)
        data.setdefault("summaries", {})
        data["summaries"][section] = summary.model_dump(exclude_none=False)

        prov = list(self.provenance)
        prov_dicts = [
            p.model_dump(exclude_none=False) if hasattr(p, "model_dump") else p
            for p in prov
        ]
        _append_prov(
            prov_dicts,
            turn_id=turn_id,
            section=section,
            segment_text=None,
            path=f"summaries.{section}.text",
            value=summary.text or "Not Found",
            timestamp=timestamp,
            extractor="SectionReportAgent",
            model_name=model_name,
        )
        data["provenance"] = prov_dicts
        return self.__class__.model_validate(data)

    # ------------------------------- Helpers ----------------------------------

    @staticmethod
    def _is_provided(v: Any) -> bool:
        return _value_is_provided(v)

    def _walk_and_collect(self, prefix: str, obj: Any, out: Dict[str, Any]) -> None:
        _walk_and_collect(prefix, obj, out)

    @staticmethod
    def _set_by_path(data: Dict[str, Any], path: str, value: Any) -> None:
        _set_by_path(data, path, value)

    # -------------------------------- Merge -----------------------------------

    def model_merge_updates(
        self,
        updates: Dict[str, Any] | BaseModel | None,
        issues: Any | None = None,
        policy: str = "prefer_existing",  # or "last_write"
        turn_id: Optional[str] = None,
        timestamp: Optional[str] = None,
        domain: Optional[str] = None,
        extractor: Optional[str] = None,
        model_name: Optional[str] = None,
        segment_text: Optional[str] = None,
    ) -> "ReportState":
        data = self.model_dump(exclude_none=False)

        prov_acc: List[Dict[str, Any]] = [
            e.model_dump(exclude_none=False) if hasattr(e, "model_dump") else e
            for e in self.provenance
        ]

        # No envelope → single Not Found row, no state change
        if updates is None:
            _append_prov(
                prov_acc,
                turn_id=turn_id,
                section=domain,
                segment_text=segment_text,
                path="Not Found",
                value="Not Found",
                timestamp=timestamp,
                extractor=extractor,
                model_name=model_name,
            )
            data["provenance"] = prov_acc
            return self.__class__.model_validate(data)

        # Normalize input
        if hasattr(updates, "model_dump"):
            updates = updates.model_dump(exclude_none=False)
        if not isinstance(updates, dict):
            _append_prov(
                prov_acc,
                turn_id=turn_id,
                section=domain,
                segment_text=segment_text,
                path="Not Found",
                value="Not Found",
                timestamp=timestamp,
                extractor=extractor,
                model_name=model_name,
            )
            data["provenance"] = prov_acc
            return self.__class__.model_validate(data)

        upd_root = updates.get("updates") if "updates" in updates else updates
        if not isinstance(upd_root, dict) or not upd_root:
            _append_prov(
                prov_acc,
                turn_id=turn_id,
                section=domain,
                segment_text=segment_text,
                path="Not Found",
                value="Not Found",
                timestamp=timestamp,
                extractor=extractor,
                model_name=model_name,
            )
            data["provenance"] = prov_acc
            return self.__class__.model_validate(data)

        # Flatten incoming updates and current state
        flat_updates: Dict[str, Any] = {}
        self._walk_and_collect("", upd_root, flat_updates)

        cur_flat: Dict[str, Any] = {}
        self._walk_and_collect("", self, cur_flat)

        captured_any = False

        for path, new_val in flat_updates.items():
            if path == "":
                continue

            # Policy guard
            if policy == "prefer_existing":
                cur_val_existing = cur_flat.get(path, None)
                if self._is_provided(cur_val_existing) and not self._is_provided(new_val):
                    continue

            cur_val = cur_flat.get(path, None)

            # List fields: append semantics
            if isinstance(cur_val, list):
                if isinstance(new_val, list) and len(new_val) > 0:
                    _set_by_path(data, path, (cur_val or []) + new_val)
                    _append_prov(
                        prov_acc,
                        turn_id=turn_id,
                        section=domain,
                        segment_text=segment_text,
                        path=path,
                        value=str(new_val),
                        timestamp=timestamp,
                        extractor=extractor,
                        model_name=model_name,
                    )
                    captured_any = True

            else:
                # Scalar fields: last-write (subject to policy)
                _set_by_path(data, path, new_val)
                if self._is_provided(new_val):
                    val_str = new_val if isinstance(new_val, str) else ("" if new_val is None else str(new_val))

                    if policy == "last_write":
                        prov_acc = [
                            row
                            for row in prov_acc
                            if not ((row.get("section") == domain) and (row.get("path") == path))
                        ]

                    _append_prov(
                        prov_acc,
                        turn_id=turn_id,
                        section=domain,
                        segment_text=segment_text,
                        path=path,
                        value=val_str,
                        timestamp=timestamp,
                        extractor=extractor,
                        model_name=model_name,
                    )
                    captured_any = True

        if not captured_any:
            _append_prov(
                prov_acc,
                turn_id=turn_id,
                section=domain,
                segment_text=segment_text,
                path="Not Found",
                value="Not Found",
                timestamp=timestamp,
                extractor=extractor,
                model_name=model_name,
            )

        data["provenance"] = prov_acc
        return self.__class__.model_validate(data)


# ------------------------------------------------------------------------------
# Whats-left
# ------------------------------------------------------------------------------

def compute_whats_left(state: ReportState) -> Dict[str, List[str]]:
    missing: Dict[str, List[str]] = {}

    flat: Dict[str, Any] = {}
    state._walk_and_collect("", state, flat)

    for path, val in flat.items():
        if not path:
            continue
        top = path.split(".")[0]
        if top in _SKIP_TOP_LEVEL:
            continue
        if _is_missing_value(val):
            missing.setdefault(top, []).append(path)

    for k in list(missing.keys()):
        missing[k] = sorted(set(missing[k]))

    return missing
