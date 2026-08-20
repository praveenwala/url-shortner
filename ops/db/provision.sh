#!/usr/bin/env bash
#
# Provisioning wrapper for the Agentic URL Shortener (T006, T007 — HUMAN tasks).
#
# Passwords reach psql over stdin, base64-encoded, never as command-line
# arguments. Validation lives here rather than in SQL because psql has no way
# to exit with a chosen status: a shell wrapper can fail cleanly, SQL can only
# fail by erroring.
#
# Usage:
#   SHORTENER_OWNER_PW=... SHORTENER_APP_PW=... \
#   ORCH_OWNER_PW=...      ORCH_APP_PW=...      \
#   ops/db/provision.sh cluster     # roles, databases, isolation, defaults
#
#   ops/db/provision.sh grants      # after migrations; needs no passwords
#
# Connection: standard libpq environment variables (PGHOST, PGPORT, PGUSER,
# PGDATABASE, PGPASSWORD/.pgpass) or PROVISION_DSN. Must connect as a superuser.
#
# No credential is embedded in this file or in the SQL it runs.
#
# ---------------------------------------------------------------------------
# OPERATIONAL ASSUMPTION / ACCEPTED RISK — plaintext password at CREATE ROLE
# ---------------------------------------------------------------------------
# Base64 keeps password values out of argv, out of this repository, and out of
# normal stdout/stderr. It does not, and cannot, keep them out of the statement
# PostgreSQL executes: 01-provision-cluster.sql decodes each value server-side
# and \gexec issues a CREATE ROLE ... LOGIN PASSWORD '<plaintext>' statement.
# The plaintext therefore reaches the server, and any statement logging that
# captures DDL will capture it.
#
# What this means for the operator:
#
#   * Run provisioning against a cluster whose statement logging does not
#     record password-bearing role DDL — log_statement should not be 'all' or
#     'ddl' for the duration, and any external audit or proxy layer in front of
#     PostgreSQL must not capture statement text either.
#   * In production, prefer a dedicated secret/credential provisioning
#     mechanism — a managed-identity or secrets-manager integration that
#     creates and rotates the role credential outside application DDL — over
#     running this script with real production passwords.
#   * Rotate any credential that may have been captured in logs, rather than
#     assuming it was not.
#
# Why it is not fixed here: the durable fix is to never transmit plaintext at
# all, by computing a SCRAM-SHA-256 verifier client-side and issuing
# CREATE ROLE ... PASSWORD 'SCRAM-SHA-256$...' (what psql's \password does
# internally). That is operational hardening, not part of the assignment's
# subject matter, and it is intentionally deferred. This note exists so the
# deferral is a recorded decision rather than an oversight.
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly MIN_PW_LENGTH=12
readonly ORCHESTRATOR_DB="orchestrator_db"

# Environment variable  ->  psql variable receiving its base64 form
readonly PW_VARS=(
  "SHORTENER_OWNER_PW:shortener_owner_pw_b64"
  "SHORTENER_APP_PW:shortener_app_pw_b64"
  "ORCH_OWNER_PW:orch_owner_pw_b64"
  "ORCH_APP_PW:orch_app_pw_b64"
)

usage() {
  cat >&2 <<'USAGE'
usage: provision.sh [cluster|grants]

  cluster   create roles and databases, establish isolation and default
            privileges (ops/db/01-provision-cluster.sql)
            Requires: SHORTENER_OWNER_PW SHORTENER_APP_PW ORCH_OWNER_PW ORCH_APP_PW

  grants    apply per-table runtime privileges after migrations have run
            (ops/db/02-apply-runtime-grants.sql), then verify them
            Requires: no password variables
USAGE
}

die() {
  printf 'provision.sh: %s\n' "$*" >&2
  exit 1
}

# ---------------------------------------------------------------------------
# Validation — reports every failure in one pass, and prints only variable
# names. No value, no length, no prefix, no hash is ever emitted.
# ---------------------------------------------------------------------------
validate_password_vars() {
  local failures=0 entry name value

  for entry in "${PW_VARS[@]}"; do
    name="${entry%%:*}"

    if [[ -z "${!name+is_set}" ]]; then
      printf 'FATAL: %s is not set\n' "$name" >&2
      failures=$((failures + 1))
      continue
    fi

    value="${!name}"
    if (( ${#value} < MIN_PW_LENGTH )); then
      printf 'FATAL: %s is shorter than %d characters\n' "$name" "$MIN_PW_LENGTH" >&2
      failures=$((failures + 1))
    fi
  done
  unset value

  if (( failures > 0 )); then
    printf '\n' >&2
    printf 'Provisioning aborted: %d password variable(s) failed validation.\n' "$failures" >&2
    printf 'Supply them from the environment or a secret store, never from a file\n' >&2
    printf 'in this repository.\n' >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Base64-encode each password into a shell variable. Encoding happens through a
# pipe, so no value is ever an argument, and nothing is written to stdout.
#
# Base64 is encoding, not protection — see the OPERATIONAL ASSUMPTION block
# above. Its purposes here are narrow and real: keeping raw values out of
# anything a human or a log might glance at, and guaranteeing the emitted \set
# lines contain only [A-Za-z0-9+/=], so no password can break out of its
# quoting.
# ---------------------------------------------------------------------------
encode_passwords() {
  local entry name psql_var encoded

  for entry in "${PW_VARS[@]}"; do
    name="${entry%%:*}"
    psql_var="${entry##*:}"

    encoded="$(printf '%s' "${!name}" | base64 | tr -d '\r\n')"
    [[ -n "$encoded" ]] || die "failed to encode $name"

    printf -v "B64_${psql_var}" '%s' "$encoded"
  done
  unset encoded
}

scrub_encoded() {
  local entry psql_var
  for entry in "${PW_VARS[@]}"; do
    psql_var="${entry##*:}"
    unset "B64_${psql_var}" || true
  done
}

# Built once in main(). A plain global array rather than a helper that returns
# lines: `mapfile` is a bash 4 builtin and macOS still ships bash 3.2, so this
# keeps the script runnable with the default shell on a developer laptop.
PSQL_CMD=()

build_psql_cmd() {
  PSQL_CMD=(psql --no-psqlrc --set=ON_ERROR_STOP=1)
  if [[ -n "${PROVISION_DSN:-}" ]]; then
    PSQL_CMD+=(--dbname="$PROVISION_DSN")
  fi
}

# ---------------------------------------------------------------------------
# cluster — the only step that consumes passwords
# ---------------------------------------------------------------------------
run_cluster() {
  validate_password_vars
  encode_passwords

  printf '==> creating roles, databases, isolation and default privileges\n'

  # Everything psql reads arrives on stdin: four \set lines carrying base64
  # values, then \i of the SQL file. Nothing sensitive is in argv, and the
  # stream is never materialised as a file.
  {
    local entry psql_var ref
    for entry in "${PW_VARS[@]}"; do
      psql_var="${entry##*:}"
      ref="B64_${psql_var}"
      printf "\\set %s '%s'\n" "$psql_var" "${!ref}"
    done
    printf "\\i %s\n" "$SCRIPT_DIR/01-provision-cluster.sql"
  } | "${PSQL_CMD[@]}"

  scrub_encoded
}

# ---------------------------------------------------------------------------
# grants — post-migration; deliberately requires no password variables
# ---------------------------------------------------------------------------
run_grants() {
  printf '==> applying post-migration runtime privileges\n'
  "${PSQL_CMD[@]}" -f "$SCRIPT_DIR/02-apply-runtime-grants.sql"

  verify_audit_privileges
}

# The SQL reports the privilege state; the wrapper is what turns a wrong answer
# into a non-zero exit. Keeps assertion logic out of SQL entirely.
verify_audit_privileges() {
  # boolean || text renders as 'true'/'false' — psql's aligned output shows
  # t/f, but concatenation does not. Compare against what actually comes back.
  local expected="true,true,false,false" actual
  actual="$("${PSQL_CMD[@]}" --dbname="$ORCHESTRATOR_DB" -tAX -c "
      SELECT has_table_privilege('orchestrator_app','public.audit_event','SELECT')
          || ',' || has_table_privilege('orchestrator_app','public.audit_event','INSERT')
          || ',' || has_table_privilege('orchestrator_app','public.audit_event','UPDATE')
          || ',' || has_table_privilege('orchestrator_app','public.audit_event','DELETE')
  ")"

  printf '==> audit_event privileges for orchestrator_app '
  printf '(select,insert,update,delete): %s\n' "$actual"

  if [[ "$actual" != "$expected" ]]; then
    die "audit_event privilege check failed: expected '$expected', got '$actual'
The orchestrator runtime role must hold SELECT and INSERT and must NOT hold
UPDATE or DELETE on audit_event (FR-036, approval record item 6)."
  fi
  printf '==> audit immutability verified\n'
}

# ---------------------------------------------------------------------------
main() {
  local step="${1:-}"
  case "$step" in
    -h|--help) usage; exit 0 ;;
    "")        usage; die "no step given" ;;
    cluster|grants) ;;
    *)         usage; die "unknown step: $step" ;;
  esac

  command -v psql   >/dev/null 2>&1 || die "psql not found on PATH"
  command -v base64 >/dev/null 2>&1 || die "base64 not found on PATH"

  build_psql_cmd

  case "$step" in
    cluster) run_cluster ;;
    grants)  run_grants ;;
  esac

  printf '==> done\n'
}

trap scrub_encoded EXIT
main "$@"
