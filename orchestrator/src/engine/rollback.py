"""Rollback linkage (FR-032, FR-044).

Every rollback is an event linked to the change it reverses. A *failed*
rollback is the dangerous case — the artifact is in neither the old nor the
intended state — so it safe-stops and is audited rather than being retried.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, text

from src.agent.changes import ChangeRecord, revert
from src.api.errors import ErrorCode, OrchestratorError
from src.store.repository import AuditRepository
from src.trace.correlation import Correlation, now


class RollbackFailed(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


@dataclass(frozen=True, slots=True)
class RollbackEvent:
    id: str
    run_id: str
    change_id: str
    outcome: str
    reason: str | None
    occurred_at: str


class RollbackStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(self, event: RollbackEvent) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO rollback_event (id, run_id, change_id, outcome, reason,"
                    " occurred_at) VALUES (:id,:run,:change,:outcome,:reason,:at)"
                ),
                {"id": event.id, "run": event.run_id, "change": event.change_id,
                 "outcome": event.outcome, "reason": event.reason, "at": event.occurred_at},
            )

    def for_change(self, change_id: str) -> list[RollbackEvent]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, run_id, change_id, outcome, reason, occurred_at"
                    " FROM rollback_event WHERE change_id = :c ORDER BY occurred_at"
                ),
                {"c": change_id},
            ).all()
        return [RollbackEvent(r[0], r[1], r[2], r[3], r[4], str(r[5])) for r in rows]


def revert_change(
    *, engine: Engine, run_id: str, change_id: str, record: ChangeRecord, path: Path,
) -> RollbackEvent:
    store = RollbackStore(engine)
    audit = AuditRepository(engine)
    correlation = Correlation(run_id=run_id, actor="orchestrator")

    try:
        revert(record, path)
    except Exception as exc:
        event = RollbackEvent(
            id=uuid.uuid4().hex, run_id=run_id, change_id=change_id, outcome="failed",
            reason=str(exc), occurred_at=now().isoformat(),
        )
        store.record(event)
        audit.append(correlation, "ROLLBACK_FAILED",
                     {"change_id": change_id, "artifact": record.artifact_path,
                      "reason": str(exc)})
        # A failed rollback leaves the artifact in neither state. Stop; do not retry.
        audit.append(correlation.child(), "SAFE_STOP_ROLLBACK_FAILED",
                     {"change_id": change_id, "artifact": record.artifact_path})
        raise RollbackFailed(
            f"rollback of change {change_id!r} failed: {exc}; run safe-stopped"
        ) from exc

    event = RollbackEvent(
        id=uuid.uuid4().hex, run_id=run_id, change_id=change_id, outcome="succeeded",
        reason=None, occurred_at=now().isoformat(),
    )
    store.record(event)
    audit.append(correlation, "ROLLBACK_SUCCEEDED",
                 {"change_id": change_id, "artifact": record.artifact_path})
    return event
