"""Scope boundary (FR-039) and governance protection (FR-040).

Both are the same shape and it is worth naming: the work is **halted and
surfaced for a human**, not silently refused and not silently absorbed. A run
that quietly widened its own scope, or an agent that edited the constitution
because nothing stopped it, are the two failures these prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Engine, text

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.approvals import ApprovalService, Checkpoint
from src.engine.decompose import TaskNode

GOVERNANCE_PREFIXES: tuple[str, ...] = (
    ".specify/", "specs/", "ops/", ".github/",
)


class ScopeViolation(OrchestratorError):
    code = ErrorCode.FORBIDDEN


class GovernanceViolation(OrchestratorError):
    code = ErrorCode.FORBIDDEN


def classify_governance_path(path: str) -> Checkpoint | None:
    """Governance artifacts: constitution, plan, task definitions, approval
    policy, gate definitions, and the operational scripts that enforce them."""
    normalised = path.lstrip("./")
    if any(normalised.startswith(prefix.lstrip("./")) for prefix in GOVERNANCE_PREFIXES):
        return Checkpoint.GOVERNANCE
    return None


@dataclass(slots=True)
class Guardrails:
    engine: Engine
    approvals: ApprovalService

    # -- FR-039 --------------------------------------------------------------
    def approved_scope(self, run_id: str) -> tuple[str, ...]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT approved_scope FROM workflow_run WHERE id = :id"),
                {"id": run_id},
            ).one_or_none()
        if row is None:
            raise OrchestratorError(f"unknown run {run_id!r}", ErrorCode.NOT_FOUND)
        return tuple(row[0] or ())

    def assert_task_in_scope(self, run_id: str, task: TaskNode) -> None:
        scope = self.approved_scope(run_id)
        if task.requirement_ref in scope:
            return
        detail = {
            "action": "task_out_of_scope",
            "task_id": task.id,
            "requirement_ref": task.requirement_ref,
            "approved_scope": list(scope),
        }
        self.approvals.request(
            run_id=run_id, checkpoint=Checkpoint.SCOPE, detail=detail,
            requested_by="orchestrator",
        )
        raise ScopeViolation(
            f"task {task.id!r} serves {task.requirement_ref!r}, which is outside this run's "
            f"approved scope {list(scope)}; halted and surfaced for human decision (FR-039)"
        )

    def widen_scope_from_approval(self, run_id: str, request_id: str) -> tuple[str, ...]:
        """Scope grows only through a recorded approval, never by absorption."""
        if not self.approvals.is_approved(request_id):
            raise ScopeViolation(
                f"approval request {request_id!r} was not approved; scope unchanged"
            )
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT detail FROM approval_request WHERE id = :id"), {"id": request_id}
            ).one()
            ref = row[0]["requirement_ref"]
            current = list(
                conn.execute(
                    text("SELECT approved_scope FROM workflow_run WHERE id = :id"),
                    {"id": run_id},
                ).one()[0]
                or []
            )
            if ref not in current:
                current.append(ref)
            conn.execute(
                text("UPDATE workflow_run SET approved_scope = CAST(:s AS JSONB) WHERE id = :id"),
                {"s": json.dumps(current), "id": run_id},
            )
        return tuple(current)

    # -- FR-040 --------------------------------------------------------------
    def assert_governance_write_allowed(
        self, run_id: str, path: str, *, requested_by: str
    ) -> None:
        if classify_governance_path(path) is None:
            return

        detail = {"action": "write_file", "path": path}
        for request in self._decided_governance_requests(run_id):
            if self.approvals.authorises(request, detail):
                return

        self.approvals.request(
            run_id=run_id, checkpoint=Checkpoint.GOVERNANCE, detail=detail,
            requested_by=requested_by,
        )
        raise GovernanceViolation(
            f"{path!r} is a governance artifact and cannot be modified without explicit "
            f"human approval (FR-040); halted and surfaced"
        )

    def _decided_governance_requests(self, run_id: str) -> list[str]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id FROM approval_request WHERE run_id = :r"
                    " AND checkpoint = 'governance' AND state = 'decided'"
                ),
                {"r": run_id},
            ).all()
        return [r[0] for r in rows]
