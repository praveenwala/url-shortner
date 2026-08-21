"""T046 — the agent's tool surface is exactly four tools and nothing more
(FR-041, R6, SC-017)."""

from pathlib import Path

import pytest

from src.agent.allowlist import PathPolicy
from src.agent.client import FORBIDDEN_SERVER_TOOLS, AgentModelConfig, build_request
from src.agent.errors import CheckpointCrossing, ToolViolation
from src.agent.testrunner import TEST_COMMANDS, TestLayer
from src.agent.tools import (
    TOOL_NAMES,
    ToolContext,
    handle_write_file,
    tool_schemas,
)
from src.engine.decompose import TaskNode
from src.models.states import ExecutionMode, Surface

pytestmark = pytest.mark.failure

REPO = Path(__file__).resolve().parents[3]


def _task(outputs=("orchestrator/src/agent/scratch_probe.py",), surface=Surface.ORCHESTRATOR):
    return TaskNode(
        id="t1", description="bounded task", requirement_ref="FR-041",
        execution_mode=ExecutionMode.AGENT_AUTHORED, surface=surface,
        declared_outputs=outputs,
    )


def _ctx(task=None):
    return ToolContext(repo_root=REPO, task=task or _task())


# --- exactly four tools -----------------------------------------------------

def test_tool_set_is_exactly_four():
    assert TOOL_NAMES == ("read_file", "write_file", "run_tests", "report")
    assert {t["name"] for t in tool_schemas()} == set(TOOL_NAMES)


def test_no_shell_exec_git_or_package_tool_exists():
    names = {t["name"] for t in tool_schemas()}
    for forbidden in ("bash", "exec", "shell", "git", "pip", "npm", "install", "fetch", "http"):
        assert not any(forbidden in n for n in names), f"{forbidden} reachable"


def test_no_tool_accepts_a_command_url_host_or_port():
    for tool in tool_schemas():
        props = tool["input_schema"]["properties"]
        for field in props:
            assert field not in {"command", "cmd", "argv", "url", "host", "port", "image"}
        assert tool["input_schema"]["additionalProperties"] is False
        assert tool["strict"] is True


def test_run_tests_accepts_only_an_enum_layer():
    schema = next(t for t in tool_schemas() if t["name"] == "run_tests")
    props = schema["input_schema"]["properties"]
    assert set(props) == {"layer"}
    assert set(props["layer"]["enum"]) == {layer.value for layer in TestLayer}


def test_test_commands_are_argv_tuples_never_strings():
    """No shell in this path, so metacharacters have no meaning."""
    for key, argv in TEST_COMMANDS.items():
        assert isinstance(argv, tuple), key
        assert all(isinstance(part, str) for part in argv)
        joined = " ".join(argv)
        assert ";" not in joined and "&&" not in joined and "$(" not in joined


# --- server-side tools are not declared -------------------------------------

def test_server_side_tools_and_mcp_are_not_declared():
    request = build_request(AgentModelConfig(), "sys", [{"role": "user", "content": "hi"}])
    declared = {t["name"] for t in request["tools"]}
    assert not (declared & FORBIDDEN_SERVER_TOOLS)
    assert "mcp_servers" not in request
    assert all(t.get("type") is None for t in request["tools"]), "no Anthropic-defined tool"


def test_task_budget_and_adaptive_thinking_are_declared():
    request = build_request(AgentModelConfig(), "sys", [])
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"]["task_budget"]["total"] >= 20_000


# --- read / write allow-lists -----------------------------------------------

def test_read_outside_surface_is_refused():
    policy = PathPolicy(repo_root=REPO, task=_task())
    for bad in ("ops/db/provision.sql", "shortener/pom.xml", "../etc/passwd",
                ".git/config", "specs/001-agentic-url-shortener/plan.md"):
        with pytest.raises(ToolViolation):
            policy.resolve_read(bad)


def test_read_inside_surface_is_allowed():
    policy = PathPolicy(repo_root=REPO, task=_task())
    assert policy.resolve_read("orchestrator/src/models/states.py").exists()


def test_write_to_undeclared_output_is_refused_and_changes_nothing(tmp_path):
    ctx = _ctx()
    target = REPO / "orchestrator/src/models/states.py"
    before = target.read_bytes()
    with pytest.raises(ToolViolation):
        handle_write_file(ctx, "orchestrator/src/models/states.py", "tampered")
    assert target.read_bytes() == before
    assert ctx.changes == []


def test_write_to_another_surface_is_refused():
    ctx = _ctx(_task(outputs=("orchestrator/src/agent/scratch_probe.py",)))
    with pytest.raises(ToolViolation):
        handle_write_file(ctx, "shortener/src/main/java/X.java", "x")


def test_write_to_build_manifest_is_a_checkpoint_not_a_violation():
    """Tier C: a decision a human must make, not a mistake to correct."""
    ctx = _ctx(_task(outputs=("orchestrator/pyproject.toml",)))
    with pytest.raises(CheckpointCrossing):
        handle_write_file(ctx, "orchestrator/pyproject.toml", "[project]\n")


def test_symlink_escape_is_resolved_and_refused(tmp_path):
    """Containment is checked on the resolved path, not the supplied string."""
    link = REPO / "orchestrator" / "src" / "agent" / "escape_probe_link"
    link.symlink_to(REPO / "ops")
    try:
        policy = PathPolicy(repo_root=REPO, task=_task())
        with pytest.raises(ToolViolation):
            policy.resolve_read("orchestrator/src/agent/escape_probe_link/db/provision.sql")
    finally:
        link.unlink(missing_ok=True)


def test_reading_a_directory_is_refused():
    policy = PathPolicy(repo_root=REPO, task=_task())
    with pytest.raises(ToolViolation):
        policy.resolve_read("orchestrator/src")
