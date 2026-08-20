"""Actors and roles (FR-029, FR-050).

The rule that matters: an agent identity can never hold the approver role. Not
"is not currently granted it" — cannot be granted it. Making that a construction
error rather than a check at decision time means there is no window in which a
mis-provisioned actor exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.api.errors import ErrorCode, OrchestratorError

APPROVER_ROLE = "approver"
AGENT_ID_PREFIX = "agent:"
HUMAN_ID_PREFIX = "human:"


class AgentCannotHoldApproverRole(OrchestratorError):
    code = ErrorCode.FORBIDDEN


@dataclass(frozen=True, slots=True)
class Actor:
    id: str
    roles: frozenset[str]

    def __post_init__(self) -> None:
        if not self.id or ":" not in self.id:
            raise OrchestratorError(
                f"actor id {self.id!r} must be namespaced, e.g. human:lead",
                ErrorCode.INVALID_REQUEST,
            )
        if self.is_agent and APPROVER_ROLE in self.roles:
            raise AgentCannotHoldApproverRole(
                f"{self.id!r} is an agent identity and can never hold the approver role "
                f"(FR-050); approval is a human act"
            )

    @property
    def is_agent(self) -> bool:
        return self.id.startswith(AGENT_ID_PREFIX)

    @property
    def is_human(self) -> bool:
        return self.id.startswith(HUMAN_ID_PREFIX)

    def holds(self, role: str) -> bool:
        # Belt and braces: even if a role set were constructed by some future
        # path that bypassed __post_init__, an agent still holds nothing.
        if self.is_agent:
            return False
        return role in self.roles
