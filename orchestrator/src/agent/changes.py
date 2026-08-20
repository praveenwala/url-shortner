"""Prior-state capture and atomic write (T052, FR-032, FR-044).

Capture happens *before* a byte is modified, so a crash mid-write still leaves a
restorable record. Deletion exists in exactly one place — reverting a file that
did not previously exist — and no tool can reach it.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.agent.errors import ToolViolation

MAX_INLINE_PRIOR_STATE = 256 * 1024
MAX_WRITE_BYTES = 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    task_id: str
    surface: str
    artifact_path: str
    execution_mode: str
    existed: bool
    prior_state: str | None
    prior_sha256: str | None
    new_sha256: str
    applied_at: str
    approving_human: str | None = None


def apply_write(
    *, path: Path, content: str, task_id: str, surface: str, execution_mode: str,
    relative_path: str, now_iso: str, approving_human: str | None = None,
) -> ChangeRecord:
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ToolViolation(f"write of {len(encoded)} bytes exceeds the cap")

    existed = path.exists()
    prior_bytes = path.read_bytes() if existed else b""
    if existed and len(prior_bytes) > MAX_INLINE_PRIOR_STATE:
        # Refuse rather than make the change irreversible.
        raise ToolViolation(
            f"{relative_path!r} is too large to capture prior state; write refused so the "
            f"change cannot become unrevertible"
        )

    record = ChangeRecord(
        task_id=task_id, surface=surface, artifact_path=relative_path,
        execution_mode=execution_mode, existed=existed,
        prior_state=prior_bytes.decode("utf-8", "replace") if existed else None,
        prior_sha256=_sha256(prior_bytes) if existed else None,
        new_sha256=_sha256(encoded), applied_at=now_iso,
        approving_human=approving_human,
    )

    # Atomic: temp file in the same directory, fsync, rename. No partially
    # written artifact can exist even if the process dies mid-write.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".agent-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return record


def revert(record: ChangeRecord, path: Path) -> None:
    """Restore the artifact to its pre-change state.

    Refuses if the file changed again after this record was written — clobbering
    a later edit during a rollback would be its own failure.
    """
    if path.exists():
        current = _sha256(path.read_bytes())
        if current != record.new_sha256:
            raise ToolViolation(
                f"{record.artifact_path!r} changed after this record was written; "
                f"refusing to revert over a later edit"
            )
    if record.existed:
        assert record.prior_state is not None
        path.write_text(record.prior_state, encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def revert_all(records: list[ChangeRecord], resolve: "callable[[str], Path]") -> None:
    """Reverse-chronological, so a file written twice returns to its true original."""
    for record in reversed(records):
        revert(record, resolve(record.artifact_path))
