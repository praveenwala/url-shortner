"""Clarification requests and human answers (FR-028, FR-046, FR-049).

The ordering rule this module exists to enforce: the answer is **persisted
before** the run leaves WAITING_FOR_HUMAN. Resuming on a client's say-so, or on
an in-memory answer, would let a lost write resume a run that was never actually
clarified.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Engine, text

from src.api.errors import ErrorCode, OrchestratorError
from src.trace.correlation import now


class ClarificationState(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"


class AnswerRequired(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


class AlreadyAnswered(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


@dataclass(frozen=True, slots=True)
class ClarificationRequest:
    id: str
    run_id: str
    question: str
    affects: str
    requested_by: str
    requested_at: str
    state: ClarificationState
    answer: str | None = None
    answered_by: str | None = None
    answered_at: str | None = None
    requirement_id: str | None = None
    round: int = 1
    rule: str | None = None


class ClarificationService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def request(self, *, run_id: str, question: str, affects: str, requested_by: str,
                requirement_id: str | None = None, round: int = 1, rule: str | None = None,
                ) -> ClarificationRequest:
        if not question.strip().endswith("?"):
            raise OrchestratorError(
                "a clarification must be a specific answerable question (FR-028)",
                ErrorCode.INVALID_REQUEST,
            )
        record = ClarificationRequest(
            id=uuid.uuid4().hex, run_id=run_id, question=question.strip(), affects=affects,
            requested_by=requested_by, requested_at=now().isoformat(),
            state=ClarificationState.PENDING, requirement_id=requirement_id,
            round=round, rule=rule,
        )
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO clarification_request (id, run_id, question, affects,"
                    " requested_by, requested_at, state, requirement_id, round, rule)"
                    " VALUES (:id,:run,:q,:aff,:by,:at,'pending',:req,:round,:rule)"
                ),
                {"id": record.id, "run": run_id, "q": record.question, "aff": affects,
                 "by": requested_by, "at": record.requested_at, "req": requirement_id,
                 "round": round, "rule": rule},
            )
        return record

    def pending(self, run_id: str) -> list[ClarificationRequest]:
        return [r for r in self._select("run_id = :r AND state = 'pending'", {"r": run_id})]

    def get(self, request_id: str) -> ClarificationRequest | None:
        rows = self._select("id = :id", {"id": request_id})
        return rows[0] if rows else None

    def answered(self, run_id: str) -> list[ClarificationRequest]:
        return self._select("run_id = :r AND state = 'answered'", {"r": run_id})

    def answer(self, request_id: str, *, answer: str, answered_by: str
               ) -> ClarificationRequest:
        """Persist first. The caller resumes the run only after this returns."""
        if not answer or not answer.strip():
            raise AnswerRequired("a clarification answer must not be empty")

        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT state FROM clarification_request WHERE id = :id FOR UPDATE"),
                {"id": request_id},
            ).one_or_none()
            if row is None:
                raise OrchestratorError(
                    f"unknown clarification {request_id!r}", ErrorCode.NOT_FOUND
                )
            if ClarificationState(row[0]) is ClarificationState.ANSWERED:
                raise AlreadyAnswered(f"clarification {request_id!r} is already answered")
            conn.execute(
                text(
                    "UPDATE clarification_request SET state = 'answered', answer = :a,"
                    " answered_by = :by, answered_at = :at WHERE id = :id"
                ),
                {"a": answer.strip(), "by": answered_by, "at": now(), "id": request_id},
            )
        result = self.get(request_id)
        assert result is not None
        return result

    def _select(self, where: str, params: dict) -> list[ClarificationRequest]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, run_id, question, affects, requested_by, requested_at,"
                    " state, answer, answered_by, answered_at, requirement_id, round, rule"
                    f" FROM clarification_request WHERE {where} ORDER BY requested_at"
                ),
                params,
            ).all()
        return [
            ClarificationRequest(
                r[0], r[1], r[2], r[3], r[4], str(r[5]), ClarificationState(r[6]),
                r[7], r[8], str(r[9]) if r[9] else None, r[10], r[11], r[12],
            )
            for r in rows
        ]
