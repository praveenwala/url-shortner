"""T011 — the orchestrator skeleton is wired and answers health."""

import pytest

pytestmark = pytest.mark.unit


def test_health_endpoint():
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from src.api.app import app

    client = fastapi_testclient.TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "up"
