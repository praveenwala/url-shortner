"""Failure taxonomy for the bounded agent runtime.

Three tiers, deliberately distinct (contracts/agent-runtime.md §7):

* :class:`PreconditionFailed` — tier A. The task is never dispatched; no model
  call is made. Requires replanning.
* :class:`ToolViolation` — tier B. One tool call is refused and returned to the
  agent as an error result. Recoverable, and counted.
* :class:`CheckpointCrossing` — tier C. Halt *before* apply; the run waits for a
  human. Nothing is written.

:class:`SafeStop` is the escalation: the run halts, state is preserved, a human
is notified. It is never a retry.
"""

from __future__ import annotations

from src.api.errors import ErrorCode, OrchestratorError


class PreconditionFailed(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


class ToolViolation(OrchestratorError):
    code = ErrorCode.FORBIDDEN


class CheckpointCrossing(OrchestratorError):
    code = ErrorCode.FORBIDDEN


class SafeStop(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


class SandboxError(OrchestratorError):
    code = ErrorCode.INVALID_REQUEST


class SandboxUnavailable(SandboxError):
    """The sandbox cannot be established — no Docker daemon, or a missing image.

    This is deliberately a *boundary* failure, not a degradation. `run_tests`
    never falls back to host execution: without the sandbox there is no boundary
    around agent-authored code, so the only safe response is to stop.
    """

    code = ErrorCode.FORBIDDEN


class EgressDenied(OrchestratorError):
    code = ErrorCode.FORBIDDEN
