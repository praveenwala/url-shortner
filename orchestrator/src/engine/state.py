"""State persistence and resume (T045, FR-025, NFR-003, SC-012).

State is written at *every* transition, so an interrupted run is inspectable
while stopped and resumable without repeating completed work.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, text

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
    def create_requirement(self, req_id: str, text_: str, submitted_by: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO requirement (id, submitted_text, resolution_state,"
                    " submitted_by, submitted_at) VALUES (:id,:t,'SUBMITTED',:by,:at)"
                ),
                {"id": req_id, "t": text_, "by": submitted_by, "at": now()},
            )

    def create_run(
        self, run_id: str, requirement_id: str, wall_clock_ceiling: int, retry_ceiling: int
    ) -> RunRecord:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO workflow_run (id, requirement_id, state, wall_clock_ceiling,"
                    " retry_ceiling, started_at) VALUES (:id,:r,'PLANNING',:w,:rc,:at)"
                ),
                {"id": run_id, "r": requirement_id, "w": wall_clock_ceiling,
                 "rc": retry_ceiling, "at": now()},
            )
        return RunRecord(run_id, requirement_id, RunState.PLANNING, wall_clock_ceiling,
                         retry_ceiling)

    def run_state(self, run_id: str) -> RunState:
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT state FROM workflow_run WHERE id = :id"), {"id": run_id}
            ).one_or_none()
        if row is None:
            raise OrchestratorError(f"unknown run {run_id!r}", ErrorCode.NOT_FOUND)
        return RunState(row[0])

    def transition_run(self, run_id: str, target: RunState, waiting_on: str | None = None) -> None:
        current = self.run_state(run_id)
        check_run_transition(current, target)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE workflow_run SET state = :s, waiting_on = :w,"
                    " ended_at = CASE WHEN :s IN ('COMPLETED','FAILED','SAFE_STOPPED','ABANDONED')"
                    " THEN :at ELSE ended_at END WHERE id = :id"
                ),
                {"s": str(target), "w": waiting_on, "at": now(), "id": run_id},
            )

    # -- nodes ---------------------------------------------------------------
    def persist_nodes(self, run_id: str, nodes: list[TaskNode]) -> None:
        with self._engine.begin() as conn:
            for node in nodes:
                conn.execute(
                    text(
                        "INSERT INTO task_node (id, run_id, description, requirement_ref,"
                        " execution_mode, surface, is_sync, state, timeout_seconds,"
                        " max_attempts, backoff_seconds) VALUES (:id,:run,:d,:ref,:mode,"
                        ":surface,:sync,:state,:t,:ma,:b)"
                    ),
                    {
                        "id": node.id, "run": run_id, "d": node.description,
                        "ref": node.requirement_ref, "mode": str(node.execution_mode),
                        "surface": str(node.surface), "sync": node.is_sync,
                        "state": str(node.state), "t": node.timeout_seconds,
                        "ma": node.max_attempts, "b": node.backoff_seconds,
                    },
                )
            for node in nodes:
                for dep in node.depends_on:
                    conn.execute(
                        text(
                            "INSERT INTO task_dependency (run_id, from_node, to_node)"
                            " VALUES (:run,:f,:t) ON CONFLICT DO NOTHING"
                        ),
                        {"run": run_id, "f": dep, "t": node.id},
                    )

    def record_node_transition(self, node: TaskNode) -> None:
        """Called on every node transition — this is what makes resume possible."""
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE task_node SET state = :s, attempt_count = :a, is_stale = :stale"
                    " WHERE id = :id"
                ),
                {"s": str(node.state), "a": node.attempt_count, "stale": node.is_stale,
                 "id": node.id},
            )

    def load_graph(self, run_id: str) -> TaskGraph:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, description, requirement_ref, execution_mode, surface,"
                    " is_sync, state, is_stale, attempt_count, timeout_seconds, max_attempts,"
                    " backoff_seconds FROM task_node WHERE run_id = :r ORDER BY id"
                ),
                {"r": run_id},
            ).all()
            deps = conn.execute(
                text("SELECT from_node, to_node FROM task_dependency WHERE run_id = :r"),
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
            )
            for r in rows
        ]
        return build_graph(nodes)

    def completed_node_ids(self, run_id: str) -> set[str]:
        graph = self.load_graph(run_id)
        return {n.id for n in graph.nodes.values() if n.state in TERMINAL_NODE_STATES}
