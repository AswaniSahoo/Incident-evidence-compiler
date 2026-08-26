"""Composition root and process entrypoint (ADR 0016).

Wires the persistence, LLM, and telemetry ports selected by ``AppConfig`` into a FastAPI
control plane plus an optional in-process worker loop, and exposes ``main`` for
``python -m incident_evidence_compiler``. This is the only module that constructs concrete
infrastructure; the domain and application layers stay framework- and driver-agnostic.
"""

import asyncio
import contextlib
import logging
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta

from fastapi import FastAPI

from ..api import TokenRegistry, create_app
from ..application import InMemoryTelemetrySource, TelemetrySource, Worker
from ..llm import GeminiLLMClient, LLMClient
from ..observability import MetricsRegistry
from ..persistence import InMemoryUnitOfWorkFactory, UnitOfWorkFactory
from ..persistence.postgres import PostgresUnitOfWorkFactory
from .config import AppConfig, ConfigError
from .demo_llm import FirstSignalLLMClient
from .prometheus import PrometheusClient, PrometheusTelemetrySource
from .telemetry import RcaevalTelemetrySource

_LOGGER = logging.getLogger("incident_evidence_compiler")
_WORKER_ID = "inproc-worker"


@dataclass(frozen=True, slots=True)
class ServerComponents:
    """The wired-up components for one process."""

    app: FastAPI
    worker: Worker | None
    uow_factory: UnitOfWorkFactory
    telemetry: TelemetrySource
    metrics: MetricsRegistry


def _build_uow_factory(config: AppConfig) -> UnitOfWorkFactory:
    if config.persistence == "postgres":
        assert config.database_url is not None  # guaranteed by AppConfig.from_env
        return PostgresUnitOfWorkFactory(config.database_url)
    return InMemoryUnitOfWorkFactory()


def _build_llm_client(config: AppConfig) -> LLMClient:
    if config.llm_provider == "developer":
        assert config.gemini_api_key is not None
        return GeminiLLMClient.from_api_key(config.gemini_api_key, model=config.gemini_model)
    if config.llm_provider == "vertex":
        assert config.gemini_project is not None
        return GeminiLLMClient.from_vertex(
            project=config.gemini_project,
            location=config.gemini_location,
            model=config.gemini_model,
        )
    return FirstSignalLLMClient()


def _build_telemetry(config: AppConfig) -> TelemetrySource:
    if config.telemetry == "rcaeval":
        assert config.re2_root is not None
        return RcaevalTelemetrySource(config.re2_root, split=config.re2_split)
    if config.telemetry == "prometheus":
        assert config.prom_url is not None  # guaranteed by AppConfig.from_env
        return PrometheusTelemetrySource(
            PrometheusClient.over_http(config.prom_url, bearer_token=config.prom_bearer_token),
            config.prom_queries,
            step_seconds=config.prom_step_seconds,
            deadline=timedelta(seconds=config.prom_timeout_seconds),
        )
    return InMemoryTelemetrySource()


def build_components(config: AppConfig) -> ServerComponents:
    """Construct every concrete component the config selects (may perform startup I/O)."""
    metrics = MetricsRegistry()
    uow_factory = _build_uow_factory(config)
    telemetry = _build_telemetry(config)
    tokens = TokenRegistry.from_mapping(config.tokens)
    app = create_app(uow_factory=uow_factory, tokens=tokens, metrics=metrics)
    worker: Worker | None = None
    if config.worker_enabled:
        worker = Worker(
            uow_factory,
            _build_llm_client(config),
            telemetry,
            worker_id=_WORKER_ID,
            metrics=metrics,
        )
    return ServerComponents(
        app=app,
        worker=worker,
        uow_factory=uow_factory,
        telemetry=telemetry,
        metrics=metrics,
    )


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)


async def run_worker_loop(
    worker: Worker, *, stop_event: asyncio.Event, idle_sleep_seconds: float = 1.0
) -> None:
    """Claim and process jobs until ``stop_event`` is set, sleeping only when idle.

    A single iteration's failure is logged (without payloads, the worker itself is
    leakage-safe) and the loop backs off rather than dying, so one bad job cannot wedge the
    process.
    """
    while not stop_event.is_set():
        try:
            did_work = await worker.run_once()
        except Exception:
            _LOGGER.exception("worker iteration failed")
            await _sleep_or_stop(stop_event, idle_sleep_seconds)
            continue
        if not did_work:
            await _sleep_or_stop(stop_event, idle_sleep_seconds)


def create_server_app(config: AppConfig) -> FastAPI:
    """Build the ASGI app, attaching an in-process worker loop to its lifespan if enabled."""
    components = build_components(config)
    app = components.app
    worker = components.worker
    if worker is None:
        return app

    @contextlib.asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        task = asyncio.create_task(
            run_worker_loop(
                worker, stop_event=stop, idle_sleep_seconds=config.worker_idle_sleep_seconds
            )
        )
        try:
            yield
        finally:
            stop.set()
            await task

    app.router.lifespan_context = _lifespan
    return app


def main() -> int:
    """Parse the environment, build the app, and serve it under uvicorn."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = AppConfig.from_env(os.environ)
    except ConfigError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2

    app = create_server_app(config)
    _LOGGER.info(
        "starting control plane host=%s port=%d persistence=%s llm=%s telemetry=%s worker=%s",
        config.bind_host,
        config.bind_port,
        config.persistence,
        config.llm_provider,
        config.telemetry,
        "on" if config.worker_enabled else "off",
    )

    import uvicorn

    uvicorn.run(app, host=config.bind_host, port=config.bind_port, log_level="info")
    return 0
