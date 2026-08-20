"""T100 — the traceability matrix stays true, or the build fails.

A traceability document is worth exactly as much as its freshness. Left
unchecked it decays in three specific ways, and this file makes each of them a
build failure rather than something a reader discovers months later:

* a requirement is added to the spec and never reaches the matrix;
* a task id in the matrix stops existing, so a row points at nothing;
* a deferred capability gets implemented while the register still calls it
  deferred — checked by probing for the capability itself, because a register
  that is trusted to describe reality is not a check.

The two known gaps are pinned by id. Closing one means deleting it from
:data:`DECLARED_GAPS`; a *new* gap appearing anywhere fails immediately.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / "specs/001-agentic-url-shortener/spec.md"
TASKS = REPO / "specs/001-agentic-url-shortener/tasks.md"
MATRIX = REPO / "docs/traceability/requirements-traceability.md"

STATUSES = ("COVERED", "DEFERRED_APPROVED", "GAP")

#: Known, reported, owner-visible gaps. Remove an entry when it is closed.
DECLARED_GAPS: frozenset[str] = frozenset({"SC-001", "NFR-008"})

#: Requirements deferred at the implementation level, with the register entry
#: that approves each.
DECLARED_DEFERRALS: frozenset[str] = frozenset({"FR-005", "FR-015"})


def spec_requirements() -> list[str]:
    return re.findall(r"^- \*\*((?:FR|NFR|SC)-\d+)\*\*", SPEC.read_text(), re.M)


MATRIX_HEADING = "## 2. Requirement coverage matrix"


def matrix_section() -> str:
    """Only the matrix table — the summary tables elsewhere use other shapes."""
    text = MATRIX.read_text()
    assert MATRIX_HEADING in text, f"{MATRIX} has no {MATRIX_HEADING!r} section"
    after = text.split(MATRIX_HEADING, 1)[1]
    return after.split("\n## ", 1)[0]


def matrix_rows() -> dict[str, dict[str, str]]:
    """Parse the matrix table into {id: {status, tasks}}."""
    rows: dict[str, dict[str, str]] = {}
    for line in matrix_section().splitlines():
        m = re.match(r"^\| \*\*((?:FR|NFR|SC)-\d+)\*\* \|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 8, f"{m.group(1)} row has {len(cells)} columns, expected 8"
        rows[m.group(1)] = {"status": cells[2], "tasks": cells[3]}
    return rows


def task_ids() -> set[str]:
    return set(re.findall(r"^- \[[X ]\] (T\d+)", TASKS.read_text(), re.M))


# --- 1. every requirement is classified, exactly once ------------------------

def test_every_spec_requirement_appears_in_the_matrix():
    requirements = spec_requirements()
    missing = sorted(set(requirements) - set(matrix_rows()))
    assert not missing, f"requirements absent from the traceability matrix: {missing}"


def test_the_matrix_invents_no_requirement():
    extra = sorted(set(matrix_rows()) - set(spec_requirements()))
    assert not extra, f"matrix rows with no requirement in spec.md: {extra}"


def test_no_requirement_is_listed_twice():
    ids = re.findall(r"^\| \*\*((?:FR|NFR|SC)-\d+)\*\* \|", matrix_section(), re.M)
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicated matrix rows: {duplicates}"


def test_every_row_carries_exactly_one_of_the_three_classifications():
    for rid, row in matrix_rows().items():
        found = [s for s in STATUSES if s in row["status"]]
        # DEFERRED_APPROVED contains no other status as a substring; COVERED and
        # GAP are disjoint. So a well-formed cell yields exactly one hit.
        assert len(found) == 1, f"{rid} has status cell {row['status']!r} (matched {found})"


# --- 2. references resolve ---------------------------------------------------

def test_every_task_id_in_the_matrix_exists():
    known = task_ids()
    dangling: list[tuple[str, str]] = []
    for rid, row in matrix_rows().items():
        for tid in re.findall(r"T\d+", row["tasks"]):
            if tid not in known:
                dangling.append((rid, tid))
    assert not dangling, f"matrix cites task ids that do not exist in tasks.md: {dangling}"


def test_covered_requirements_name_at_least_one_task():
    thin = [
        rid for rid, row in matrix_rows().items()
        if "COVERED" in row["status"] and not re.search(r"T\d+", row["tasks"])
    ]
    assert not thin, f"COVERED with no task reference: {thin}"


# --- 3. gaps stay visible ----------------------------------------------------

def test_no_undeclared_gap_appears():
    gaps = {rid for rid, row in matrix_rows().items() if "GAP" in row["status"]}
    new = sorted(gaps - DECLARED_GAPS)
    assert not new, (
        f"new traceability gap(s): {new}. A gap is a failure condition (FR-035, SC-007) — "
        f"close it, or record an approved deferral and update the register."
    )


def test_declared_gaps_are_still_gaps_or_have_been_removed_from_the_list():
    """Stops a closed gap from lingering in the list and masking a real one."""
    gaps = {rid for rid, row in matrix_rows().items() if "GAP" in row["status"]}
    stale = sorted(DECLARED_GAPS - gaps)
    assert not stale, (
        f"{stale} are no longer gaps in the matrix; remove them from DECLARED_GAPS"
    )


# --- 4. deferrals stay deferred ----------------------------------------------

def test_deferred_requirements_are_marked_deferred_in_the_matrix():
    rows = matrix_rows()
    for rid in DECLARED_DEFERRALS:
        assert "DEFERRED_APPROVED" in rows[rid]["status"], (
            f"{rid} is in the deferred register but the matrix says {rows[rid]['status']!r}"
        )


def test_every_deferral_cites_its_approval_in_the_register():
    register = TASKS.read_text().split("## Deferred Capabilities", 1)
    assert len(register) == 2, "tasks.md has no Deferred Capabilities register"
    for rid in DECLARED_DEFERRALS:
        assert rid in register[1], f"{rid} is not named in tasks.md § Deferred Capabilities"


def test_a_deferred_capability_has_not_been_implemented_behind_the_register():
    """Probe the capability, not the register.

    FR-005 (custom aliases) and FR-015 (rate limiting) have no API surface. If
    either acquires one, the register is stale and this fails — which is the
    point: the register must not be the only thing asserting a thing is absent.
    """
    document = json.loads((REPO / "docs/contracts/shortener-openapi.json").read_text())
    blob = json.dumps(document).lower()
    assert "alias" not in blob, "FR-005 is deferred but an alias surface is now published"
    assert "rate_limit" not in blob, "FR-015 is deferred but a rate-limit surface is published"
    assert "ratelimit" not in blob, "FR-015 is deferred but a rate-limit surface is published"

    create = document["paths"]["/v1/links"]["post"]["requestBody"]
    schema = create["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    fields = set(document["components"]["schemas"][schema]["properties"])
    assert fields == {"destination", "expires_at"}, (
        f"link creation now accepts {sorted(fields)}; a deferred capability may have shipped"
    )
