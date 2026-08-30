"""Composition root: environment config, process wiring, and the runnable entrypoint.

This is the only package permitted to import every layer at once (persistence drivers, the
LLM adapters, the evaluation-backed demo telemetry source, and the FastAPI control plane).
The domain and application layers stay ignorant of it.
"""

from .config import AppConfig, ConfigError
from .demo_llm import FirstSignalLLMClient
from .prometheus import (
    PrometheusClient,
    PrometheusError,
    PrometheusLimits,
    PrometheusTelemetrySource,
)
from .server import (
    ServerComponents,
    build_components,
    create_server_app,
    main,
    run_worker_loop,
)
from .telemetry import RcaevalTelemetrySource, opaque_case_id

__all__ = [
    "AppConfig",
    "ConfigError",
    "FirstSignalLLMClient",
    "PrometheusClient",
    "PrometheusError",
    "PrometheusLimits",
    "PrometheusTelemetrySource",
    "RcaevalTelemetrySource",
    "ServerComponents",
    "build_components",
    "create_server_app",
    "main",
    "opaque_case_id",
    "run_worker_loop",
]
