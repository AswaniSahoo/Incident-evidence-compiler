"""HTTP request models for the control plane.

These are the wire contract only; handlers translate them into domain/application types,
where the real validation (identifier shape, window ordering) lives.
"""

from datetime import datetime

from pydantic import BaseModel, Field

# Both identifiers are interpolated verbatim into the LLM prompt, so an uncapped value is a
# cost-amplification lever for any authenticated tenant. The domain only requires non-blank.
MAX_IDENTIFIER_LENGTH = 200


class WindowPayload(BaseModel):
    start: datetime
    injection: datetime
    end: datetime


class CreateInvestigationRequest(BaseModel):
    incident_id: str = Field(max_length=MAX_IDENTIFIER_LENGTH)
    run_id: str = Field(max_length=MAX_IDENTIFIER_LENGTH)
    window: WindowPayload
