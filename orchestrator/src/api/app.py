"""FastAPI skeleton for the orchestrator (T011).

Health only. The `/v1` routes land in checkpoint 2f, which is out of scope for
this run; the bounded agent runtime (2d) and approvals (2e) are not built yet.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from starlette.requests import Request

from src.agent.config import build_policy, install_socket_guard
from src.obs import logging as olog

# The egress allow-list is installed at import time, before any router, client,
# or connection pool exists. Installing it later would leave a window in which
# the process has unrestricted egress, and a guard with a window is a guard that
# has to be argued about rather than relied on.
install_socket_guard(build_policy())

olog.configure()
olog.log("orchestrator_started", outcome="ready")

@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown markers. `on_event` is deprecated in FastAPI; this is the supported form."""
    yield
    olog.log("orchestrator_stopping", outcome="stopping")


app = FastAPI(title="orchestrator", version="0.1.0", lifespan=_lifespan)


@app.exception_handler(HTTPException)
async def _error_shape(request: Request, exc: HTTPException) -> JSONResponse:
    """Return the error shape the contract specifies.

    FastAPI nests `detail` by default; `contracts/orchestrator-api.md` specifies
    a flat `{error, message}` with a stable identifier, so a client can branch on
    `error` without parsing prose.
    """
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "invalid_request", "message": str(exc.detail)},
    )

from src.api.routes import router

app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness. Deliberately touches nothing.

    This answers "is the process alive", and must keep answering yes while the database is down —
    otherwise an orchestrator restarts a healthy process in a loop that cannot fix a dependency
    outage. Readiness is a separate question with a separate endpoint.
    """
    return {"status": "up", "service": "orchestrator"}


#: Bounded so a probe fails fast rather than hanging on an unreachable database.
READINESS_TIMEOUT_SECONDS = 2


@app.get("/ready", responses={503: {"description": "a required dependency is unavailable"}})
def ready(response: Response) -> dict[str, Any]:
    """Readiness. Requires the database, within a bounded timeout.

    Returns 503 rather than raising, so a probe reads a status code instead of a stack trace. The
    body names *which* dependency failed and its exception type — never the DSN, which carries a
    password, and never the driver message, which quotes the DSN.
    """

    from src.api.deps import get_engine

    try:
        engine = get_engine()
        with engine.connect().execution_options(
            timeout=READINESS_TIMEOUT_SECONDS
        ) as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - any failure to reach the database is "not ready"
        olog.error(
            "postgres_readiness_failed",
            type(exc).__name__,
            outcome="not_ready",
        )
        response.status_code = 503
        return {
            "status": "not_ready",
            "service": "orchestrator",
            "dependency": "postgresql",
            "error_type": type(exc).__name__,
        }
    return {"status": "ready", "service": "orchestrator", "dependency": "postgresql"}
