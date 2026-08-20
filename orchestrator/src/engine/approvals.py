"""Human approval requests and decisions (T064, FR-029, FR-043, FR-050).

An approval authorises **one pending action**, identified by a fingerprint of
the request detail. It is not a general permission, does not persist beyond the
action it was granted for, and cannot be issued by an agent.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Engine, text

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.identity import APPROVER_ROLE, Actor
from src.trace.correlation import now


class Checkpoint(StrEnum):
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    DESTRUCTIVE = "destructive"
    RELEASE = "release"
    GOVERNANCE = "governance"
    SCOPE = "scope"


class Decision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class RequestState(StrEnum):
    PENDING = "pending"
    DECIDED = "decided"


class NotAnApprover(OrchestratorError):
    code = ErrorCode.FORBIDDEN


class RationaleRequired(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


class AlreadyDecided(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


def fingerprint(detail: dict[str, Any]) -> str:
    """Stable identity of the action an approval covers."""
    return hashlib.sha256(
        json.dumps(detail, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    id: str
    run_id: str
    checkpoint: Checkpoint
    detail: dict[str, Any]
    action_fingerprint: str
    requested_by: str
    requested_at: str
    state: RequestState


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    id: str
    request_id: str
    run_id: str
    checkpoint: Checkpoint
    human_actor: str
    approver_role_held: str
    decision: Decision
    rationale: str
    decided_at: str


class ApprovalService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- request -------------------------------------------------------------
    def request(
        self, *, run_id: str, checkpoint: Checkpoint, detail: dict[str, Any],
        requested_by: str,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            id=uuid.uuid4().hex, run_id=run_id, checkpoint=checkpoint, detail=detail,
            action_fingerprint=fingerprint(detail), requested_by=requested_by,
            requested_at=now().isoformat(), state=RequestState.PENDING,
        )
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO approval_request (id, run_id, checkpoint, detail,"
                    " action_fingerprint, requested_by, requested_at, state)"
                    " VALUES (:id,:run,:cp,CAST(:d AS JSONB),:fp,:by,:at,:state)"
                ),
                {"id": request.id, "run": run_id, "cp": str(checkpoint),
                 "d": json.dumps(detail), "fp": request.action_fingerprint,
                 "by": requested_by, "at": request.requested_at, "state": "pending"},
            )
        return request

    def pending(self, run_id: str) -> list[ApprovalRequest]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, run_id, checkpoint, detail, action_fingerprint,"
                    " requested_by, requested_at, state FROM approval_request"
                    " WHERE run_id = :r AND state = 'pending' ORDER BY requested_at"
                ),
                {"r": run_id},
            ).all()
        return [
            ApprovalRequest(r[0], r[1], Checkpoint(r[2]), r[3], r[4], r[5], str(r[6]),
                            RequestState(r[7]))
            for r in rows
        ]

    # -- decide --------------------------------------------------------------
    def decide(
        self, request_id: str, *, actor: Actor, decision: Decision, rationale: str,
    ) -> ApprovalRecord:
        # FR-050: the role check comes first, and an agent never passes it.
        if not actor.holds(APPROVER_ROLE):
            raise NotAnApprover(
                f"{actor.id!r} does not hold the {APPROVER_ROLE!r} role; "
                f"only an approver may decide a checkpoint (FR-029, FR-050)"
            )
        if not rationale or not rationale.strip():
            raise RationaleRequired("an approval decision must carry a rationale")

        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT run_id, checkpoint, state FROM approval_request WHERE id = :id"
                    " FOR UPDATE"
                ),
                {"id": request_id},
            ).one_or_none()
            if row is None:
                raise OrchestratorError(f"unknown approval request {request_id!r}",
                                        ErrorCode.NOT_FOUND)
            run_id, checkpoint, state = row[0], Checkpoint(row[1]), RequestState(row[2])
            if state is RequestState.DECIDED:
                raise AlreadyDecided(f"approval request {request_id!r} is already decided")

            record = ApprovalRecord(
                id=uuid.uuid4().hex, request_id=request_id, run_id=run_id,
                checkpoint=checkpoint, human_actor=actor.id,
                approver_role_held=APPROVER_ROLE, decision=decision,
                rationale=rationale.strip(), decided_at=now().isoformat(),
            )
            conn.execute(
                text(
                    "INSERT INTO approval_record (id, run_id, request_id, checkpoint,"
                    " human_actor, approver_role_held, decision, rationale, decided_at)"
                    " VALUES (:id,:run,:req,:cp,:actor,:role,:dec,:why,:at)"
                ),
                {"id": record.id, "run": run_id, "req": request_id, "cp": str(checkpoint),
                 "actor": actor.id, "role": APPROVER_ROLE, "dec": str(decision),
                 "why": record.rationale, "at": record.decided_at},
            )
            conn.execute(
                text("UPDATE approval_request SET state = 'decided' WHERE id = :id"),
                {"id": request_id},
            )
        return record

    # -- query ---------------------------------------------------------------
    def is_approved(self, request_id: str) -> bool:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT decision FROM approval_record WHERE request_id = :r"
                    " ORDER BY decided_at DESC LIMIT 1"
                ),
                {"r": request_id},
            ).one_or_none()
        return row is not None and Decision(row[0]) is Decision.APPROVED

    def authorises(self, request_id: str, detail: dict[str, Any]) -> bool:
        """An approval covers exactly the action it was requested for."""
        if not self.is_approved(request_id):
            return False
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT action_fingerprint FROM approval_request WHERE id = :id"),
                {"id": request_id},
            ).one_or_none()
        return row is not None and row[0] == fingerprint(detail)

    def decisions_for_run(self, run_id: str) -> list[ApprovalRecord]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, request_id, run_id, checkpoint, human_actor,"
                    " approver_role_held, decision, rationale, decided_at"
                    " FROM approval_record WHERE run_id = :r ORDER BY decided_at"
                ),
                {"r": run_id},
            ).all()
        return [
            ApprovalRecord(r[0], r[1], r[2], Checkpoint(r[3]), r[4], r[5],
                           Decision(r[6]), r[7], str(r[8]))
            for r in rows
        ]
