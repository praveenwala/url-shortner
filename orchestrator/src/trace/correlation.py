"""Correlation fields for the orchestrator.

Implements `contracts/correlation.md` for this service only. The Java shortener
implements the same contract independently — there is deliberately no shared
runtime module across the language boundary (plan.md § Structure Decision).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import UTC, datetime

TRACE_ID = "trace_id"
SPAN_ID = "span_id"
RUN_ID = "run_id"
ACTOR = "actor"
OCCURRED_AT = "occurred_at"

FIELD_NAMES: frozenset[str] = frozenset({TRACE_ID, SPAN_ID, RUN_ID, ACTOR, OCCURRED_AT})


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Correlation:
    trace_id: str = field(default_factory=new_id)
    span_id: str = field(default_factory=new_id)
    run_id: str | None = None
    actor: str = "system"
    occurred_at: datetime = field(default_factory=now)

    def child(self, actor: str | None = None) -> "Correlation":
        return Correlation(
            trace_id=self.trace_id,
            span_id=new_id(),
            run_id=self.run_id,
            actor=actor or self.actor,
        )

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        d[OCCURRED_AT] = self.occurred_at.isoformat()
        return d
