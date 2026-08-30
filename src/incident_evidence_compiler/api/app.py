"""FastAPI control plane.

A thin inbound adapter over the application use-cases. Authentication is a static bearer
token mapped to a tenant; every data route is authenticated and tenant-scoped, and a
cross-tenant lookup returns 404 (never 403) to avoid leaking existence. ``/health`` is the
only unauthenticated route. Error bodies carry only stable codes, never model text,
tenant data, or internals.
"""

import json
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..application import (
    CreateInvestigation,
    CreateInvestigationCommand,
    GetInvestigationStatus,
    GetReport,
    InvestigationNotFoundError,
    ReportNotReadyError,
)
from ..domain.errors import DomainValidationError
from ..domain.identifiers import IncidentId, RunId, TenantId
from ..domain.incidents import IncidentWindow
from ..observability import MetricsRegistry
from ..persistence import InvestigationId, UnitOfWorkFactory
from ..persistence.errors import InvalidPersistenceIdentifierError
from .auth import TokenRegistry
from .models import MAX_IDENTIFIER_LENGTH, CreateInvestigationRequest


def _investigation_id(raw: str) -> InvestigationId:
    try:
        return InvestigationId(UUID(raw))
    except (ValueError, InvalidPersistenceIdentifierError):
        raise HTTPException(status_code=404, detail={"code": "investigation_not_found"}) from None


def create_app(
    *,
    uow_factory: UnitOfWorkFactory,
    tokens: TokenRegistry,
    metrics: MetricsRegistry | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Incident Evidence Compiler",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    create_investigation = CreateInvestigation(uow_factory)
    get_status = GetInvestigationStatus(uow_factory)
    get_report = GetReport(uow_factory)
    registry = metrics if metrics is not None else MetricsRegistry()

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> TenantId:
        prefix = "Bearer "
        if authorization is None or not authorization.startswith(prefix):
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})
        tenant = tokens.tenant_for(authorization[len(prefix) :].strip())
        if tenant is None:
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})
        return tenant

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        # Open like /health, and deliberately free of tenant/PII labels; restrict network
        # access to this scrape endpoint at deployment time.
        return PlainTextResponse(
            registry.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    @app.post("/investigations", status_code=202)
    async def create(
        body: CreateInvestigationRequest,
        tenant: Annotated[TenantId, Depends(authenticate)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, str]:
        if idempotency_key is not None and (
            not idempotency_key.strip() or len(idempotency_key) > MAX_IDENTIFIER_LENGTH
        ):
            # The persistence record rejects a blank key with a PersistenceValidationError,
            # which is not a DomainValidationError and so escaped the handler below as a 500.
            raise HTTPException(status_code=422, detail={"code": "invalid_idempotency_key"})
        try:
            command = CreateInvestigationCommand(
                tenant=tenant,
                incident=IncidentId(body.incident_id),
                run=RunId(body.run_id),
                window=IncidentWindow(
                    start=body.window.start,
                    injection=body.window.injection,
                    end=body.window.end,
                ),
                idempotency_key=idempotency_key,
            )
        except DomainValidationError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code}) from None
        investigation_id = await create_investigation.execute(command)
        return {"investigation_id": str(investigation_id.value)}

    @app.get("/investigations/{investigation_id}")
    async def status(
        investigation_id: str, tenant: Annotated[TenantId, Depends(authenticate)]
    ) -> dict[str, str]:
        record = await get_status.execute(tenant, _investigation_id(investigation_id))
        return {
            "investigation_id": str(record.investigation_id.value),
            "status": record.status.value,
        }

    @app.get("/investigations/{investigation_id}/report")
    async def report(
        investigation_id: str, tenant: Annotated[TenantId, Depends(authenticate)]
    ) -> dict[str, object]:
        record = await get_report.execute(tenant, _investigation_id(investigation_id))
        return {
            "investigation_id": str(record.investigation_id.value),
            "schema_version": record.schema_version,
            "report": json.loads(record.payload),
            "baseline_ranking": (
                json.loads(record.baseline_payload) if record.baseline_payload is not None else None
            ),
        }

    @app.exception_handler(InvestigationNotFoundError)
    async def _handle_not_found(_request: Request, exc: InvestigationNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"code": exc.code})

    @app.exception_handler(ReportNotReadyError)
    async def _handle_not_ready(_request: Request, exc: ReportNotReadyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"code": exc.code})

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail
        code = detail["code"] if isinstance(detail, dict) and "code" in detail else "http_error"
        return JSONResponse(status_code=exc.status_code, content={"code": code})

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        # Do not echo the offending request back; only a stable code crosses the boundary.
        return JSONResponse(status_code=422, content={"code": "invalid_request"})

    return app
