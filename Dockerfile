# syntax=docker/dockerfile:1
#
# Multi-stage image for the Incident Evidence Compiler control plane + in-process worker
# (ADR 0016). The builder installs the locked, no-dev environment with uv; the runtime stage
# carries only the virtualenv and source, runs as a non-root user, and health-checks /health
# with the standard library (no curl in the image). No new runtime dependency is introduced.

# ---- builder: resolve and install the locked environment ----
FROM python:3.12-slim-bookworm AS builder

# Pin uv to the exact required version by copying its static binary from the official image;
# UV_PYTHON_DOWNLOADS=0 forces uv to use this base image's interpreter rather than fetch one.
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install third-party dependencies first so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then install the project itself against the already-resolved environment.
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev

# ---- runtime: carry only the virtualenv and the source ----
FROM python:3.12-slim-bookworm AS runtime

RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

# The container is network-isolated, so bind all interfaces here (the bare-process default
# stays loopback). Restrict access to the open /health and /metrics surface at deployment.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IEC_BIND_HOST=0.0.0.0 \
    IEC_BIND_PORT=8000

EXPOSE 8000
USER app

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

CMD ["python", "-m", "incident_evidence_compiler"]
