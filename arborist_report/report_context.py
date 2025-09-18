"""
Project: Arborist Agent
File: report_context.py
Author: roger erismann
Assistant: chatGPT5
code review: chatGPT5

Read-only job context (“who/where”) injected into the Coordinator at startup.
Strict Pydantic models; the Coordinator must not mutate this context.

The report context identifies the arborist, the client, the tree and the job number. It defines the subject of the report.
Report context can be added through local_store.inbox.pending_jobs.jsonl. Once the arborist accepts the context it can not
be edited through the coordinator or top agent application.

context can be manually added or edited (prior to accepting) by the arborist using the job notes interface.

Methods & Classes
- AddressCtx, ArboristInfoCtx, CustomerInfoCtx, LocationCtx: strict context submodels.
- class ReportContext: {arborist, customer, location}; extra="forbid".
- _build_context_from_testdata() -> ReportContext: helper to construct a dev context from test fixtures.

Dependencies
- External: pydantic
- Internal (dev-only in helper): tests.test_data fixtures
"""


from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict

class AddressCtx(BaseModel):
    street: str = Field(...)
    city: str = Field(...)
    state: str = Field(...)
    postal_code: str = Field(...)
    country: str = Field(...)
    model_config = ConfigDict(extra="forbid")

class ArboristInfoCtx(BaseModel):
    name: str = Field(...)
    company: str = Field(...)
    phone: str = Field(...)
    email: str = Field(...)
    license: str = Field(...)
    certification: str = Field(...)  # <-- added
    address: AddressCtx = Field(...)
    model_config = ConfigDict(extra="forbid")

class CustomerInfoCtx(BaseModel):
    name: str = Field(...)
    company: str = Field(...)
    phone: str = Field(...)
    email: str = Field(...)
    address: AddressCtx = Field(...)
    model_config = ConfigDict(extra="forbid")

class LocationCtx(BaseModel):
    latitude: float = Field(...)
    longitude: float = Field(...)
    model_config = ConfigDict(extra="forbid")

class JobNumber(BaseModel):
    job_id: str = Field(...)
    model_config = ConfigDict(extra="forbid")

class ReportContext(BaseModel):
    job_id: str = Field(...)
    arborist: ArboristInfoCtx = Field(...)
    customer: CustomerInfoCtx = Field(...)
    location: LocationCtx = Field(...)
    model_config = ConfigDict(extra="forbid")

# ! deprecate
def _build_context_from_testdata() -> ReportContext:
    """
    Convenience for local/dev runs: constructs ReportContext
    from test_data.py fixtures.
    """
    from tests.test_data import ARBORIST_PROFILE, CUSTOMER_PROFILE, DEFAULT_LOCATION # local-only
    return ReportContext(
        arborist=ArboristInfoCtx(**ARBORIST_PROFILE),
        customer=CustomerInfoCtx(**CUSTOMER_PROFILE),
        location=LocationCtx(**DEFAULT_LOCATION),
    )
