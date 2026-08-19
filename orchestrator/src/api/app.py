"""FastAPI skeleton for the orchestrator (T011).

Health only. The `/v1` routes land in checkpoint 2f, which is out of scope for
this run; the bounded agent runtime (2d) and approvals (2e) are not built yet.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="orchestrator", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "up", "service": "orchestrator"}
