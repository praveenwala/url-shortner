"""Requirement intake and interpretation (T037, FR-020, FR-028).

Principle I made concrete: a written interpretation — scope, actors,
constraints, identified ambiguities — is recorded *before* any implementation
task exists. `record_interpretation` is the only way to move a requirement out
of SUBMITTED, and `Planner` refuses to decompose one that has not been through it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.api.errors import ErrorCode, OrchestratorError


class ResolutionState(StrEnum):
    SUBMITTED = "SUBMITTED"
    INTERPRETED = "INTERPRETED"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    CLARIFIED = "CLARIFIED"


@dataclass(frozen=True, slots=True)
class Ambiguity:
    """FR-028: a specific answerable question, not a general complaint."""

    question: str
    affects: str  # "scope" | "security" | "user_visible_behaviour"

    def __post_init__(self) -> None:
        if not self.question.strip().endswith("?"):
            raise OrchestratorError(
                "an ambiguity must be phrased as an answerable question",
                ErrorCode.INVALID_REQUEST,
            )


@dataclass(slots=True)
class Interpretation:
    scope: str
    actors: list[str]
    constraints: list[str]
    ambiguities: list[Ambiguity] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "actors": list(self.actors),
            "constraints": list(self.constraints),
            "ambiguities": [{"question": a.question, "affects": a.affects} for a in self.ambiguities],
        }


@dataclass(slots=True)
class Requirement:
    id: str
    submitted_text: str
    submitted_by: str
    resolution_state: ResolutionState = ResolutionState.SUBMITTED
    interpretation: Interpretation | None = None

    @property
    def is_interpreted(self) -> bool:
        return self.interpretation is not None

    @property
    def blocking_ambiguities(self) -> list[Ambiguity]:
        if self.interpretation is None:
            return []
        return list(self.interpretation.ambiguities)


def record_interpretation(requirement: Requirement, interpretation: Interpretation) -> Requirement:
    """FR-020. Records the interpretation and, per FR-028, halts on blocking ambiguity."""
    requirement.interpretation = interpretation
    requirement.resolution_state = (
        ResolutionState.AWAITING_CLARIFICATION
        if interpretation.ambiguities
        else ResolutionState.INTERPRETED
    )
    return requirement
