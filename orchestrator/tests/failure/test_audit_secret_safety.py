"""T099 — audit and error records carry correlation, never credentials (FR-038).

The existing control rejected a payload whose *key* looked like a secret
(`password`, `api_key`, ...). Audit details are free text: `dispatch._audit`
writes `{"task_id": ..., "detail": str(exc)}`, and an exception message is
exactly where a connection string ends up. A key-only check cannot see that, so
this file drives the control from the value side as well.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent import sandbox
from src.agent.dispatch import BoundedTask, Dispatcher
from src.api.errors import ErrorCode, OrchestratorError
from src.engine.decompose import TaskNode
from src.models.states import ExecutionMode, Surface
from src.store.repository import _reject_secrets
from src.trace.correlation import Correlation

pytestmark = pytest.mark.failure

REPO = Path(__file__).resolve().parents[3]
ALL_APPROVALS = frozenset(
    {"interface", "acceptance_criteria", "dependencies", "security_constraints"}
)

SENTINEL_PASSWORD = "AuditSafetyPassw0rd-not-real"
SENTINEL_API_KEY = "sk-ant-api03-AUDITSAFETY-NOT-A-REAL-KEY"


class RecordingAudit:
    """Stands in for AuditRepository, running the real secret check."""

    def __init__(self) -> None:
        self.records: list[tuple[Correlation, str, dict]] = []

    def append(self, correlation: Correlation, event_type: str, payload: dict) -> int:
        _reject_secrets(payload)
        self.records.append((correlation, event_type, payload))
        return len(self.records)


def _node() -> TaskNode:
    return TaskNode(
        id="t-audit", description="d", requirement_ref="FR-038",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=Surface.ORCHESTRATOR,
        declared_outputs=("orchestrator/src/agent/probe.py",),
    )


# --- value-side detection ---------------------------------------------------

def test_a_database_password_embedded_in_a_value_is_refused():
    dsn = f"postgresql+psycopg://postgres:{SENTINEL_PASSWORD}@agent-pg-1:5432/agent_test"
    with pytest.raises(OrchestratorError) as exc:
        _reject_secrets({"task_id": "t1", "detail": f"could not start postgres: {dsn}"})
    assert exc.value.code is ErrorCode.FORBIDDEN
    assert SENTINEL_PASSWORD not in str(exc.value), "the check must not echo what it caught"


def test_an_api_key_embedded_in_a_value_is_refused():
    with pytest.raises(OrchestratorError):
        _reject_secrets({"detail": f"Authorization: Bearer {SENTINEL_API_KEY}"})


def test_a_key_named_like_a_secret_is_still_refused():
    """Positive control: the original key-side check is not weakened."""
    with pytest.raises(OrchestratorError):
        _reject_secrets({"db_password": "anything"})


def test_ordinary_details_are_not_false_positives():
    """A boundary that refuses normal audit text would be quietly disabled."""
    for detail in (
        "sandbox unavailable: the Docker daemon is unavailable",
        "egress to 'example.com' is not permitted",
        "path 'ops/db/provision.sh' is in a denied tree",
        "postgresql+psycopg://orchestrator_app@db.internal:5432/orchestrator_db",
    ):
        _reject_secrets({"task_id": "t1", "detail": detail})


# --- records emitted by the boundary itself ---------------------------------

def test_safe_stop_record_carries_correlation_and_no_credentials(monkeypatch):
    monkeypatch.setattr(sandbox, "docker_available", lambda: False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SENTINEL_API_KEY)
    audit = RecordingAudit()

    dispatcher = Dispatcher(
        repo_root=REPO, task=BoundedTask(_node(), ALL_APPROVALS),
        audit=audit, run_id="run-audit-1",
    )
    turns = iter([[("run_tests", {"layer": "unit"})], []])
    outcome = dispatcher.run(lambda feedback: next(turns))

    assert outcome.safe_stopped is True
    assert audit.records, "the safe-stop was not audited"
    for correlation, event_type, payload in audit.records:
        assert correlation.run_id == "run-audit-1"
        assert correlation.trace_id, "no trace id on an audited boundary event"
        assert event_type == "SAFE_STOP_SANDBOX_UNAVAILABLE"
        blob = repr(payload)
        assert SENTINEL_API_KEY not in blob
        assert SENTINEL_PASSWORD not in blob
        assert "reason" in blob or "detail" in blob, "the reason must be recorded"
