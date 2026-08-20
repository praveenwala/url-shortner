"""API support for approvals and lineage (checkpoint 2e).

Scope is deliberately narrow: only what a human needs to see and act on a
pending checkpoint, plus the lineage and audit needed to review it. The full
`/v1` surface and the console are checkpoint 2f.

Every route here is a view over recorded state — nothing an approval means
lives only in this layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

from src.api.errors import ErrorCode, OrchestratorError
from src.audit.trace import TraceStore
from src.engine.approvals import ApprovalService, Decision
from src.engine.decisions import DecisionStore
from src.engine.identity import Actor
from src.store.repository import AuditRepository, ChangeStore


@dataclass(frozen=True, slots=True)
class ApprovalsApi:
    engine: Engine

    # -- what needs a human --------------------------------------------------
    def pending(self, run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": request.id,
                "checkpoint": str(request.checkpoint),
                "detail": request.detail,
                "requested_by": request.requested_by,
                "requested_at": request.requested_at,
            }
            for request in ApprovalService(self.engine).pending(run_id)
        ]

    # -- recording a human decision -----------------------------------------
    def decide(
        self, request_id: str, *, actor_id: str, roles: list[str], decision: str,
        rationale: str,
    ) -> dict[str, Any]:
        """The API never invents an actor. Identity is supplied by the caller's
        authenticated session; an agent identity cannot satisfy the approver
        role no matter what roles it claims (FR-050, enforced in `Actor`)."""
        actor = Actor(id=actor_id, roles=frozenset(roles))
        try:
            parsed = Decision(decision)
        except ValueError as exc:
            raise OrchestratorError(
                f"unknown decision {decision!r}", ErrorCode.INVALID_REQUEST
            ) from exc

        record = ApprovalService(self.engine).decide(
            request_id, actor=actor, decision=parsed, rationale=rationale
        )
        return {
            "id": record.id,
            "request_id": record.request_id,
            "checkpoint": str(record.checkpoint),
            "human_actor": record.human_actor,
            "approver_role_held": record.approver_role_held,
            "decision": str(record.decision),
            "rationale": record.rationale,
            "decided_at": record.decided_at,
        }

    # -- review surfaces -----------------------------------------------------
    def decisions(self, run_id: str) -> list[dict[str, Any]]:
        approvals = [
            {
                "kind": "approval", "checkpoint": str(r.checkpoint), "actor": r.human_actor,
                "decision": str(r.decision), "rationale": r.rationale, "at": r.decided_at,
            }
            for r in ApprovalService(self.engine).decisions_for_run(run_id)
        ]
        lineage = [
            {
                "kind": "decision", "selection": r.selection, "actor": r.actor,
                "rationale": r.rationale, "alternatives": r.alternatives,
                "serves_ref": r.serves_ref, "at": r.decided_at,
            }
            for r in DecisionStore(self.engine).for_run(run_id)
        ]
        return sorted(approvals + lineage, key=lambda item: item["at"])

    def audit(self, run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "event_type": e.event_type, "actor": e.actor, "trace_id": e.trace_id,
                "span_id": e.span_id, "payload": e.payload, "occurred_at": e.occurred_at,
            }
            for e in AuditRepository(self.engine).for_run(run_id)
        ]

    def trace(self, *, requirement: str | None = None, change: str | None = None
              ) -> dict[str, Any]:
        store = TraceStore(self.engine)
        if requirement:
            forward = store.for_requirement(requirement)
            return {
                "requirement_ref": forward.requirement_ref, "tasks": list(forward.tasks),
                "changes": list(forward.changes), "tests": list(forward.tests),
            }
        if change:
            return {"change_ref": change, "requirement_ref": store.requirement_for_change(change)}
        raise OrchestratorError(
            "trace requires either a requirement or a change reference",
            ErrorCode.INVALID_REQUEST,
        )

    def untraceable_changes(self, run_id: str) -> list[dict[str, Any]]:
        store = ChangeStore(self.engine)
        ids = TraceStore(self.engine).untraceable_changes(run_id)
        return [
            {"change_id": cid, "artifact_path": (c.artifact_path if c else None)}
            for cid in ids
            for c in [store.get(cid)]
        ]
