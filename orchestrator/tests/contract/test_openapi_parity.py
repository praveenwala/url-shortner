"""T030 — the published contract, the generated document, and the running app agree.

Three things must stay in step: `contracts/orchestrator-api.md` (what we promised), the
committed `docs/contracts/orchestrator-openapi.json` (what we published), and the live FastAPI
router (what we serve). This test fails if any pair diverges, so the next drift breaks the
build instead of being found by a reader.
"""

import json
import re
from pathlib import Path

import pytest

from src.api.app import app

pytestmark = pytest.mark.contract

REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / "specs" / "001-agentic-url-shortener" / "contracts" / "orchestrator-api.md"
GENERATED = REPO / "docs" / "contracts" / "orchestrator-openapi.json"

#: Declared in the contract but deliberately not built. Listed here so a deferral is an
#: explicit entry someone must edit, not a silent absence the checker tolerates.
DEFERRED = {("POST", "/v1/requirements")}


def normalise(path: str) -> str:
    """Compare structure, not parameter spelling: {id} and {run_id} are the same shape."""
    return re.sub(r"\{[^}]+\}", "{}", path.split("?")[0].rstrip("/"))


def contract_operations() -> set[tuple[str, str]]:
    rows = re.findall(r"^\| [^|]+ \| [`*]+([A-Z]+) (/[^`|*\s]+)", CONTRACT.read_text(), re.MULTILINE)
    return {(method, normalise(path)) for method, path in rows}


def live_operations() -> set[tuple[str, str]]:
    spec = app.openapi()
    return {
        (method.upper(), normalise(path))
        for path, operations in spec["paths"].items()
        for method in operations
    }


# --- the three-way agreement --------------------------------------------------

def test_every_declared_operation_is_implemented():
    missing = contract_operations() - live_operations() - {
        (m, normalise(p)) for m, p in DEFERRED
    }
    assert missing == set(), f"declared in the contract but not served: {sorted(missing)}"


def test_every_implemented_operation_is_declared():
    undeclared = live_operations() - contract_operations()
    assert undeclared == set(), (
        f"served but not declared in the contract: {sorted(undeclared)} — "
        f"document it or remove it; an undocumented route is drift"
    )


def test_deferred_operations_are_genuinely_absent():
    """A deferral that quietly got built would make the register a lie."""
    live = live_operations()
    for method, path in DEFERRED:
        assert (method, normalise(path)) not in live, (
            f"{method} {path} is listed as deferred but is now implemented"
        )


def test_the_committed_document_matches_the_running_application():
    assert GENERATED.exists(), (
        "run orchestrator/scripts/generate_openapi.py and commit the result"
    )
    committed = json.loads(GENERATED.read_text())
    live = json.loads(json.dumps(app.openapi(), sort_keys=True))
    assert json.dumps(committed, sort_keys=True) == json.dumps(live, sort_keys=True), (
        "the committed OpenAPI document is stale — regenerate it"
    )


# --- shapes the contract makes promises about ---------------------------------

def test_the_stable_error_envelope_is_published():
    spec = app.openapi()
    assert "ApiErrorBody" in spec["components"]["schemas"]
    envelope = spec["components"]["schemas"]["ApiErrorBody"]["properties"]
    assert set(envelope) == {"error", "message"}


@pytest.mark.parametrize("path,method", [
    ("/v1/runs/{run_id}", "get"),
    ("/v1/runs/{run_id}/graph", "get"),
    ("/v1/runs/{run_id}/gates", "get"),
    ("/v1/runs/{run_id}/audit", "get"),
    ("/v1/runs/{run_id}/decisions", "get"),
    ("/v1/runs/{run_id}/pending", "get"),
    ("/v1/runs/{run_id}/approvals/{request_id}", "post"),
    ("/v1/runs/{run_id}/clarifications/{request_id}", "post"),
    ("/v1/trace", "get"),
])
def test_every_fallible_route_documents_the_error_envelope(path, method):
    responses = app.openapi()["paths"][path][method]["responses"]
    for code in ("400", "401", "403", "404", "409"):
        assert code in responses, f"{method.upper()} {path} does not document {code}"
        schema = responses[code]["content"]["application/json"]["schema"]
        assert "ApiErrorBody" in json.dumps(schema)


def test_approval_and_clarification_request_bodies_are_declared():
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    assert set(schemas["ApprovalBody"]["properties"]) == {"decision", "rationale"}
    assert set(schemas["ClarificationBody"]["properties"]) == {"answer"}

    for path in ("/v1/runs/{run_id}/approvals/{request_id}",
                 "/v1/runs/{run_id}/clarifications/{request_id}"):
        assert "requestBody" in spec["paths"][path]["post"]


def test_decision_and_status_values_match_the_contract():
    """The contract names the vocabulary; the implementation must not widen it."""
    from src.engine.approvals import Checkpoint, Decision

    assert {str(d) for d in Decision} == {"approved", "rejected"}
    assert {str(c) for c in Checkpoint} >= {"architecture", "security", "destructive",
                                            "release", "governance", "scope"}


def test_run_metrics_shape_is_the_fr037_set():
    """US6 put metrics on the run endpoint; the published shape must say so."""
    import inspect

    from src.api import routes

    source = inspect.getsource(routes.get_run)
    for field in ("task_success_rate", "retry_rate", "rollback_rate", "mttr_seconds",
                  "end_to_end_seconds", "human_wait_seconds"):
        assert f'"{field}"' in source, field
