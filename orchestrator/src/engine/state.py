"""State persistence and resume (T045, FR-025, NFR-003, SC-012).

State is written at *every* transition, so an interrupted run is inspectable
while stopped and resumable without repeating completed work.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

# Aliased so `text` remains usable as a domain word in signatures below.
from sqlalchemy import Engine
from sqlalchemy import text as sql_text

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.decompose import TaskNode
from src.graph.builder import TaskGraph, build_graph
from src.models.states import (
    TERMINAL_NODE_STATES,
    ExecutionMode,
    NodeState,
    RunState,
    Surface,
    check_run_transition,
)
from src.obs import logging as olog
from src.trace.correlation import now


@dataclass(slots=True)
class RunRecord:
    id: str
    requirement_id: str
    state: RunState
    wall_clock_ceiling: int
    retry_ceiling: int


class StateStore:
    """Every write here is a persisted transition. There is no in-memory-only path."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- requirement / run ---------------------------------------------------
    def create_requirement(self, req_id: str, text: str, submitted_by: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                sql_text(
                    "INSERT INTO requirement (id, submitted_text, resolution_state,"
                    " submitted_by, submitted_at) VALUES (:id,:t,'SUBMITTED',:by,:at)"
                ),
                {"id": req_id, "t": text, "by": submitted_by, "at": now()},
            )

    def create_run(
        self, run_id: str, requirement_id: str, wall_clock_ceiling: int, retry_ceiling: int
    ) -> RunRecord:
        with self._engine.begin() as conn:
            conn.execute(
                sql_text(
                    "INSERT INTO workflow_run (id, requirement_id, state, wall_clock_ceiling,"
                    " retry_ceiling, started_at) VALUES (:id,:r,'PLANNING',:w,:rc,:at)"
                ),
                {"id": run_id, "r": requirement_id, "w": wall_clock_ceiling,
                 "rc": retry_ceiling, "at": now()},
            )
        return RunRecord(run_id, requirement_id, RunState.PLANNING, wall_clock_ceiling,
                         retry_ceiling)

    def set_approved_scope(self, run_id: str, requirement_refs: list[str]) -> None:
        """The scope a run is authorised to work within (FR-039)."""
        with self._engine.begin() as conn:
            conn.execute(
                sql_text("UPDATE workflow_run SET approved_scope = CAST(:s AS JSONB) WHERE id = :id"),
                {"s": json.dumps(requirement_refs), "id": run_id},
            )

    def run_state(self, run_id: str) -> RunState:
        with self._engine.begin() as conn:
            row = conn.execute(
                sql_text("SELECT state FROM workflow_run WHERE id = :id"), {"id": run_id}
            ).one_or_none()
        if row is None:
            raise OrchestratorError(f"unknown run {run_id!r}", ErrorCode.NOT_FOUND)
        return RunState(row[0])

    #: Run states that warrant an operational log line, and the event name each maps to.
    #: Immutable so no caller can reshape the logging vocabulary at runtime.
    _RUN_EVENT: ClassVar[Mapping[RunState, str]] = MappingProxyType({
        RunState.EXECUTING: "run_started",
        RunState.COMPLETED: "run_completed",
        RunState.FAILED: "run_failed",
        RunState.SAFE_STOPPED: "safe_stop",
        RunState.WAITING_FOR_HUMAN: "waiting_for_human",
    })

    def transition_run(self, run_id: str, target: RunState, waiting_on: str | None = None) -> None:
        current = self.run_state(run_id)
        check_run_transition(current, target)
        with self._engine.begin() as conn:
            conn.execute(
                sql_text(
                    "UPDATE workflow_run SET state = :s, waiting_on = :w,"
                    " ended_at = CASE WHEN :s IN ('COMPLETED','FAILED','SAFE_STOPPED','ABANDONED')"
                    " THEN :at ELSE ended_at END WHERE id = :id"
                ),
                {"s": str(target), "w": waiting_on, "at": now(), "id": run_id},
            )

        # Emitted only after the transition is persisted, so an operational log line can never
        # claim a state the store rejected. This is a diagnostic record; the audit trail is
        # written separately and is unaffected.
        event = self._RUN_EVENT.get(target)
        if event:
            olog.log(event, run_id=run_id, outcome=str(target),
                     **({"waiting_on": waiting_on} if waiting_on else {}))

    # -- nodes ---------------------------------------------------------------

    def persist_nodes(self, run_id: str, nodes: list[TaskNode]) -> None:
        with self._engine.begin() as conn:
            for node in nodes:
                conn.execute(
                    sql_text(
                        "INSERT INTO task_node (id, run_id, description, requirement_ref,"
                        " execution_mode, surface, is_sync, state, timeout_seconds,"
                        " max_attempts, backoff_seconds, declared_inputs, declared_outputs,"
                        " supersedes)"
                        " VALUES (:id,:run,:d,:ref,:mode,:surface,:sync,:state,:t,:ma,:b,"
                        " CAST(:din AS JSONB), CAST(:dout AS JSONB), :sup)"
                    ),
                    {
                        "id": node.id, "run": run_id, "d": node.description,
                        "ref": node.requirement_ref, "mode": str(node.execution_mode),
                        "surface": str(node.surface), "sync": node.is_sync,
                        "state": str(node.state), "t": node.timeout_seconds,
                        "ma": node.max_attempts, "b": node.backoff_seconds,
                        "din": json.dumps(list(node.declared_inputs)),
                        "dout": json.dumps(list(node.declared_outputs)),
                        "sup": node.supersedes,
                    },
                )
            for node in nodes:
                for dep in node.depends_on:
                    conn.execute(
                        sql_text(
                            "INSERT INTO task_dependency (run_id, from_node, to_node)"
                            " VALUES (:run,:f,:t) ON CONFLICT DO NOTHING"
                        ),
                        {"run": run_id, "f": dep, "t": node.id},
                    )

    def record_attempt(self, node_id: str) -> int:
        """Atomically spend one attempt and return the new count.

        Persisted per attempt rather than at the end, so a process that dies mid-retry
        resumes with the budget it had actually spent — not the budget it started with.
        """
        with self._engine.begin() as conn:
            row = conn.execute(
                sql_text(
                    "UPDATE task_node SET attempt_count = attempt_count + 1"
                    " WHERE id = :id RETURNING attempt_count"
                ),
                {"id": node_id},
            ).one_or_none()
        if row is None:
            raise OrchestratorError(f"unknown operation {node_id!r}", ErrorCode.NOT_FOUND)
        return int(row[0])

    def attempts_spent(self, node_id: str) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(
                sql_text("SELECT attempt_count FROM task_node WHERE id = :id"),
                {"id": node_id},
            ).one_or_none()
        if row is None:
            raise OrchestratorError(f"unknown operation {node_id!r}", ErrorCode.NOT_FOUND)
        return int(row[0])

    def mark_stale(self, node_ids: list[str], stale: bool = True) -> None:
        """Staleness is a flag, never a state change: the prior result survives."""
        if not node_ids:
            return
        with self._engine.begin() as conn:
            conn.execute(
                sql_text("UPDATE task_node SET is_stale = :s WHERE id = ANY(:ids)"),
                {"s": stale, "ids": node_ids},
            )

    def record_node_transition(self, node: TaskNode) -> None:
        """Called on every node transition — this is what makes resume possible."""
        with self._engine.begin() as conn:
            conn.execute(
                sql_text(
                    "UPDATE task_node SET state = :s, attempt_count = :a, is_stale = :stale"
                    " WHERE id = :id"
                ),
                {"s": str(node.state), "a": node.attempt_count, "stale": node.is_stale,
                 "id": node.id},
            )

    def load_graph(self, run_id: str) -> TaskGraph:
        with self._engine.begin() as conn:
            rows = conn.execute(
                sql_text(
                    "SELECT id, description, requirement_ref, execution_mode, surface,"
                    " is_sync, state, is_stale, attempt_count, timeout_seconds, max_attempts,"
                    " backoff_seconds, declared_inputs, declared_outputs, supersedes"
                    " FROM task_node WHERE run_id = :r ORDER BY id"
                ),
                {"r": run_id},
            ).all()
            deps = conn.execute(
                sql_text("SELECT from_node, to_node FROM task_dependency WHERE run_id = :r"),
                {"r": run_id},
            ).all()
        incoming: dict[str, list[str]] = {}
        for frm, to in deps:
            incoming.setdefault(to, []).append(frm)

        nodes = [
            TaskNode(
                id=r[0], description=r[1], requirement_ref=r[2],
                execution_mode=ExecutionMode(r[3]), surface=Surface(r[4]),
                depends_on=sorted(incoming.get(r[0], [])), is_sync=r[5],
                state=NodeState(r[6]), is_stale=r[7], attempt_count=r[8],
                timeout_seconds=r[9], max_attempts=r[10], backoff_seconds=r[11],
                declared_inputs=tuple(r[12] or ()), declared_outputs=tuple(r[13] or ()),
                supersedes=r[14],
            )
            for r in rows
        ]
        return build_graph(nodes)

    def completed_node_ids(self, run_id: str) -> set[str]:
        graph = self.load_graph(run_id)
        return {n.id for n in graph.nodes.values() if n.state in TERMINAL_NODE_STATES}
