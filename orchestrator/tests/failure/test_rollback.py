"""T052 — prior-state capture makes every agent-authored change revertible
(FR-032, FR-044, SC-018)."""

from pathlib import Path

import pytest

from src.agent.changes import apply_write, revert, revert_all
from src.agent.errors import ToolViolation

pytestmark = pytest.mark.failure


def _write(path: Path, content: str, when="2026-08-18T00:00:00+00:00"):
    return apply_write(
        path=path, content=content, task_id="t1", surface="orchestrator",
        execution_mode="agent_authored", relative_path=path.name, now_iso=when,
    )


def test_modified_file_is_restored_byte_identical(tmp_path):
    target = tmp_path / "module.py"
    target.write_text("original\n", encoding="utf-8")
    original = target.read_bytes()

    record = _write(target, "rewritten by the agent\n")
    assert target.read_text() == "rewritten by the agent\n"
    assert record.existed and record.prior_sha256

    revert(record, target)
    assert target.read_bytes() == original


def test_created_file_is_removed_on_revert(tmp_path):
    target = tmp_path / "new_module.py"
    record = _write(target, "created\n")
    assert target.exists() and record.existed is False

    revert(record, target)
    assert not target.exists()


def test_double_write_reverts_to_the_true_original(tmp_path):
    target = tmp_path / "module.py"
    target.write_text("v0\n", encoding="utf-8")
    records = [_write(target, "v1\n"), _write(target, "v2\n")]
    assert target.read_text() == "v2\n"

    revert_all(records, lambda _rel: target)
    assert target.read_text() == "v0\n"


def test_revert_refuses_to_clobber_a_later_edit(tmp_path):
    target = tmp_path / "module.py"
    target.write_text("v0\n", encoding="utf-8")
    record = _write(target, "v1\n")

    target.write_text("edited by someone else\n", encoding="utf-8")
    with pytest.raises(ToolViolation):
        revert(record, target)
    assert target.read_text() == "edited by someone else\n"


def test_oversize_prior_state_refuses_the_write_rather_than_losing_reversibility(tmp_path):
    target = tmp_path / "big.py"
    target.write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ToolViolation):
        _write(target, "small\n")
    assert target.stat().st_size > 256 * 1024, "the original must be untouched"


def test_write_is_atomic_and_leaves_no_temp_files(tmp_path):
    target = tmp_path / "module.py"
    _write(target, "content\n")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".agent-")]
    assert leftovers == []
