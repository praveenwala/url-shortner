"""Orchestration API for the two console views (checkpoint 2f).

Only what RunView and HumanActionView need. Every response is a projection of
recorded state — nothing an approval or clarification means lives in this layer,
and nothing the console shows exists only in the browser.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from src.api import deps
from src.api.errors import ErrorCode, OrchestratorError
from src.audit.metrics import MetricsService
from src.audit.trace import TraceStore
from src.engine.approvals import AlreadyDecided, ApprovalService, Decision, NotAnApprover
from src.engine.clarifications import (
    AlreadyAnswered,
    AnswerRequired,
    ClarificationService,
)
from src.engine.decisions import DecisionStore
from src.engine.identity import AgentCannotHoldApproverRole
from src.engine.state import StateStore
from src.models.states import RunState
from src.store.repository import AuditRepository

router = APIRouter(prefix="/v1")


def _engine():
    return deps.get_engine() if deps._ENGINE is None else deps._ENGINE


def _actor(actor_id: str | None):
    try:
        return deps.resolve_actor(actor_id)
    except AgentCannotHoldApproverRole as exc:  # cannot happen: directory excludes agents
        raise HTTPException(403, {"error": "forbidden", "message": str(exc)}) from exc
    except OrchestratorError as exc:
        raise HTTPException(401, {"error": "forbidden", "message": str(exc)}) from exc


# --- request bodies ---------------------------------------------------------

class ApiErrorBody(BaseModel):
    """The stable error envelope every failure uses (contracts/orchestrator-api.md).

    Declared as a response model so the generated OpenAPI *says* so. Without this the
    document advertises only FastAPI's 422 validation shape, and a client reading the
    published contract would not know an `error` identifier exists to branch on.
    """

    error: str
    message: str


#: Attached to every route that can fail. The status codes are the ones the handlers
#: actually raise — see the status mapping in contracts/orchestrator-api.md.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ApiErrorBody, "description": "invalid_request"},
    401: {"model": ApiErrorBody, "description": "no authenticated actor"},
    403: {"model": ApiErrorBody, "description": "forbidden — not an approver"},
    404: {"model": ApiErrorBody, "description": "not_found"},
    409: {"model": ApiErrorBody, "description": "invalid_request — already decided"},
}


class ApprovalBody(BaseModel):
    decision: str
    rationale: str


class ClarificationBody(BaseModel):
    answer: str


# --- runs -------------------------------------------------------------------

@router.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    with _engine().begin() as conn:
        rows = conn.execute(
            text(
                "SELECT r.id, r.state, r.requirement_id, q.submitted_text, r.started_at"
                " FROM workflow_run r JOIN requirement q ON q.id = r.requirement_id"
                " ORDER BY r.started_at DESC"
            )
        ).all()
    return [
        {"id": r[0], "state": r[1], "requirement_id": r[2],
         "summary": r[3][:120], "started_at": str(r[4])}
        for r in rows
    ]


@router.get("/runs/{run_id}", responses=ERROR_RESPONSES)
def get_run(run_id: str) -> dict[str, Any]:
    engine = _engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT r.state, r.waiting_on, r.approved_scope, r.started_at, r.ended_at,"
                " q.id, q.submitted_text, q.resolution_state"
                " FROM workflow_run r JOIN requirement q ON q.id = r.requirement_id"
                " WHERE r.id = :id"
            ),
            {"id": run_id},
        ).one_or_none()
        if row is None:
            raise HTTPException(404, {"error": "not_found", "message": f"unknown run {run_id}"})

        node_states = dict(
            conn.execute(
                text("SELECT state, count(*) FROM task_node WHERE run_id = :r GROUP BY state"),
                {"r": run_id},
            ).all()
        )
        nodes_succeeded = node_states.get("SUCCEEDED", 0)
        nodes_terminal = sum(
            count for state, count in node_states.items()
            if state in ("SUCCEEDED", "FAILED", "ROLLED_BACK", "SKIPPED")
        )
        replans = conn.execute(
            text(
                "SELECT trigger, blast_radius, occurred_at FROM replan_event"
                " WHERE run_id = :r ORDER BY occurred_at"
            ),
            {"r": run_id},
        ).all()
    reliability = MetricsService(engine).for_run(run_id)
    return {
        "id": run_id,
        "state": row[0],
        "waiting_on": row[1],
        "approved_scope": list(row[2] or []),
        "started_at": str(row[3]),
        "ended_at": str(row[4]) if row[4] else None,
        "requirement": {
            "id": row[5], "summary": row[6], "resolution_state": row[7],
        },
        # FR-037 reliability metrics, computed from persisted audit and run rows
        # (research R11). `null` means "no denominator, unknown"; 0 means "measured
        # and zero" — the console must not render those the same way.
        "metrics": {
            "nodes_total": sum(node_states.values()),
            "nodes_by_state": node_states,
            "task_success_rate": (nodes_succeeded / nodes_terminal) if nodes_terminal else None,
            "retries": reliability.retries,
            "retry_rate": reliability.retry_frequency,
            "rollbacks": reliability.rollbacks,
            "rollback_rate": reliability.rollback_frequency,
            "mttr_seconds": reliability.mttr_seconds,
            "end_to_end_seconds": reliability.end_to_end_seconds,
            "human_wait_seconds": reliability.human_wait_seconds,
            "failures": reliability.failures,
            "unrecovered_failures": reliability.unrecovered_failures,
        },
        "replans": [
            {"trigger": r[0], "blast_radius": r[1], "occurred_at": str(r[2])} for r in replans
        ],
    }


@router.get("/runs/{run_id}/graph", responses=ERROR_RESPONSES)
def get_graph(run_id: str) -> dict[str, Any]:
    with _engine().begin() as conn:
        nodes = conn.execute(
            text(
                "SELECT id, description, requirement_ref, execution_mode, surface, is_sync,"
                " state, is_stale, attempt_count FROM task_node WHERE run_id = :r ORDER BY id"
            ),
            {"r": run_id},
        ).all()
        edges = conn.execute(
            text(
                "SELECT from_node, to_node FROM task_dependency WHERE run_id = :r"
                " ORDER BY from_node, to_node"
            ),
            {"r": run_id},
        ).all()

    incoming: dict[str, list[str]] = {}
    for frm, to in edges:
        incoming.setdefault(to, []).append(frm)

    return {
        "nodes": [
            {
                "id": n[0], "description": n[1], "requirement_ref": n[2],
                "execution_mode": n[3], "surface": n[4], "is_sync": n[5],
                "state": n[6], "is_stale": n[7], "attempt_count": n[8],
                "depends_on": sorted(incoming.get(n[0], [])),
            }
            for n in nodes
        ],
        "edges": [{"from": e[0], "to": e[1]} for e in edges],
    }


@router.get("/runs/{run_id}/gates", responses=ERROR_RESPONSES)
def get_gates(run_id: str) -> list[dict[str, Any]]:
    with _engine().begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, stage, kind, criteria, outcome, reason, evaluated_at FROM gate"
                " WHERE run_id = :r ORDER BY evaluated_at NULLS LAST, id"
            ),
            {"r": run_id},
        ).all()
    return [
        {"id": r[0], "stage": r[1], "kind": r[2], "criteria": r[3], "outcome": r[4],
         "reason": r[5], "evaluated_at": str(r[6]) if r[6] else None}
        for r in rows
    ]


@router.get("/runs/{run_id}/audit", responses=ERROR_RESPONSES)
def get_audit(run_id: str) -> list[dict[str, Any]]:
    return [
        {"event_type": e.event_type, "actor": e.actor, "trace_id": e.trace_id,
         "payload": e.payload, "occurred_at": e.occurred_at}
        for e in AuditRepository(_engine()).for_run(run_id)
    ]


@router.get("/runs/{run_id}/decisions", responses=ERROR_RESPONSES)
def get_decisions(run_id: str) -> list[dict[str, Any]]:
    engine = _engine()
    lineage = [
        {"kind": "decision", "selection": d.selection, "rationale": d.rationale,
         "alternatives": d.alternatives, "actor": d.actor, "serves_ref": d.serves_ref,
         "at": d.decided_at}
        for d in DecisionStore(engine).for_run(run_id)
    ]
    approvals = [
        {"kind": "approval", "selection": str(a.decision), "rationale": a.rationale,
         "alternatives": [], "actor": a.human_actor, "serves_ref": str(a.checkpoint),
         "at": a.decided_at}
        for a in ApprovalService(engine).decisions_for_run(run_id)
    ]
    return sorted(lineage + approvals, key=lambda item: item["at"])


@router.get("/trace", responses=ERROR_RESPONSES)
def get_trace(requirement: str | None = None, change: str | None = None,
              run: str | None = None) -> dict[str, Any]:
    """Both directions of the trace (FR-034), at the path the approved contract names."""
    store = TraceStore(_engine())
    if requirement:
        forward = store.for_requirement(requirement)
        return {"requirement_ref": forward.requirement_ref, "tasks": list(forward.tasks),
                "changes": list(forward.changes), "tests": list(forward.tests)}
    if change:
        return {"change_ref": change, "requirement_ref": store.requirement_for_change(change)}
    if run:
        return {"untraceable_changes": store.untraceable_changes(run)}
    raise HTTPException(400, {
        "error": "invalid_request",
        "message": "trace requires one of requirement, change, or run",
    })


# --- pending human work -----------------------------------------------------

@router.get("/runs/{run_id}/pending", responses=ERROR_RESPONSES)
def get_pending(run_id: str) -> dict[str, Any]:
    engine = _engine()
    return {
        "approvals": [
            {"id": r.id, "checkpoint": str(r.checkpoint), "action": r.detail.get("action"),
             "detail": r.detail, "requested_by": r.requested_by,
             "requested_at": r.requested_at, "fingerprint": r.action_fingerprint}
            for r in ApprovalService(engine).pending(run_id)
        ],
        "clarifications": [
            {"id": c.id, "question": c.question, "affects": c.affects,
             "requested_by": c.requested_by, "requested_at": c.requested_at}
            for c in ClarificationService(engine).pending(run_id)
        ],
    }


@router.post("/runs/{run_id}/approvals/{request_id}", responses=ERROR_RESPONSES)
def decide_approval(
    run_id: str, request_id: str, body: ApprovalBody,
    x_actor_id: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = _actor(x_actor_id)
    engine = _engine()
    try:
        decision = Decision(body.decision)
    except ValueError as exc:
        raise HTTPException(400, {"error": "invalid_request",
                                  "message": f"unknown decision {body.decision!r}"}) from exc

    service = ApprovalService(engine)
    try:
        record = service.decide(request_id, actor=actor, decision=decision,
                                rationale=body.rationale)
    except NotAnApprover as exc:
        raise HTTPException(403, {"error": "forbidden", "message": str(exc)}) from exc
    except AlreadyDecided as exc:
        raise HTTPException(409, {"error": "invalid_request", "message": str(exc)}) from exc
    except OrchestratorError as exc:
        status = 404 if exc.code is ErrorCode.NOT_FOUND else 400
        raise HTTPException(status, {"error": str(exc.code), "message": str(exc)}) from exc

    return {
        "id": record.id, "request_id": record.request_id, "checkpoint": str(record.checkpoint),
        "human_actor": record.human_actor, "approver_role_held": record.approver_role_held,
        "decision": str(record.decision), "rationale": record.rationale,
        "decided_at": record.decided_at,
    }


@router.post("/runs/{run_id}/clarifications/{request_id}", responses=ERROR_RESPONSES)
def answer_clarification(
    run_id: str, request_id: str, body: ClarificationBody,
    x_actor_id: str | None = Header(default=None),
) -> dict[str, Any]:
    actor = _actor(x_actor_id)
    engine = _engine()
    service = ClarificationService(engine)
    try:
        answered = service.answer(request_id, answer=body.answer, answered_by=actor.id)
    except (AnswerRequired, AlreadyAnswered) as exc:
        raise HTTPException(400, {"error": "invalid_request", "message": str(exc)}) from exc
    except OrchestratorError as exc:
        status = 404 if exc.code is ErrorCode.NOT_FOUND else 400
        raise HTTPException(status, {"error": str(exc.code), "message": str(exc)}) from exc

    # Persisted above; only now is the answer part of the run's lineage, and only
    # now may the run leave WAITING_FOR_HUMAN (FR-046, FR-049).
    DecisionStore(engine).record(
        run_id=run_id, alternatives=[], selection=answered.answer or "",
        rationale=f"clarification: {answered.question}", actor=actor.id,
        serves_ref=answered.affects,
    )
    store = StateStore(engine)
    if store.run_state(run_id) is RunState.WAITING_FOR_HUMAN:
        store.transition_run(run_id, RunState.PLANNING)

    return {
        "id": answered.id, "answer": answered.answer, "answered_by": answered.answered_by,
        "answered_at": answered.answered_at, "run_state": str(store.run_state(run_id)),
    }
