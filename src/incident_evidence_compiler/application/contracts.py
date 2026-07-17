"""Typed application command contracts (no anonymous dictionaries)."""

from dataclasses import dataclass

from ..domain.identifiers import IncidentId, RunId, TenantId
from ..domain.incidents import IncidentWindow


@dataclass(frozen=True, slots=True)
class CreateInvestigationCommand:
    """A request to open an investigation for a tenant's incident run."""

    tenant: TenantId
    incident: IncidentId
    run: RunId
    window: IncidentWindow
    idempotency_key: str | None = None
