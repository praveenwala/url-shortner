"""T035 — checkpoint 2b: interpretation is recorded before any task exists (FR-020)."""

import pytest

from src.api.errors import ErrorCode, OrchestratorError
from src.engine.decompose import TaskNode, decompose
from src.engine.intake import (
    Ambiguity,
    Interpretation,
    Requirement,
    ResolutionState,
    record_interpretation,
)
from src.models.states import ExecutionMode, Surface

pytestmark = pytest.mark.workflow


def _node(nid: str, **kw) -> TaskNode:
    return TaskNode(
        id=nid,
        description=f"task {nid}",
        requirement_ref=kw.pop("requirement_ref", "FR-001"),
        execution_mode=kw.pop("execution_mode", ExecutionMode.AGENT_AUTHORED),
        surface=kw.pop("surface", Surface.ORCHESTRATOR),
        declared_outputs=kw.pop("declared_outputs", (f"orchestrator/src/{nid}.py",)),
        **kw,
    )


def test_decomposition_refused_before_interpretation():
    req = Requirement(id="r1", submitted_text="provide short links", submitted_by="human:lead")
    assert req.resolution_state is ResolutionState.SUBMITTED
    with pytest.raises(OrchestratorError):
        decompose(req, [_node("a")])


def test_interpretation_records_scope_actors_constraints():
    req = Requirement(id="r1", submitted_text="provide short links", submitted_by="human:lead")
    record_interpretation(
        req,
        Interpretation(
            scope="create and resolve short links",
            actors=["link creator", "visitor"],
            constraints=["http/https only"],
        ),
    )
    assert req.is_interpreted
    assert req.resolution_state is ResolutionState.INTERPRETED
    assert req.interpretation.as_dict()["actors"] == ["link creator", "visitor"]
    assert decompose(req, [_node("a")])


def test_blocking_ambiguity_prevents_any_task(recwarn):
    """FR-028: an ambiguity that would change scope halts planning; zero tasks result."""
    req = Requirement(id="r2", submitted_text="make the links smarter", submitted_by="human:lead")
    record_interpretation(
        req,
        Interpretation(
            scope="undetermined",
            actors=["link creator"],
            constraints=[],
            ambiguities=[Ambiguity(question="What does 'smarter' mean for a link?", affects="scope")],
        ),
    )
    assert req.resolution_state is ResolutionState.AWAITING_CLARIFICATION
    with pytest.raises(OrchestratorError):
        decompose(req, [_node("a")])


def test_ambiguity_must_be_an_answerable_question():
    with pytest.raises(OrchestratorError):
        Ambiguity(question="the requirement is vague", affects="scope")


def test_task_without_requirement_reference_is_refused():
    """FR-035."""
    with pytest.raises(OrchestratorError) as exc:
        _node("a", requirement_ref="  ")
    assert exc.value.code is ErrorCode.MISSING_REQUIREMENT_REF
