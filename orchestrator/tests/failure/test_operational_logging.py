"""Operational logging contract (production-hardening).

Three properties, each of which would be worth nothing if merely documented:

1. The record carries the fields an operator needs, at stable top-level keys.
2. A credential never reaches a log line, whatever a call site passes.
3. A logging fault cannot break orchestration — the diagnostic tool must not become the outage.

Audit behaviour is asserted unchanged: nothing here writes to or reads from `audit_event`.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

from src.obs import logging as olog

pytestmark = pytest.mark.failure

SECRET_DSN = "postgresql+psycopg://app:hunter2-not-real@db.internal:5432/orchestrator_db"
SECRET_KEY = "sk-ant-api03-LOGTEST-NOT-A-REAL-KEY"


def emit(*calls) -> list[dict]:
    buf = io.StringIO()
    olog.configure(level="DEBUG", stream=buf)
    for fn, args, kwargs in calls:
        fn(*args, **kwargs)
    return [json.loads(line) for line in buf.getvalue().strip().splitlines() if line]


# --- shape --------------------------------------------------------------------

def test_record_is_json_with_the_standard_envelope():
    [rec] = emit((olog.log, ("run_started",), {"run_id": "r1"}))
    for key in ("timestamp", "level", "service", "event"):
        assert key in rec, f"missing envelope field {key}"
    assert rec["service"] == "orchestrator"
    assert rec["event"] == "run_started"


def test_context_fields_are_promoted_to_top_level():
    [rec] = emit((olog.log, ("node_completed",), {
        "correlation_id": "c1", "run_id": "r1", "node_id": "n1",
        "actor_id": "human:lead", "attempt": 2, "duration_ms": 12.5, "outcome": "succeeded",
    }))
    assert rec["correlation_id"] == "c1" and rec["run_id"] == "r1" and rec["node_id"] == "n1"
    assert rec["actor_id"] == "human:lead" and rec["attempt"] == 2
    assert rec["duration_ms"] == 12.5 and rec["outcome"] == "succeeded"


def test_unpromoted_fields_go_under_detail_so_the_top_level_shape_is_stable():
    [rec] = emit((olog.log, ("node_failed",), {"run_id": "r1", "image": "agent-sandbox/x"}))
    assert rec["detail"] == {"image": "agent-sandbox/x"}
    assert "image" not in rec


def test_levels_are_distinguishable():
    recs = emit((olog.log, ("run_started",), {}),
                (olog.warn, ("retry_scheduled",), {}),
                (olog.error, ("safe_stop",), {}))
    assert [r["level"] for r in recs] == ["INFO", "WARNING", "ERROR"]


def test_the_lifecycle_vocabulary_covers_every_required_event():
    required = {
        "orchestrator_started", "orchestrator_stopping",
        "run_started", "run_completed", "run_failed",
        "node_started", "node_completed", "node_failed",
        "retry_scheduled", "fallback_selected", "safe_stop", "waiting_for_human",
        "approval_decision", "replan_started", "replan_completed",
        "sandbox_unavailable", "postgres_readiness_failed",
    }
    assert required <= olog.EVENTS


def test_an_off_vocabulary_event_is_emitted_but_marked():
    """Losing a log line because its name was wrong is worse than an odd name."""
    [rec] = emit((olog.log, ("not_a_real_event",), {"run_id": "r1"}))
    assert rec["event"] == "not_a_real_event"
    assert rec["detail"]["unknown_event"] is True


# --- secrets ------------------------------------------------------------------

def test_a_dsn_with_a_password_is_redacted():
    [rec] = emit((olog.log, ("postgres_readiness_failed",), {"dsn": SECRET_DSN}))
    blob = json.dumps(rec)
    assert "hunter2-not-real" not in blob
    assert rec["detail"]["dsn"] == "[redacted]"


def test_an_api_key_is_redacted_from_a_message():
    [rec] = emit((olog.error, ("sandbox_unavailable", f"auth failed with {SECRET_KEY}"), {}))
    assert SECRET_KEY not in json.dumps(rec)


def test_a_credential_in_a_promoted_field_is_also_redacted():
    [rec] = emit((olog.log, ("approval_decision",), {"actor_id": SECRET_DSN}))
    assert "hunter2-not-real" not in json.dumps(rec)


def test_ordinary_values_are_not_false_positives():
    """A redactor that eats normal text would be switched off."""
    [rec] = emit((olog.log, ("node_failed",), {
        "run_id": "run-1", "node_id": "node-7", "outcome": "failed",
        "reason": "sandbox unavailable: the Docker daemon is unavailable",
    }))
    assert rec["detail"]["reason"].startswith("sandbox unavailable")
    assert rec["run_id"] == "run-1"


# --- logging must never break orchestration -----------------------------------

def test_a_broken_handler_does_not_raise():
    class Exploding(logging.Handler):
        def emit(self, record):
            raise RuntimeError("sink is down")

    olog.configure(level="DEBUG", stream=io.StringIO())
    logger = logging.getLogger(olog.SERVICE)
    logger.addHandler(Exploding())
    try:
        olog.log("run_started", run_id="r1")   # must not raise
    finally:
        logger.handlers.pop()


def test_an_unserialisable_field_does_not_raise():
    class Awkward:
        def __repr__(self):
            raise RuntimeError("cannot repr")

    olog.configure(level="DEBUG", stream=io.StringIO())
    olog.log("node_failed", run_id="r1", thing=Awkward())   # must not raise


def test_timed_context_records_duration_and_reraises():
    buf = io.StringIO()
    olog.configure(level="DEBUG", stream=buf)
    with pytest.raises(ValueError), olog.timed(
        "replan_started", "replan_completed", "run_failed", run_id="r1"
    ):
        raise ValueError("boom")
    recs = [json.loads(x) for x in buf.getvalue().strip().splitlines()]
    assert recs[0]["event"] == "replan_started"
    assert recs[-1]["event"] == "run_failed" and recs[-1]["outcome"] == "failed"
    assert isinstance(recs[-1]["duration_ms"], float)


# --- audit is untouched -------------------------------------------------------

def test_logging_module_never_touches_the_audit_trail():
    source = (olog.__file__ or "")
    text = Path(source).read_text()
    for forbidden in ("INSERT INTO audit_event", "AuditRepository", "audit.append"):
        assert forbidden not in text, "operational logging must not write the audit trail"
