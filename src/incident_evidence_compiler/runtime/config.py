"""Environment-only, fail-fast runtime configuration (ADR 0016).

``AppConfig.from_env`` is a pure function of a string mapping: it validates every knob and
raises a typed ``ConfigError`` with a stable, secret-free message on any missing or invalid
value. Nothing is silently defaulted into a production-shaped lie, and no secret value is
ever echoed back in an error.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_PERSISTENCE_CHOICES = ("memory", "postgres")
_LLM_CHOICES = ("fake", "developer", "vertex")
_TELEMETRY_CHOICES = ("none", "rcaeval", "prometheus")
_DEFAULT_MODEL = "gemini-2.5-flash"
_DEFAULT_LOCATION = "us-central1"
# PromQL label lists contain commas, so a comma cannot separate selectors the way it does for
# IEC_TOKENS. A semicolon has no meaning in PromQL, so it separates them unambiguously.
_QUERY_SEPARATOR = ";"


class ConfigError(Exception):
    """A stable, secret-free configuration failure raised before the server starts."""


def _choice(env: Mapping[str, str], key: str, choices: tuple[str, ...], default: str) -> str:
    value = env.get(key, default).strip()
    if value not in choices:
        raise ConfigError(f"{key} must be one of {', '.join(choices)}")
    return value


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} is required")
    return value


def _parse_tokens(raw: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for pair in raw.split(","):
        token, separator, tenant = pair.partition("=")
        token = token.strip()
        tenant = tenant.strip()
        if separator != "=" or not token or not tenant:
            raise ConfigError("IEC_TOKENS must be comma-separated token=tenant pairs")
        tokens[token] = tenant
    if not tokens:
        raise ConfigError("IEC_TOKENS is required")
    return tokens


def _parse_port(env: Mapping[str, str]) -> int:
    raw = env.get("IEC_BIND_PORT", "8000").strip()
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError("IEC_BIND_PORT must be an integer") from None
    if not 1 <= port <= 65535:
        raise ConfigError("IEC_BIND_PORT must be in 1..65535")
    return port


def _parse_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be a boolean (1/0, true/false)")


def _parse_positive_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number") from None
    if not value > 0.0:
        raise ConfigError(f"{key} must be strictly positive")
    return value


def _parse_optional_nonnegative_float(env: Mapping[str, str], key: str) -> float | None:
    if key not in env:
        return None
    raw = env[key].strip()
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a number") from None
    if not math.isfinite(value) or value < 0.0:
        raise ConfigError(f"{key} must be a finite number >= 0.0")
    return value


def _parse_positive_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be an integer") from None
    if value < 1:
        raise ConfigError(f"{key} must be strictly positive")
    return value


def _parse_queries(raw: str) -> tuple[str, ...]:
    queries = tuple(part.strip() for part in raw.split(_QUERY_SEPARATOR) if part.strip())
    if not queries:
        raise ConfigError("IEC_PROM_QUERIES must contain at least one PromQL selector")
    return queries


@dataclass(frozen=True, slots=True)
class AppConfig:
    """The fully-validated runtime configuration for one process."""

    tokens: dict[str, str]
    persistence: str
    database_url: str | None
    llm_provider: str
    gemini_api_key: str | None
    gemini_project: str | None
    gemini_location: str
    gemini_model: str
    telemetry: str
    re2_root: Path | None
    re2_split: str
    prom_url: str | None
    prom_queries: tuple[str, ...]
    prom_step_seconds: int
    prom_timeout_seconds: float
    prom_bearer_token: str | None
    bind_host: str
    bind_port: int
    worker_enabled: bool
    worker_idle_sleep_seconds: float
    baseline_minimum_score: float | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AppConfig":
        tokens = _parse_tokens(_require(env, "IEC_TOKENS"))

        persistence = _choice(env, "IEC_PERSISTENCE", _PERSISTENCE_CHOICES, "memory")
        database_url = _require(env, "IEC_DATABASE_URL") if persistence == "postgres" else None

        provider = _choice(env, "IEC_LLM_PROVIDER", _LLM_CHOICES, "fake")
        gemini_api_key = _require(env, "GEMINI_API_KEY") if provider == "developer" else None
        gemini_project = _require(env, "IEC_GEMINI_PROJECT") if provider == "vertex" else None
        gemini_location = env.get("IEC_GEMINI_LOCATION", _DEFAULT_LOCATION).strip()
        gemini_model = env.get("IEC_GEMINI_MODEL", _DEFAULT_MODEL).strip()

        telemetry = _choice(env, "IEC_TELEMETRY", _TELEMETRY_CHOICES, "none")
        re2_root = Path(_require(env, "IEC_RE2_ROOT")) if telemetry == "rcaeval" else None
        re2_split = env.get("IEC_RE2_SPLIT", "OB").strip()

        live = telemetry == "prometheus"
        prom_url = _require(env, "IEC_PROM_URL") if live else None
        prom_queries = _parse_queries(_require(env, "IEC_PROM_QUERIES")) if live else ()
        # The token is read but never echoed: no ConfigError message includes a value.
        prom_bearer_token = (env.get("IEC_PROM_BEARER_TOKEN", "").strip() or None) if live else None

        return cls(
            tokens=tokens,
            persistence=persistence,
            database_url=database_url,
            llm_provider=provider,
            gemini_api_key=gemini_api_key,
            gemini_project=gemini_project,
            gemini_location=gemini_location or _DEFAULT_LOCATION,
            gemini_model=gemini_model or _DEFAULT_MODEL,
            telemetry=telemetry,
            re2_root=re2_root,
            re2_split=re2_split or "OB",
            prom_url=prom_url,
            prom_queries=prom_queries,
            prom_step_seconds=_parse_positive_int(env, "IEC_PROM_STEP_SECONDS", 30),
            prom_timeout_seconds=_parse_positive_float(env, "IEC_PROM_TIMEOUT_SECONDS", 30.0),
            prom_bearer_token=prom_bearer_token,
            bind_host=env.get("IEC_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1",
            bind_port=_parse_port(env),
            worker_enabled=_parse_bool(env, "IEC_WORKER_ENABLED", True),
            worker_idle_sleep_seconds=_parse_positive_float(
                env, "IEC_WORKER_IDLE_SLEEP_SECONDS", 1.0
            ),
            baseline_minimum_score=_parse_optional_nonnegative_float(env, "IEC_BASELINE_MIN_SCORE"),
        )
