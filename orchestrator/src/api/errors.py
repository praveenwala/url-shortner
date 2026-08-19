"""Stable, machine-readable error identifiers for the orchestrator (FR-016)."""

from enum import StrEnum


class ErrorCode(StrEnum):
    NOT_FOUND = "not_found"
    INVALID_REQUEST = "invalid_request"
    CYCLE_DETECTED = "cycle_detected"
    UNKNOWN_DEPENDENCY = "unknown_dependency"
    MISSING_REQUIREMENT_REF = "missing_requirement_ref"
    INVALID_TRANSITION = "invalid_transition"
    GATE_FAILED = "gate_failed"
    MODE_ESCALATION = "mode_escalation"
    AUDIT_IMMUTABLE = "audit_immutable"
    FORBIDDEN = "forbidden"


class OrchestratorError(Exception):
    code: ErrorCode = ErrorCode.INVALID_REQUEST

    def __init__(self, message: str, code: ErrorCode | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def as_response(self) -> dict[str, str]:
        return {"error": str(self.code), "message": str(self)}
