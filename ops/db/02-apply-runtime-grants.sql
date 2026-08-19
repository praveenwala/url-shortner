-- ops/db/02-apply-runtime-grants.sql
--
-- Per-table runtime privileges (T007 — HUMAN task).
--
-- RUN AFTER MIGRATIONS. Grants cannot be issued on tables that do not exist
-- yet; under ON_ERROR_STOP a premature run stops on the first missing relation
-- with a message naming it.
--
-- Invoked by ops/db/provision.sh, which also asserts the resulting privileges
-- and turns a wrong answer into a non-zero exit. This file declares state and
-- reports it; the wrapper decides whether that state is acceptable.
--
-- No password variables are used or needed here.

\set ON_ERROR_STOP on

-- =====================================================================
-- 1. shortener_db — pick up tables created by migrations
-- =====================================================================
-- Default privileges from 01 cover future tables, but re-applying here makes
-- the step correct even if a migration ran under a different role.
\connect shortener_db

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO shortener_app;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO shortener_app;

-- =====================================================================
-- 2. orchestrator_db — baseline, then the audit exception
-- =====================================================================
\connect orchestrator_db

GRANT SELECT, INSERT ON ALL TABLES    IN SCHEMA public TO orchestrator_app;
GRANT USAGE, SELECT  ON ALL SEQUENCES IN SCHEMA public TO orchestrator_app;

-- Tables whose rows legitimately change state (FR-025). Named individually
-- rather than granted wholesale, so a new table never inherits UPDATE silently.
GRANT UPDATE ON public.workflow_run TO orchestrator_app;
GRANT UPDATE ON public.task_node    TO orchestrator_app;
GRANT UPDATE ON public.requirement  TO orchestrator_app;
GRANT UPDATE ON public.gate         TO orchestrator_app;

-- ---------------------------------------------------------------------
-- audit_event: append and read only (FR-036, NFR-004, approval item 6)
-- ---------------------------------------------------------------------
GRANT  SELECT, INSERT ON public.audit_event TO orchestrator_app;

-- The immutability guarantee. Application code already exposes no update path;
-- this makes the database refuse one even if the code changes.
REVOKE UPDATE, DELETE ON public.audit_event FROM orchestrator_app;

-- Flanking routes: TRUNCATE empties the table without DELETE, and TRIGGER would
-- allow attaching logic that mutates rows.
REVOKE TRUNCATE, REFERENCES, TRIGGER ON public.audit_event FROM orchestrator_app;
REVOKE ALL ON public.audit_event FROM PUBLIC;

-- BIGSERIAL inserts need the sequence; SELECT on it is not granted because
-- nothing reads it directly.
GRANT USAGE ON SEQUENCE public.audit_event_id_seq TO orchestrator_app;

-- =====================================================================
-- 3. Report resulting privileges (the wrapper asserts on these)
-- =====================================================================
\echo ''
\echo 'orchestrator_app privileges on audit_event (expected: t, t, f, f):'

SELECT
  has_table_privilege('orchestrator_app', 'public.audit_event', 'SELECT') AS can_select,
  has_table_privilege('orchestrator_app', 'public.audit_event', 'INSERT') AS can_insert,
  has_table_privilege('orchestrator_app', 'public.audit_event', 'UPDATE') AS can_update,
  has_table_privilege('orchestrator_app', 'public.audit_event', 'DELETE') AS can_delete;

\echo ''
\echo 'orchestrator_app UPDATE on state-bearing tables (expected: all t):'

SELECT
  has_table_privilege('orchestrator_app', 'public.workflow_run', 'UPDATE') AS workflow_run,
  has_table_privilege('orchestrator_app', 'public.task_node',    'UPDATE') AS task_node,
  has_table_privilege('orchestrator_app', 'public.requirement',  'UPDATE') AS requirement,
  has_table_privilege('orchestrator_app', 'public.gate',         'UPDATE') AS gate;

\echo ''
\echo 'cross-database isolation (expected: all f):'

SELECT
  has_database_privilege('orchestrator_app', 'shortener_db',    'CONNECT') AS orch_app_to_shortener,
  has_database_privilege('orchestrator_owner','shortener_db',   'CONNECT') AS orch_owner_to_shortener,
  has_database_privilege('shortener_app',     'orchestrator_db','CONNECT') AS short_app_to_orch,
  has_database_privilege('shortener_owner',   'orchestrator_db','CONNECT') AS short_owner_to_orch;
