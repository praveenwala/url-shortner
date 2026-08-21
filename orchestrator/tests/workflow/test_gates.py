"""T041 — checkpoint 2c: entry and exit gates block and record outcome and reason (FR-026)."""

import pytest

from src.api.errors import OrchestratorError
from src.engine.gates import Gate, GateLedger, StageBlocked, enter_stage, exit_stage
from src.models.states import GateKind, GateOutcome

pytestmark = pytest.mark.workflow


def _gate(kind, ok, reason="", stage="planning", criteria="criteria"):
    return Gate(stage=stage, kind=kind, criteria=criteria, predicate=lambda ctx: (ok, reason))


def test_entry_gate_blocks_stage_from_starting():
    ledger = GateLedger()
    with pytest.raises(StageBlocked):
        enter_stage(_gate(GateKind.ENTRY, False, "spec has unresolved ambiguity"), {}, ledger)
    assert len(ledger.evaluations) == 1
    assert ledger.evaluations[0].outcome is GateOutcome.FAIL
    assert "unresolved ambiguity" in ledger.evaluations[0].reason


def test_exit_gate_blocks_stage_from_completing():
    ledger = GateLedger()
    with pytest.raises(StageBlocked):
        exit_stage(_gate(GateKind.EXIT, False, "a previously passing test now fails"), {}, ledger)
    assert ledger.failures()[0].kind is GateKind.EXIT


def test_passing_evaluations_are_recorded_too():
    """Not only failures: the trail must show what was checked."""
    ledger = GateLedger()
    enter_stage(_gate(GateKind.ENTRY, True, "spec complete"), {}, ledger)
    exit_stage(_gate(GateKind.EXIT, True, "all tests pass"), {}, ledger)
    assert [e.outcome for e in ledger.evaluations] == [GateOutcome.PASS, GateOutcome.PASS]
    assert all(e.evaluated_at for e in ledger.evaluations)
    assert all(e.reason for e in ledger.evaluations)


def test_gate_kind_is_enforced():
    ledger = GateLedger()
    with pytest.raises(OrchestratorError):
        enter_stage(_gate(GateKind.EXIT, True), {}, ledger)
    with pytest.raises(OrchestratorError):
        exit_stage(_gate(GateKind.ENTRY, True), {}, ledger)


def test_gate_predicate_sees_context():
    ledger = GateLedger()
    gate = Gate(
        stage="implementation", kind=GateKind.EXIT, criteria="tests must pass",
        predicate=lambda ctx: (ctx["failing"] == 0, f"{ctx['failing']} failing"),
    )
    with pytest.raises(StageBlocked):
        exit_stage(gate, {"failing": 3}, ledger)
    exit_stage(gate, {"failing": 0}, ledger)
    assert [e.outcome for e in ledger.for_stage("implementation")] == [
        GateOutcome.FAIL, GateOutcome.PASS
    ]
