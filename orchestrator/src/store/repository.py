"""Persistence for the orchestrator (FR-025, FR-036).

Design rule this module exists to enforce: **the audit trail has no update and
no delete path**. `AuditRepository` exposes `append` and read methods only —
there is no code path in this service that can modify a recorded audit event.
Database privilege is the second layer (ops/db/provision.sql, a HUMAN task);
this is the first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import Engine, create_engine, text

from src.api.errors import ErrorCode, OrchestratorError
from src.trace.correlation import Correlation

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def make_engine(dsn: str) -> Engine:
    return create_engine(dsn, future=True)


def apply_migrations(engine: Engine) -> list[str]:
    """Apply every .sql migration in order. Returns the filenames applied."""
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        with engine.begin() as conn:
            conn.execute(text(path.read_text()))
        applied.append(path.name)
    return applied


@dataclass(frozen=True, slots=True)
class AuditEvent:
    run_id: str
    event_type: str
    actor: str
    trace_id: str
    span_id: str
    payload: dict[str, Any]
    occurred_at: str


class AuditRepository:
    """Append-only. No update, no delete — deliberately (FR-036, NFR-004)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, correlation: Correlation, event_type: str, payload: dict[str, Any]) -> int:
        if correlation.run_id is None:
            raise OrchestratorError("audit events require a run_id", ErrorCode.INVALID_REQUEST)
        _reject_secrets(payload)
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO audit_event (run_id, event_type, actor, trace_id, span_id,"
                    " payload, occurred_at) VALUES (:run_id, :event_type, :actor, :trace_id,"
                    " :span_id, CAST(:payload AS JSONB), :occurred_at) RETURNING id"
                ),
                {
                    "run_id": correlation.run_id,
                    "event_type": event_type,
                    "actor": correlation.actor,
                    "trace_id": correlation.trace_id,
                    "span_id": correlation.span_id,
                    "payload": json.dumps(payload),
                    "occurred_at": correlation.occurred_at,
                },
            ).one()
        return int(row[0])

    def for_run(self, run_id: str) -> list[AuditEvent]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT run_id, event_type, actor, trace_id, span_id, payload, occurred_at"
                    " FROM audit_event WHERE run_id = :run_id ORDER BY id"
                ),
                {"run_id": run_id},
            ).all()
        return [
            AuditEvent(r[0], r[1], r[2], r[3], r[4], r[5], r[6].isoformat()) for r in rows
        ]

    def count(self, run_id: str) -> int:
        with self._engine.begin() as conn:
            return int(
                conn.execute(
                    text("SELECT count(*) FROM audit_event WHERE run_id = :r"), {"r": run_id}
                ).scalar_one()
            )


_SECRET_HINTS = ("password", "secret", "api_key", "apikey", "token", "credential", "authorization")


def _reject_secrets(payload: dict[str, Any]) -> None:
    """FR-038: audit payloads carry no secrets. Fail loudly rather than redact quietly."""
    for key in _flatten_keys(payload):
        if any(hint in key.lower() for hint in _SECRET_HINTS):
            raise OrchestratorError(
                f"refusing to audit a payload containing key {key!r}", ErrorCode.FORBIDDEN
            )


def _flatten_keys(obj: Any, prefix: str = "") -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{prefix}{k}"
            yield from _flatten_keys(v, prefix=f"{prefix}{k}.")
    elif isinstance(obj, list):
        for item in obj:
            yield from _flatten_keys(item, prefix=prefix)


AUDIT_MUTATION_METHODS = ("update", "delete", "remove", "purge", "truncate")


def audit_repository_is_append_only() -> bool:
    """Structural self-check used by the store-shape test (T031)."""
    names = {n for n in dir(AuditRepository) if not n.startswith("_")}
    return not any(any(m in n.lower() for m in AUDIT_MUTATION_METHODS) for n in names)
