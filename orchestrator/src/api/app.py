"""FastAPI skeleton for the orchestrator (T011).

Health only. The `/v1` routes land in checkpoint 2f, which is out of scope for
this run; the bounded agent runtime (2d) and approvals (2e) are not built yet.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request

from src.agent.config import build_policy, install_socket_guard

# The egress allow-list is installed at import time, before any router, client,
# or connection pool exists. Installing it later would leave a window in which
# the process has unrestricted egress, and a guard with a window is a guard that
# has to be argued about rather than relied on.
install_socket_guard(build_policy())

app = FastAPI(title="orchestrator", version="0.1.0")


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
    return {"status": "up", "service": "orchestrator"}
