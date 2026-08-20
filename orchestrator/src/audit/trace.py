"""Bidirectional traceability (T067, FR-034, FR-035).

Requirement → task → change → test, and change → requirement. A change with no
requirement is reported rather than tolerated: `untraceable_changes` is what a
Principle III audit consumes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, text


@dataclass(frozen=True, slots=True)
class ForwardTrace:
    requirement_ref: str
    tasks: tuple[str, ...]
    changes: tuple[str, ...]
    tests: tuple[str, ...]


class TraceStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def link(
        self, *, requirement_ref: str, task_ref: str | None = None,
        change_ref: str | None = None, test_ref: str | None = None,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO trace_link (requirement_ref, task_ref, change_ref, test_ref)"
                    " VALUES (:req,:task,:change,:test)"
                ),
                {"req": requirement_ref, "task": task_ref, "change": change_ref,
                 "test": test_ref},
            )

    def for_requirement(self, requirement_ref: str) -> ForwardTrace:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT task_ref, change_ref, test_ref FROM trace_link"
                    " WHERE requirement_ref = :r ORDER BY id"
                ),
                {"r": requirement_ref},
            ).all()
        def column(index: int) -> tuple[str, ...]:
            return tuple(dict.fromkeys(r[index] for r in rows if r[index]))
        return ForwardTrace(requirement_ref, column(0), column(1), column(2))

    def requirement_for_change(self, change_ref: str) -> str | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "SELECT requirement_ref FROM trace_link WHERE change_ref = :c LIMIT 1"
                ),
                {"c": change_ref},
            ).one_or_none()
        return row[0] if row else None

    def untraceable_changes(self, run_id: str) -> list[str]:
        """FR-035: a change with no originating requirement is a finding."""
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT c.id FROM change_record c"
                    " LEFT JOIN trace_link t ON t.change_ref = c.id"
                    " WHERE c.run_id = :r AND t.change_ref IS NULL"
                ),
                {"r": run_id},
            ).all()
        return [r[0] for r in rows]
