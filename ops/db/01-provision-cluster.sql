-- ops/db/01-provision-cluster.sql
--
-- Roles, databases, isolation, and default privileges (T006 — HUMAN task).
-- Approved architecture: two databases, four roles — an owner and a runtime
-- role per service (plan.md § Architecture Approval Record, items 3 and 6;
-- research R3).
--
-- Not intended to be run directly. ops/db/provision.sh validates the four
-- password environment variables, base64-encodes them, and pipes four \set
-- lines plus \i of this file over stdin. Passwords therefore never appear in
-- command-line arguments. This file expects these psql variables to be set:
--
--     shortener_owner_pw_b64   shortener_app_pw_b64
--     orch_owner_pw_b64        orch_app_pw_b64
--
-- each holding the base64 form of a password. There is deliberately no
-- validation logic here — the wrapper is the gate.
--
-- Re-running is safe: role and database creation are guarded by existence
-- checks, and GRANT/REVOKE are idempotent. An existing role's password is never
-- reset by a re-run — rotate deliberately with an explicit ALTER ROLE.
--
-- Nothing here is wrapped in BEGIN/COMMIT. psql runs in autocommit, which
-- CREATE DATABASE requires: it cannot execute inside a transaction block.

\set ON_ERROR_STOP on

-- =====================================================================
-- 1. Roles — owner and runtime are deliberately different identities
-- =====================================================================
-- The owner runs migrations and owns the tables. The runtime role only reads
-- and writes rows. They must not be the same role: a table's owner can always
-- re-grant privileges to itself, so revoking UPDATE from an owner is not a
-- guarantee. This split is what makes audit immutability in 02 actually hold.
--
-- The password arrives base64-encoded in a psql variable. Decoding happens
-- server-side inside the SELECT: decode() yields bytea, convert_from() turns it
-- back into text, and format(%L) quotes it for CREATE ROLE. \gexec then runs
-- the statement that comes back.
--
-- Interpolation happens in an ordinary SELECT, never inside a dollar-quoted
-- body: psql does not substitute variables within quoted SQL literals or
-- dollar-quoted strings. Because the interpolated value is base64, it contains
-- only [A-Za-z0-9+/=] and cannot break out of its quoting.
--
-- When a role already exists the SELECT returns no rows, \gexec runs nothing,
-- and the existing password is left untouched.
--
-- Operational note: \gexec issues a CREATE ROLE statement containing the
-- decoded plaintext password, so the plaintext does reach the server and any
-- DDL statement logging will capture it. See the OPERATIONAL ASSUMPTION block
-- in ops/db/provision.sh for the accepted risk and the required mitigations.

SELECT format('CREATE ROLE shortener_owner LOGIN PASSWORD %L',
              convert_from(decode(:'shortener_owner_pw_b64', 'base64'), 'UTF8'))
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shortener_owner')
\gexec

SELECT format('CREATE ROLE shortener_app LOGIN PASSWORD %L',
              convert_from(decode(:'shortener_app_pw_b64', 'base64'), 'UTF8'))
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'shortener_app')
\gexec

SELECT format('CREATE ROLE orchestrator_owner LOGIN PASSWORD %L',
              convert_from(decode(:'orch_owner_pw_b64', 'base64'), 'UTF8'))
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orchestrator_owner')
\gexec

SELECT format('CREATE ROLE orchestrator_app LOGIN PASSWORD %L',
              convert_from(decode(:'orch_app_pw_b64', 'base64'), 'UTF8'))
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orchestrator_app')
\gexec

-- Attribute hardening is idempotent and touches no password.
ALTER ROLE shortener_owner    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE shortener_app      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE orchestrator_owner NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE orchestrator_app   NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

-- =====================================================================
-- 2. Databases — PostgreSQL has no CREATE DATABASE IF NOT EXISTS
-- =====================================================================
SELECT 'CREATE DATABASE shortener_db OWNER shortener_owner'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'shortener_db')
\gexec

SELECT 'CREATE DATABASE orchestrator_db OWNER orchestrator_owner'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'orchestrator_db')
\gexec

-- =====================================================================
-- 3. Cross-database isolation (NFR-002, NFR-006)
-- =====================================================================
-- PUBLIC has CONNECT on every database by default, which would let either
-- service reach the other's data. Revoke it, then grant CONNECT only to the
-- roles that belong to each database. This is the boundary that makes
-- "neither role can read the other's database" true rather than assumed.

REVOKE ALL     ON DATABASE shortener_db    FROM PUBLIC;
REVOKE ALL     ON DATABASE orchestrator_db FROM PUBLIC;

GRANT  CONNECT ON DATABASE shortener_db    TO shortener_owner, shortener_app;
GRANT  CONNECT ON DATABASE orchestrator_db TO orchestrator_owner, orchestrator_app;

-- Explicit and redundant, stated because the requirement is explicit.
REVOKE CONNECT ON DATABASE shortener_db    FROM orchestrator_owner, orchestrator_app;
REVOKE CONNECT ON DATABASE orchestrator_db FROM shortener_owner, shortener_app;

-- =====================================================================
-- 4. shortener_db — schema ownership and default privileges
-- =====================================================================
\connect shortener_db

ALTER SCHEMA public OWNER TO shortener_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT  USAGE ON SCHEMA public TO shortener_app;

-- Applies to objects created by shortener_owner, so Flyway migrations must run
-- as that role for these defaults to attach.
ALTER DEFAULT PRIVILEGES FOR ROLE shortener_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO shortener_app;
ALTER DEFAULT PRIVILEGES FOR ROLE shortener_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO shortener_app;

-- =====================================================================
-- 5. orchestrator_db — schema ownership and default privileges
-- =====================================================================
\connect orchestrator_db

ALTER SCHEMA public OWNER TO orchestrator_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT  USAGE ON SCHEMA public TO orchestrator_app;

-- Deliberately the safe minimum: SELECT and INSERT. Tables that genuinely need
-- UPDATE are granted it by name in 02. A new table added by a future migration
-- therefore arrives append-only until someone decides otherwise.
ALTER DEFAULT PRIVILEGES FOR ROLE orchestrator_owner IN SCHEMA public
  GRANT SELECT, INSERT ON TABLES TO orchestrator_app;
ALTER DEFAULT PRIVILEGES FOR ROLE orchestrator_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO orchestrator_app;

\echo 'cluster provisioned. run migrations, then: ops/db/provision.sh grants'
