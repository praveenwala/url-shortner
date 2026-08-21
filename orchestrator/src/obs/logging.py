"""Structured operational logging for the orchestrator.

**Operational logs are not the audit trail.** `audit_event` is the governance record: append-only,
privilege-enforced, and the thing a compliance reader reconstructs a run from. These logs are for
the operator diagnosing a service at 03:00. They carry the same correlation identifiers so the two
can be joined, and neither replaces the other — nothing here writes to or reads from `audit_event`.

Three properties this module exists to guarantee:

* **JSON on stdout, standard library only.** No vendor SDK, no network sink. A container runtime
  collects stdout; that is the whole transport.
* **Secrets never reach a log line.** Every emitted record is screened by the same value-side
  detector that guards audit payloads (`store.repository._reject_secrets`), so a DSN or an API key
  in a message is dropped rather than printed. Redaction failure is not a silent pass.
* **Logging cannot break orchestration.** Every entry point swallows its own exceptions. An
  observability fault must never fail a run — that would make the diagnostic tool the outage.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

SERVICE = "orchestrator"

#: The lifecycle vocabulary. A closed set so dashboards and alerts can rely on the names, and so a
#: typo produces a visible failure in review rather than a silently unqueryable log line.
EVENTS: frozenset[str] = frozenset(
    {
        "orchestrator_started", "orchestrator_stopping",
        "run_started", "run_completed", "run_failed",
        "node_started", "node_completed", "node_failed",
        "retry_scheduled", "fallback_selected", "safe_stop", "waiting_for_human",
        "approval_decision", "replan_started", "replan_completed",
        "sandbox_unavailable", "postgres_readiness_failed",
    }
)

#: Fields promoted to top level when present. Anything else goes under `detail`, so the shape a
#: log query depends on stays stable no matter what a call site passes.
_PROMOTED = (
    "correlation_id", "trace_id", "span_id", "run_id", "node_id",
    "actor_id", "attempt", "duration_ms", "outcome",
)

_REDACTED = "[redacted]"


def _screen(value: Any) -> Any:
    """Drop anything that looks like a credential.

    Reuses the audit trail's detector so operational logs and audit payloads cannot disagree about
    what counts as a secret. Fails closed: if the detector itself errors, the value is redacted.
    """
    if not isinstance(value, str):
        return value
    try:
        from src.store.repository import _reject_secrets

        _reject_secrets({"v": value})
        return value
    except Exception:  # noqa: BLE001 - the detector's own failure must redact, never leak
        return _REDACTED


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": SERVICE,
            "event": getattr(record, "event", record.name),
        }
        fields = dict(getattr(record, "fields", {}) or {})
        for key in _PROMOTED:
            if key in fields and fields[key] is not None:
                payload[key] = _screen(fields.pop(key))
        message = record.getMessage()
        if message and message != payload["event"]:
            payload["message"] = _screen(message)
        if fields:
            payload["detail"] = {k: _screen(v) for k, v in fields.items()}
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "error"
        return json.dumps(payload, default=str, separators=(",", ":"))


_configured = False


def configure(level: str | None = None, stream: Any = None) -> None:
    """Install the JSON handler once. Safe to call repeatedly."""
    global _configured
    if _configured and stream is None:
        return
    logger = logging.getLogger(SERVICE)
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel((level or os.environ.get("ORCHESTRATOR_LOG_LEVEL", "INFO")).upper())
    logger.propagate = False
    _configured = True


def log(event: str, level: int = logging.INFO, message: str = "", **fields: Any) -> None:
    """Emit one operational record. Never raises.

    An unknown `event` is emitted rather than dropped — losing a log line because its name was
    wrong is worse than an off-vocabulary name — but it is marked so it can be found and fixed.
    """
    try:
        configure()
        if event not in EVENTS:
            fields = {**fields, "unknown_event": True}
        logging.getLogger(SERVICE).log(
            level, message or event, extra={"event": event, "fields": fields}
        )
    except Exception:  # noqa: BLE001,S110 - observability must never break orchestration.
        # Deliberately silent: the only place left to report a logging failure is logging.
        pass


def warn(event: str, message: str = "", **fields: Any) -> None:
    log(event, logging.WARNING, message, **fields)


def error(event: str, message: str = "", **fields: Any) -> None:
    log(event, logging.ERROR, message, **fields)


@contextmanager
def timed(event_started: str, event_completed: str, event_failed: str, **fields: Any) -> Iterator[dict]:
    """Bracket an operation, emitting start/completion with a measured `duration_ms`.

    The yielded dict is writable, so a call site can attach an outcome discovered during the work.
    """
    started = time.monotonic()
    log(event_started, **fields)
    extra: dict[str, Any] = {}
    try:
        yield extra
    except Exception as exc:
        error(
            event_failed,
            str(exc)[:200],
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            outcome="failed",
            **{**fields, **extra},
        )
        raise
    log(
        event_completed,
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        outcome=extra.pop("outcome", "succeeded"),
        **{**fields, **extra},
    )
