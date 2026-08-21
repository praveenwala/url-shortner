"""Testcontainers PostgreSQL harness (T010, R3, R10).

Integration tests run against real PostgreSQL, never an in-memory substitute:
R3 selected the store for its concurrency and locking semantics, and testing
against a different engine is how concurrency bugs survive to release.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.store.repository import apply_migrations, make_engine

try:  # the package moved; support both layouts
    from testcontainers.community.postgres import PostgresContainer

    _TESTCONTAINERS = True
except Exception:  # noqa: BLE001 - import guard: any import error means the
    # optional package layout is unavailable; pragma: no cover
    try:
        from testcontainers.postgres import PostgresContainer

        _TESTCONTAINERS = True
    except Exception:  # noqa: BLE001 - same import guard, second layout
        _TESTCONTAINERS = False


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    if not _TESTCONTAINERS:
        pytest.skip("testcontainers not installed")
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def engine(postgres_dsn):
    eng = make_engine(postgres_dsn)
    apply_migrations(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def clean_db(engine):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE trace_link, replan_event, audit_event, change_record,"
                " decision_record, approval_record, gate, task_dependency, task_node,"
                " workflow_run, requirement RESTART IDENTITY CASCADE"
            )
        )
    return engine
