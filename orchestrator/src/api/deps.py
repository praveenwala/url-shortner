"""Request-scoped dependencies: the engine, and who the caller is.

**Roles come from a server-side directory, never from the request.** A client
supplying `X-Actor-Roles: approver` is ignored — otherwise "the API enforces the
approver role" would mean nothing more than "the client says it holds it".
Identity itself (`X-Actor-Id`) stands in for an authenticated session; wiring
real authentication is deployment work, and the authorisation decision does not
depend on it.
"""

from __future__ import annotations

import os

from sqlalchemy import Engine

from src.engine.identity import APPROVER_ROLE, Actor
from src.store.repository import make_engine

_ENGINE: Engine | None = None


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        dsn = os.environ.get(
            "ORCHESTRATOR_DB_URL",
            "postgresql+psycopg://orchestrator_app@localhost:5432/orchestrator_db",
        )
        _ENGINE = make_engine(dsn)
    return _ENGINE


def role_directory() -> dict[str, frozenset[str]]:
    """Actor → roles, configured server-side.

    `ORCHESTRATOR_APPROVERS` is a comma-separated list of human actor ids. An
    agent id listed there is ignored: `Actor` refuses to hold the approver role.
    """
    raw = os.environ.get("ORCHESTRATOR_APPROVERS", "human:lead")
    return {
        actor_id.strip(): frozenset({APPROVER_ROLE})
        for actor_id in raw.split(",")
        if actor_id.strip() and not actor_id.strip().startswith("agent:")
    }


def resolve_actor(actor_id: str | None) -> Actor:
    """Identity from the caller, roles from the directory."""
    from src.api.errors import ErrorCode, OrchestratorError

    if not actor_id:
        raise OrchestratorError("no authenticated actor", ErrorCode.FORBIDDEN)
    return Actor(id=actor_id, roles=role_directory().get(actor_id, frozenset()))
