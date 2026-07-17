"""HTTP request models for the control plane.

These are the wire contract only; handlers translate them into domain/application types,
where the real validation (identifier shape, window ordering) lives.
"""

from datetime import datetime

from pydantic import BaseModel


class WindowPayload(BaseModel):
    start: datetime
    injection: datetime
    end: datetime


class CreateInvestigationRequest(BaseModel):
    incident_id: str
    run_id: str
    window: WindowPayload
