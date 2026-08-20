"""Anthropic client construction for bounded tasks (T053).

The single most important property of this module is what it does **not** do:
`web_search`, `web_fetch`, and `code_execution` are never declared, and no MCP
connector is configured. Declaring any of them would let the agent cause
arbitrary outbound requests through the model provider — turning the one
permitted egress into a general-purpose proxy and making the Claude channel a
bypass of the whole boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agent.tools import TOOL_NAMES, tool_schemas

DEFAULT_MODEL = "claude-opus-5"
TASK_BUDGET_BETA = "task-budgets-2026-03-13"
MIN_TASK_BUDGET_TOKENS = 20_000

#: Server-side tools that must never appear in a request from this runtime.
FORBIDDEN_SERVER_TOOLS: frozenset[str] = frozenset(
    {"web_search", "web_fetch", "code_execution", "bash", "str_replace_based_edit_tool"}
)


@dataclass(frozen=True, slots=True)
class AgentModelConfig:
    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_tokens: int = 32_000
    task_budget_tokens: int = MIN_TASK_BUDGET_TOKENS

    def __post_init__(self) -> None:
        if self.task_budget_tokens < MIN_TASK_BUDGET_TOKENS:
            raise ValueError(
                f"task budget must be at least {MIN_TASK_BUDGET_TOKENS} tokens"
            )


def build_request(config: AgentModelConfig, system: str, messages: list[dict[str, Any]]
                  ) -> dict[str, Any]:
    """Assemble the request. Kept as data so a test can assert on it without a
    network call — which is how `test_capability_boundary` proves no server-side
    tool is declared."""
    tools = tool_schemas()
    declared = {tool["name"] for tool in tools}
    if declared & FORBIDDEN_SERVER_TOOLS:
        raise AssertionError("a forbidden server-side tool leaked into the tool set")
    if declared != set(TOOL_NAMES):
        raise AssertionError(f"tool set must be exactly {TOOL_NAMES}, got {sorted(declared)}")

    return {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": system,
        "messages": messages,
        "tools": tools,
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": config.effort,
            "task_budget": {"type": "tokens", "total": config.task_budget_tokens},
        },
        "betas": [TASK_BUDGET_BETA],
        # Deliberately absent: mcp_servers, and any server-side tool.
    }
