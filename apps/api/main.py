"""
Module: apps/api/main.py
Purpose: FastAPI application factory — middleware registration, router wiring,
         rate-limiting setup, and startup/shutdown lifespan hooks.
         All business logic lives in apps/api/routers/ and application/.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    """Load .env into os.environ before any project module is imported.

    session.py creates the SQLAlchemy engine at module level, so METADATA_DB_URL
    must be in os.environ before the first project import resolves — not just
    inside the startup() hook.  start.py handles this for its own subprocess, but
    direct `uvicorn` / `python -m` invocations would otherwise silently fall back
    to SQLite.
    """
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, val)


_load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from apps.api.comparison_router import router as comparison_router
from apps.api.middleware.auth import AuthMiddleware
from apps.api.routers import (
    admin_router,
    alerts_router,
    assessment_router,
    auth_router,
    connections_router,
    conversion_router,
    discovery_router,
    migrations_router,
    programs_router,
    projects_router,
    reports_router,
    replication_router,
    validation_router,
    workflow_router,
)
from shared.errors.error_catalog import format_error_response
from shared.logging.structured_logging import LoggerContext, configure_logging, get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Rate limiter (slowapi)
# ---------------------------------------------------------------------------

from apps.api.rate_limit import available as _slowapi_available
from apps.api.rate_limit import limiter as _limiter

try:
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
except ImportError:  # pragma: no cover
    RateLimitExceeded = Exception  # type: ignore[misc, assignment]
    _rate_limit_exceeded_handler = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SQL Optima Migration API",
    version="0.2.0",
    description="SQL Optima Migration — SQL Server → PostgreSQL Migration Platform",
)

if _slowapi_available and _limiter is not None and _rate_limit_exceeded_handler is not None:
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Middleware  (outermost-first order)
# ---------------------------------------------------------------------------

app.add_middleware(AuthMiddleware)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        import traceback
        from datetime import UTC, datetime

        start = datetime.now(UTC)
        with LoggerContext(path=request.url.path, method=request.method):
            try:
                response = await call_next(request)
                elapsed = (datetime.now(UTC) - start).total_seconds()
                logger.debug(
                    "request_completed",
                    path=request.url.path,
                    status=response.status_code,
                    ms=round(elapsed * 1000, 1),
                )
                return response
            except Exception as exc:
                elapsed = (datetime.now(UTC) - start).total_seconds()
                logger.error(
                    "request_failed",
                    path=request.url.path,
                    method=request.method,
                    ms=round(elapsed * 1000, 1),
                    error=str(exc),
                    error_type=type(exc).__name__,
                    traceback=traceback.format_exc(),
                )
                import structlog
                cid = structlog.contextvars.get_contextvars().get("correlation_id")
                return JSONResponse(
                    status_code=500,
                    content=format_error_response(str(exc), correlation_id=cid),
                )


app.add_middleware(LoggingMiddleware)

# CORS — default allows any HTTP/HTTPS origin so the UI is reachable via IP address,
# hostname, or localhost without extra configuration.  JWT authentication still
# protects every non-public endpoint regardless of origin.
# To restrict: set MIGRATION_ALLOWED_ORIGINS to a comma-separated list of origins.
_CORS_ORIGINS_RAW = os.environ.get("MIGRATION_ALLOWED_ORIGINS", "").strip()

if _CORS_ORIGINS_RAW and _CORS_ORIGINS_RAW != "*":
    # Explicit allowlist provided — use it (with_credentials=True requires echoing origin)
    _cors_kwargs: dict = {
        "allow_origins": [o.strip() for o in _CORS_ORIGINS_RAW.split(",") if o.strip()],
    }
else:
    # Default / wildcard: accept any HTTP or HTTPS origin via regex so that
    # IP addresses, hostnames, and localhost all work out of the box.
    _cors_kwargs = {"allow_origin_regex": r"https?://.*"}

app.add_middleware(
    CORSMiddleware,
    **_cors_kwargs,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

_V1 = "/api/v1"

app.include_router(auth_router.router, prefix=_V1)
app.include_router(connections_router.router, prefix=_V1)
app.include_router(migrations_router.router, prefix=_V1)
app.include_router(alerts_router.router, prefix=_V1)
app.include_router(conversion_router.router, prefix=_V1)
app.include_router(validation_router.router, prefix=_V1)
app.include_router(discovery_router.router, prefix=_V1)
app.include_router(assessment_router.router, prefix=_V1)
app.include_router(projects_router.router, prefix=_V1)
app.include_router(programs_router.router, prefix=_V1)
app.include_router(reports_router.router, prefix=_V1)
app.include_router(admin_router.router, prefix=_V1)
app.include_router(workflow_router.router, prefix=_V1)
app.include_router(replication_router.router, prefix=_V1)
app.include_router(comparison_router)  # already prefixed with /api/comparison

# ---------------------------------------------------------------------------
# Backward-compatibility: redirect flat paths → /api/v1/…  (308 permanent)
# Clients that still use the old flat routes are redirected transparently.
# Remove these after one deprecation cycle.
# ---------------------------------------------------------------------------

_LEGACY_PREFIXES = (
    "/auth/", "/connections", "/migrations", "/convert", "/sql/",
    "/jobs/", "/users", "/projects", "/reports/", "/admin/",
    "/create-database", "/discover", "/assess", "/validation-runs/",
)


@app.middleware("http")
async def legacy_route_redirect(request: Request, call_next):  # type: ignore[override]
    path = request.url.path
    if path.startswith(_LEGACY_PREFIXES) and not path.startswith(("/api/", "/health", "/docs", "/openapi", "/redoc")):
        new_path = f"/api/v1{path}"
        if request.url.query:
            new_path = f"{new_path}?{request.url.query}"
        return JSONResponse(
            status_code=308,
            content={"detail": f"Moved permanently to {new_path}"},
            headers={"Location": new_path},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Lifespan hooks
# ---------------------------------------------------------------------------

_REQUIRED_ENV_VARS = (
    "MIGRATION_JWT_SECRET",
    "MIGRATION_MASTER_KEY",
)


@app.on_event("startup")
async def startup() -> None:
    configure_logging(
        level=os.environ.get("MIGRATION_LOG_LEVEL", "INFO"),
        json_output=os.environ.get("MIGRATION_LOG_JSON", "").lower() in ("1", "true", "yes"),
        log_to_file=os.environ.get("MIGRATION_LOG_FILE", "1").lower() not in ("0", "false", "no"),
    )
    missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"Required env vars not set: {', '.join(missing)}. See .env.example."
        )
    import application.migration_service as migration_svc
    from apps.api.connection_store import load_connections, set_secret_provider, set_secrets_manager
    from apps.api.dependencies import set_secret_provider as dep_set_secret_provider
    from apps.api.dependencies import set_secrets
    from infrastructure.metadata_db.session import AsyncSessionFactory, init_db
    from shared.security.secret_provider import build_secret_provider
    from shared.security.secrets_manager import SecretsManager

    sm = SecretsManager()
    set_secrets(sm)
    set_secrets_manager(sm)

    sp = build_secret_provider()
    set_secret_provider(sp)
    dep_set_secret_provider(sp)

    try:
        await init_db()
    except Exception as exc:
        db_url = os.environ.get("METADATA_DB_URL", "sqlite (default)")
        raise RuntimeError(
            f"Cannot connect to metadata database ({db_url}). "
            "If using PostgreSQL, ensure the container is running: "
            "`docker-compose up postgres_checklist -d`. "
            "To use SQLite locally, remove METADATA_DB_URL from .env."
        ) from exc
    from apps.api.startup_checks import run_startup_checks
    await run_startup_checks()
    await load_connections()
    await migration_svc.load_jobs()
    try:
        from application.audit_service import AuditService

        async with AsyncSessionFactory() as session:
            await AuditService(session).purge_expired_tokens()
    except Exception:
        pass
    logger.info("startup_complete", version="0.2.0", rate_limiting=_slowapi_available)


@app.on_event("shutdown")
async def shutdown() -> None:
    import application.migration_service as migration_svc
    import application.replication_service as replication_svc

    repl_stopped = await replication_svc.stop_all_streams()
    tasks = migration_svc.cancel_all_tasks()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("shutdown_complete", cancelled_tasks=len(tasks), replication_streams_stopped=repl_stopped)


# ---------------------------------------------------------------------------
# Health check (unauthenticated)
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    from datetime import UTC, datetime

    return {
        "status": "ok",
        "version": "0.2.0",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/metrics")
async def prometheus_metrics() -> Any:
    """Prometheus text exposition of migration throughput and failure counters."""
    from starlette.responses import PlainTextResponse

    from domains.observability.prometheus_exporter import render_prometheus

    return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4")


@app.get("/health/deep")
async def health_deep() -> JSONResponse:
    """Deep health check: probes the metadata DB, encryption, and Redis.

    Returns 200 when every dependency is healthy, 503 otherwise — suitable for
    readiness gating. Unauthenticated, like /health, but reveals only boolean
    status and short details (no secrets/stack traces).
    """
    from datetime import UTC, datetime

    from apps.api.dependencies import get_secrets
    from apps.api.health_checks import run_all_checks
    from infrastructure.metadata_db.session import AsyncSessionFactory

    try:
        secrets = get_secrets()
    except Exception:
        secrets = None

    report = await run_all_checks(
        session_factory=AsyncSessionFactory,
        secrets_manager=secrets,
        redis_client=None,
    )
    report["timestamp"] = datetime.now(UTC).isoformat()
    return JSONResponse(content=report, status_code=200 if report["healthy"] else 503)
