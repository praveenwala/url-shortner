"""Reliability metrics (T097, FR-037, research R11).

Every metric is computed from the audit trail and the run table — nothing is counted in
memory, so a restart changes no number and a reviewer can recompute any figure by hand from
the same rows.

**The definition that matters most**: time in `WAITING_FOR_HUMAN` is excluded from MTTR and
from end-to-end latency, and reported separately as `human_wait_seconds`. Folding it in would
turn both into a measure of how quickly a person answered their messages rather than how the
system performed — and since FR-049 makes waiting a zero-compute persisted state, excluding it
is also the honest description of what the system was doing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text

from src.models.states import RunState

#: Audit event types the metrics read. Kept explicit so a renamed event is a
#: visible break rather than a metric that silently drifts to zero.
OPERATION_EVENTS = ("OPERATION_EXECUTED", "TASK_EXECUTED")
RETRY_EVENTS = ("RETRY", "RETRY_ATTEMPTED")
CHANGE_EVENTS = ("CHANGE_APPLIED",)
ROLLBACK_EVENTS = ("ROLLBACK_SUCCEEDED", "ROLLBACK_FAILED")
#: A safe-stop is a failure to recover from, not a quiet ending — MTTR must
#: measure it (FR-031, FR-037).
FAILURE_EVENTS = (
    "NODE_FAILED", "OPERATION_FAILED",
    "SAFE_STOP_SANDBOX_UNAVAILABLE", "SAFE_STOP_VIOLATION_BUDGET",
    "SAFE_STOP_WALL_CLOCK", "SAFE_STOP_ROLLBACK_FAILED",
    "SAFE_STOP_CLARIFICATION_EXHAUSTED",
)
RECOVERY_EVENTS = ("NODE_RECOVERED", "OPERATION_RECOVERED", "ROLLBACK_SUCCEEDED",
                   "RUN_RESUMED")
STATE_CHANGE_EVENT = "RUN_STATE_CHANGED"

TERMINAL_STATES = {RunState.COMPLETED, RunState.FAILED, RunState.SAFE_STOPPED,
                   RunState.ABANDONED}


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


@dataclass(frozen=True, slots=True)
class RunMetrics:
    run_id: str
    state: str
    operations: int
    retries: int
    changes_applied: int
    rollbacks: int
    failures: int
    recoveries: int
    unrecovered_failures: int
    retry_frequency: float | None
    rollback_frequency: float | None
    mttr_seconds: float | None
    human_wait_seconds: float
    wall_clock_seconds: float | None
    end_to_end_seconds: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AggregateMetrics:
    runs_total: int
    runs_terminal: int
    runs_completed: int
    success_rate: float | None
    operations: int
    retries: int
    retry_frequency: float | None
    changes_applied: int
    rollbacks: int
    rollback_frequency: float | None
    mttr_seconds: float | None
    end_to_end_seconds: float | None
    human_wait_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetricsService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- per run --------------------------------------------------------------
    def for_run(self, run_id: str) -> RunMetrics:
        events = self._events(run_id)
        state, started_at, ended_at = self._run_row(run_id)

        operations = sum(1 for e in events if e[0] in OPERATION_EVENTS)
        retries = sum(1 for e in events if e[0] in RETRY_EVENTS)
        changes = sum(1 for e in events if e[0] in CHANGE_EVENTS)
        rollbacks = sum(1 for e in events if e[0] in ROLLBACK_EVENTS)

        human_wait = self._human_wait_seconds(events)
        mttr, failures, recoveries = self._mttr(events, human_wait_windows=self._wait_windows(events))
        wall_clock = (ended_at - started_at).total_seconds() if ended_at else None
        end_to_end = max(0.0, wall_clock - human_wait) if wall_clock is not None else None

        return RunMetrics(
            run_id=run_id, state=str(state), operations=operations, retries=retries,
            changes_applied=changes, rollbacks=rollbacks, failures=failures,
            recoveries=recoveries, unrecovered_failures=failures - recoveries,
            retry_frequency=_ratio(retries, operations),
            rollback_frequency=_ratio(rollbacks, changes),
            mttr_seconds=mttr, human_wait_seconds=human_wait,
            wall_clock_seconds=wall_clock, end_to_end_seconds=end_to_end,
        )

    # -- across runs ----------------------------------------------------------
    def across_runs(self) -> AggregateMetrics:
        with self._engine.begin() as conn:
            rows = conn.execute(text("SELECT id, state FROM workflow_run")).all()

        per_run = [self.for_run(row[0]) for row in rows]
        terminal = [m for m in per_run if RunState(m.state) in TERMINAL_STATES]
        completed = [m for m in terminal if RunState(m.state) is RunState.COMPLETED]

        operations = sum(m.operations for m in per_run)
        retries = sum(m.retries for m in per_run)
        changes = sum(m.changes_applied for m in per_run)
        rollbacks = sum(m.rollbacks for m in per_run)
        mttrs = [m.mttr_seconds for m in per_run if m.mttr_seconds is not None]
        latencies = [m.end_to_end_seconds for m in per_run if m.end_to_end_seconds is not None]

        return AggregateMetrics(
            runs_total=len(per_run), runs_terminal=len(terminal),
            runs_completed=len(completed),
            success_rate=_ratio(len(completed), len(terminal)),
            operations=operations, retries=retries,
            retry_frequency=_ratio(retries, operations),
            changes_applied=changes, rollbacks=rollbacks,
            rollback_frequency=_ratio(rollbacks, changes),
            mttr_seconds=sum(mttrs) / len(mttrs) if mttrs else None,
            end_to_end_seconds=sum(latencies) / len(latencies) if latencies else None,
            human_wait_seconds=sum(m.human_wait_seconds for m in per_run),
        )

    # -- internals ------------------------------------------------------------
    def _events(self, run_id: str) -> list[tuple[str, datetime, dict[str, Any]]]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT event_type, occurred_at, payload FROM audit_event"
                    " WHERE run_id = :r ORDER BY occurred_at, id"
                ),
                {"r": run_id},
            ).all()
        return [(r[0], r[1], r[2] or {}) for r in rows]

    def _run_row(self, run_id: str) -> tuple[RunState, datetime, datetime | None]:
        with self._engine.begin() as conn:
            row = conn.execute(
                text("SELECT state, started_at, ended_at FROM workflow_run WHERE id = :r"),
                {"r": run_id},
            ).one()
        return RunState(row[0]), row[1], row[2]

    def _wait_windows(self, events) -> list[tuple[datetime, datetime]]:
        """Closed [enter, leave) windows in WAITING_FOR_HUMAN."""
        windows: list[tuple[datetime, datetime]] = []
        entered: datetime | None = None
        for event_type, at, payload in events:
            if event_type != STATE_CHANGE_EVENT:
                continue
            if payload.get("to") == str(RunState.WAITING_FOR_HUMAN):
                entered = at
            elif payload.get("from") == str(RunState.WAITING_FOR_HUMAN) and entered is not None:
                windows.append((entered, at))
                entered = None
        return windows

    def _human_wait_seconds(self, events) -> float:
        return sum((leave - enter).total_seconds()
                   for enter, leave in self._wait_windows(events))

    def _overlap(self, start: datetime, end: datetime,
                 windows: list[tuple[datetime, datetime]]) -> float:
        total = 0.0
        for enter, leave in windows:
            latest_start = max(start, enter)
            earliest_end = min(end, leave)
            if earliest_end > latest_start:
                total += (earliest_end - latest_start).total_seconds()
        return total

    def _mttr(self, events, human_wait_windows) -> tuple[float | None, int, int]:
        """Mean wall-clock from a failure to the run leaving it, minus any human wait
        inside that window. Failures never recovered are counted but contribute no time."""
        durations: list[float] = []
        failures = 0
        recoveries = 0
        open_failure: datetime | None = None

        for event_type, at, _payload in events:
            if event_type in FAILURE_EVENTS:
                failures += 1
                if open_failure is None:
                    open_failure = at
            elif event_type in RECOVERY_EVENTS and open_failure is not None:
                recoveries += 1
                elapsed = (at - open_failure).total_seconds()
                durations.append(max(0.0, elapsed - self._overlap(open_failure, at,
                                                                  human_wait_windows)))
                open_failure = None

        mttr = sum(durations) / len(durations) if durations else None
        return mttr, failures, recoveries
