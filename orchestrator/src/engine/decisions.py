"""Decision lineage (T066, FR-027).

Records what was considered, what was chosen, why, by whom, and which
requirement or task it serves. This is the artifact that makes an agent-produced
run reviewable at speed: a reviewer checks the chain rather than re-deriving
intent from a diff.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text

from src.trace.correlation import now


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    id: str
    run_id: str
    alternatives: list[dict[str, Any]]
    selection: str
    rationale: str
    actor: str
    decided_at: str
    serves_ref: str


class DecisionStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(
        self, *, run_id: str, alternatives: list[dict[str, Any]], selection: str,
        rationale: str, actor: str, serves_ref: str,
    ) -> DecisionRecord:
        record = DecisionRecord(
            id=uuid.uuid4().hex, run_id=run_id, alternatives=alternatives,
            selection=selection, rationale=rationale, actor=actor,
            decided_at=now().isoformat(), serves_ref=serves_ref,
        )
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO decision_record (id, run_id, alternatives, selection,"
                    " rationale, actor, decided_at, serves_ref)"
                    " VALUES (:id,:run,CAST(:alt AS JSONB),:sel,:why,:actor,:at,:ref)"
                ),
                {"id": record.id, "run": run_id, "alt": json.dumps(alternatives),
                 "sel": selection, "why": rationale, "actor": actor,
                 "at": record.decided_at, "ref": serves_ref},
            )
        return record

    def for_run(self, run_id: str) -> list[DecisionRecord]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, run_id, alternatives, selection, rationale, actor,"
                    " decided_at, serves_ref FROM decision_record WHERE run_id = :r"
                    " ORDER BY decided_at"
                ),
                {"r": run_id},
            ).all()
        return [
            DecisionRecord(r[0], r[1], list(r[2]), r[3], r[4], r[5], str(r[6]), r[7])
            for r in rows
        ]
