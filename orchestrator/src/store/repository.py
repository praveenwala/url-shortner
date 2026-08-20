"""Persistence for the orchestrator (FR-025, FR-036).

Design rule this module exists to enforce: **the audit trail has no update and
no delete path**. `AuditRepository` exposes `append` and read methods only —
there is no code path in this service that can modify a recorded audit event.
Database privilege is the second layer (ops/db/provision.sql, a HUMAN task);
this is the first.
"""

from __future__ import annotations

import json
import re
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

#: Credential *shapes*, checked against values. Audit details are free text —
#: `dispatch._audit` records `str(exc)`, and an exception message is exactly
#: where a connection string or an auth header ends up. Checking key names alone
#: cannot see any of that, because the key is simply `detail`.
_SECRET_VALUE_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("credentials embedded in a URL", re.compile(r"://[^/\s:@]+:[^/\s@]+@")),
    ("an API key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("an authorization header", re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._\-+/=]{16,}")),
    (
        "an inline credential assignment",
        re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|token)\s*[=:]\s*\S"),
    ),
)


def _reject_secrets(payload: dict[str, Any]) -> None:
    """FR-038: audit payloads carry no secrets. Fail loudly rather than redact quietly.

    Both sides are checked: a key that *names* a secret, and a value that *looks
    like* one. The error names the pattern that matched and never the text that
    matched it — an exception raised to prevent a credential being written down
    must not write the credential down.
    """
    for key in _flatten_keys(payload):
        if any(hint in key.lower() for hint in _SECRET_HINTS):
            raise OrchestratorError(
                f"refusing to audit a payload containing key {key!r}", ErrorCode.FORBIDDEN
            )
    for key, value in _flatten_values(payload):
        for description, pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                raise OrchestratorError(
                    f"refusing to audit a payload whose {key!r} value contains {description}",
                    ErrorCode.FORBIDDEN,
                )


def _flatten_values(obj: Any, prefix: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _flatten_values(v, prefix=f"{prefix}{k}")
    elif isinstance(obj, list):
        for item in obj:
            yield from _flatten_values(item, prefix=prefix)
    elif isinstance(obj, str):
        yield prefix or "<root>", obj


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


# --- change records -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredChange:
    id: str
    run_id: str
    task_id: str
    surface: str
    artifact_path: str
    execution_mode: str
    existed: bool
    prior_state: str | None
    prior_sha256: str | None
    new_sha256: str
    applied_at: str
    approving_human: str | None


class ChangeStore:
    """Persists ChangeRecord values so rollback can find them after a restart."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def persist(self, record: Any, run_id: str) -> str:
        import uuid

        change_id = uuid.uuid4().hex
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO change_record (id, run_id, task_id, surface, artifact_path,"
                    " execution_mode, existed, prior_state, prior_sha256, new_sha256,"
                    " applied_at, approving_human)"
                    " VALUES (:id,:run,:task,:surface,:path,:mode,:existed,:prior,:psha,"
                    ":nsha,:at,:human)"
                ),
                {
                    "id": change_id, "run": run_id, "task": record.task_id,
                    "surface": record.surface, "path": record.artifact_path,
                    "mode": record.execution_mode, "existed": record.existed,
                    "prior": record.prior_state, "psha": record.prior_sha256,
                    "nsha": record.new_sha256, "at": record.applied_at,
                    "human": record.approving_human,
                },
            )
        return change_id

    def for_run(self, run_id: str) -> list[StoredChange]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, run_id, task_id, surface, artifact_path, execution_mode,"
                    " existed, prior_state, prior_sha256, new_sha256, applied_at,"
                    " approving_human FROM change_record WHERE run_id = :r ORDER BY applied_at"
                ),
                {"r": run_id},
            ).all()
        return [
            StoredChange(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                         str(r[10]), r[11])
            for r in rows
        ]

    def get(self, change_id: str) -> StoredChange | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT id, run_id, task_id, surface, artifact_path, execution_mode,"
                    " existed, prior_state, prior_sha256, new_sha256, applied_at,"
                    " approving_human FROM change_record WHERE id = :id"
                ),
                {"id": change_id},
            ).one_or_none()
        if row is None:
            return None
        return StoredChange(row[0], row[1], row[2], row[3], row[4], row[5], row[6],
                            row[7], row[8], row[9], str(row[10]), row[11])
