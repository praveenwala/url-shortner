"""Entry and exit gates (T044, FR-026).

Every stage declares both. A stage MUST NOT start until its entry gate passes
and MUST NOT be reported complete until its exit gate passes. Every evaluation
is recorded with outcome and reason — including passes, so the audit trail shows
what was checked, not only what failed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.api.errors import ErrorCode, OrchestratorError
from src.models.states import GateKind, GateOutcome
from src.trace.correlation import now


@dataclass(frozen=True, slots=True)
class GateEvaluation:
    stage: str
    kind: GateKind
    criteria: str
    outcome: GateOutcome
    reason: str
    evaluated_at: str

    @property
    def passed(self) -> bool:
        return self.outcome is GateOutcome.PASS


@dataclass(slots=True)
class Gate:
    stage: str
    kind: GateKind
    criteria: str
    predicate: Callable[[dict], tuple[bool, str]]

    def evaluate(self, context: dict) -> GateEvaluation:
        ok, reason = self.predicate(context)
        return GateEvaluation(
            stage=self.stage,
            kind=self.kind,
            criteria=self.criteria,
            outcome=GateOutcome.PASS if ok else GateOutcome.FAIL,
            reason=reason,
            evaluated_at=now().isoformat(),
        )


@dataclass(slots=True)
class GateLedger:
    """Records every evaluation. Append-only, like the audit trail it feeds."""

    evaluations: list[GateEvaluation] = field(default_factory=list)

    def record(self, evaluation: GateEvaluation) -> GateEvaluation:
        self.evaluations.append(evaluation)
        return evaluation

    def for_stage(self, stage: str) -> list[GateEvaluation]:
        return [e for e in self.evaluations if e.stage == stage]

    def failures(self) -> list[GateEvaluation]:
        return [e for e in self.evaluations if not e.passed]


class StageBlocked(OrchestratorError):
    code = ErrorCode.GATE_FAILED


def enter_stage(gate: Gate, context: dict, ledger: GateLedger) -> GateEvaluation:
    if gate.kind is not GateKind.ENTRY:
        raise OrchestratorError("enter_stage requires an entry gate", ErrorCode.INVALID_REQUEST)
    evaluation = ledger.record(gate.evaluate(context))
    if not evaluation.passed:
        raise StageBlocked(f"entry gate for {gate.stage!r} failed: {evaluation.reason}")
    return evaluation


def exit_stage(gate: Gate, context: dict, ledger: GateLedger) -> GateEvaluation:
    if gate.kind is not GateKind.EXIT:
        raise OrchestratorError("exit_stage requires an exit gate", ErrorCode.INVALID_REQUEST)
    evaluation = ledger.record(gate.evaluate(context))
    if not evaluation.passed:
        raise StageBlocked(f"exit gate for {gate.stage!r} failed: {evaluation.reason}")
    return evaluation
