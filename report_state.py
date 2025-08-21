# report_state.py — runtime state models with safe defaults

from __future__ import annotations
from typing import List, Dict, Any
from pydantic import BaseModel, Field

NOT_PROVIDED = "Not provided"

# --------- Primitive ----------
class AddressState(BaseModel):
    street: str = Field(default=NOT_PROVIDED)
    city: str = Field(default=NOT_PROVIDED)
    state: str = Field(default=NOT_PROVIDED)
    postal_code: str = Field(default=NOT_PROVIDED)
    country: str = Field(default=NOT_PROVIDED)

# --------- Sections (state-friendly) ----------
class ArboristInfoState(BaseModel):
    name: str = Field(default=NOT_PROVIDED)
    company: str = Field(default=NOT_PROVIDED)
    phone: str = Field(default=NOT_PROVIDED)
    email: str = Field(default=NOT_PROVIDED)
    address: AddressState = Field(default_factory=AddressState)
    license: str = Field(default=NOT_PROVIDED)
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
    height_ft: str = Field(default=NOT_PROVIDED)
    canopy_width_ft: str = Field(default=NOT_PROVIDED)
    crown_shape: str = Field(default=NOT_PROVIDED)
    dbh_in: str = Field(default=NOT_PROVIDED)
    trunk_notes: str = Field(default=NOT_PROVIDED)
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

# --------- Meta & Root ----------
class MetaState(BaseModel):
    declined_paths: List[str] = Field(default_factory=list)
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    provided_fields: List[str] = Field(default_factory=list)

class ReportState(BaseModel):
    current_text: str = Field(default="")

    arborist_info: ArboristInfoState = Field(default_factory=ArboristInfoState)
    customer_info: CustomerInfoState = Field(default_factory=CustomerInfoState)
    tree_description: TreeDescriptionState = Field(default_factory=TreeDescriptionState)
    area_description: AreaDescriptionState = Field(default_factory=AreaDescriptionState)
    targets: TargetsSectionState = Field(default_factory=TargetsSectionState)
    risks: RisksSectionState = Field(default_factory=RisksSectionState)
    recommendations: RecommendationsSectionState = Field(default_factory=RecommendationsSectionState)

    meta: MetaState = Field(default_factory=MetaState)
    provenance: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
