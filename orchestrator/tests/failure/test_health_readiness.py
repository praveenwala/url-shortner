"""Liveness and readiness are different questions (production-hardening).

Before this split there was one static `/health` that touched nothing, so it answered "up" while
every data endpoint returned 500 — a trap this project hit for real during T103 validation.

The rules being pinned:

* **Liveness must not fail on a dependency outage.** A restart cannot fix an unreachable database,
  so failing liveness produces a restart loop instead of a recovery.
* **Readiness must fail on one**, promptly, and must not hang.
* **Neither may leak a credential** — a DSN carries a password, and driver messages quote the DSN.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.failure

SENTINEL = "readiness-probe-password-not-real"
DEAD_DSN = f"postgresql+psycopg://orchestrator:{SENTINEL}@127.0.0.1:1/orchestrator_db"


def client(monkeypatch, dsn: str) -> TestClient:
    """A fresh app bound to `dsn`; the engine singleton is reset so the DSN actually applies."""
    from src.api import deps
    from src.api.app import app

    monkeypatch.setenv("ORCHESTRATOR_DB_URL", dsn)
    monkeypatch.setattr(deps, "_ENGINE", None)
    return TestClient(app, raise_server_exceptions=False)


# --- database unavailable -----------------------------------------------------

def test_liveness_stays_healthy_when_the_database_is_unavailable(monkeypatch):
    c = client(monkeypatch, DEAD_DSN)
    response = c.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "up"


def test_readiness_fails_when_the_database_is_unavailable(monkeypatch):
    c = client(monkeypatch, DEAD_DSN)
    response = c.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["dependency"] == "postgresql"
    assert body["error_type"], "the failure type is what makes this diagnosable"


def test_readiness_does_not_hang(monkeypatch):
    """A probe that blocks trips its deadline and causes the restart loop we are avoiding."""
    c = client(monkeypatch, DEAD_DSN)
    started = time.monotonic()
    c.get("/ready")
    assert time.monotonic() - started < 15, "readiness probe is not promptly bounded"


def test_readiness_failure_leaks_no_credential(monkeypatch):
    c = client(monkeypatch, DEAD_DSN)
    body = c.get("/ready").text
    assert SENTINEL not in body
    assert "postgresql+psycopg://" not in body


# --- database available -------------------------------------------------------

def test_readiness_recovers_when_the_database_is_reachable(monkeypatch, postgres_dsn):
    c = client(monkeypatch, postgres_dsn)
    response = c.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_liveness_and_readiness_are_distinct_endpoints(monkeypatch, postgres_dsn):
    c = client(monkeypatch, postgres_dsn)
    assert c.get("/health").json()["status"] == "up"
    assert c.get("/ready").json()["status"] == "ready"
