# Agentic URL Shortener

## 1. What this project is

A production-quality **URL shortener** delivered by an **agentic SDLC orchestration system** that
interprets a requirement, plans a dependency graph, implements, tests and reviews it — under
explicit human control.

The shortener is the *workload*: real engineering with exact analytics under concurrency, a
measured latency budget, and an availability boundary. The orchestrator is the *differentiator*
and the actual subject of the exercise: **can an agent be given real delivery work with bounds a
bank would accept?** That question needs concrete work to be answered against, which is what the
shortener provides.

Four moving parts: a **Java 21 / Spring Boot** shortener service, a **Python 3.13 / FastAPI**
orchestrator, a **React 18 / TypeScript** console, and **PostgreSQL 16** with two databases and
four roles.

## 2. Architecture overview

```mermaid
graph TB
    visitor[Visitor] -->|"GET /{code} → 302"| SH
    client[API client] -->|"POST /v1/links"| SH
    SH["<b>Shortener</b><br/>Java 21 · Spring Boot 3<br/>:8080"] --> SDB[("shortener_db<br/>shortener_owner / shortener_app")]

    human[Requirement owner] --> CON["<b>Console</b><br/>React 18 · Vite<br/>:5173"]
    CON -->|"REST via Vite proxy"| OR
    OR["<b>Orchestrator</b><br/>Python 3.13 · FastAPI<br/>:8000"] --> ODB[("orchestrator_db<br/>orchestrator_owner / orchestrator_app<br/>audit_event: INSERT+SELECT only")]
    OR -->|"egress allow-list"| CLAUDE["Claude API<br/><i>only external endpoint</i>"]
    OR -->|"docker run --network none"| SBX["<b>Agent sandbox</b><br/>ephemeral · non-root · cap-drop ALL<br/>disposable copy of ONE surface"]
    OR -.->|"authors changes in"| REPO[("repository")]
    REPO -.->|"is the source of"| SH

    human -->|"approve / reject + rationale"| GATE{{"<b>Human approval boundary</b><br/>architecture · security · destructive<br/>release · governance · scope"}}
    GATE --> OR
```

- **Shortener service** — creates, resolves, revokes and reports analytics. One connection pool
  (`redirect-pool`, 16). Analytics does not compete with the redirect path because the summary is
  a bounded primary-key lookup against counters denormalised onto `short_link` — it never scans
  `redirect_event`. A separate analytics pool is deferred until FR-014 event-history analytics
  introduces a query shape that justifies one (§20).
- **Orchestrator service** — DAG construction with cycle rejection, entry/exit gates, ambiguity
  detection, clarifications, approvals, bounded execution, selective replanning, rollback, audit.
- **Console** — exactly two views (Run, Human action). Holds no store and no cache; every value is
  re-fetched, so it can never be the only place a fact lives.
- **Database ownership boundaries** — two databases, four roles, **no credential spanning both**.
  Each `*_owner` runs migrations; each `*_app` has DML only. `orchestrator_app` holds
  **INSERT and SELECT on `audit_event` and nothing else**, so audit immutability is a database
  privilege rather than a code convention.
- **Agent sandbox** — agent-authored code executes only in an ephemeral container against a
  disposable copy of one surface. The authoritative repository is never mounted.
- **Human approval boundary** — checkpoint-crossing actions halt *before* apply. An approval binds
  to one `action_fingerprint`; roles come from a server-side directory; no agent identity can
  approve.

The orchestrator **never calls the shortener at runtime**. It builds it.

## 3. Prerequisites

### Required

| Tool | Version | Used for |
|---|---|---|
| **JDK** | **21** | Shortener build and run |
| **Maven** | 3.9+ (or the bundled wrapper) | Java build and tests |
| **Python** | **3.13** | Orchestrator |
| **Node.js / npm** | Node 20+ | Console |
| **Docker** | 20.10+ (tested on 29.4.3) | PostgreSQL, Testcontainers, agent sandbox |
| **PostgreSQL** | **16** | Run via Docker — the supported local path |
| **curl** | any | Verification commands below |

Docker is genuinely required, not optional: the orchestrator's `run_tests` capability, the
Testcontainers integration layer, and the local databases all depend on it.

### Optional

| Tool | Used for |
|---|---|
| `psql` client on the host | Convenience — every documented DB command uses `docker exec` instead |
| `jq` | Prettier JSON in the curl examples |

### Platform notes

- **macOS** — `JAVA_HOME=$(/usr/libexec/java_home -v 21)` selects JDK 21. This helper is
  macOS-only.
- **Linux** — use your distribution's equivalent, e.g.
  `export JAVA_HOME=/usr/lib/jvm/java-21-openjdk`.
- The shell default JDK on the development machine was Java 8, so **always set `JAVA_HOME`
  explicitly** before any Maven command. See §21.

## 4. Repository structure

```
shortener/     Java 21 + Spring Boot 3 shortener service (the workload)
orchestrator/  Python 3.13 + FastAPI orchestration control plane and bounded agent runtime
console/       React 18 + TypeScript + Vite human console (two views)
ops/           Operator scripts: DB provisioning, sandbox images, smoke checks. Not runtime code
docs/          HLD, LLD, generated OpenAPI contracts, security and traceability evidence
specs/         Spec-Kit feature artifacts: spec, plan, research, data model, tasks, quickstart
perf/          Load-baseline harness (seed, generator, runner) and recorded results
```

## 5. Initial setup

From a clean clone. Run every command from the repository root.

```bash
# 1. Python virtual environment + orchestrator dependencies
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e "orchestrator[dev]"

# 2. Console dependencies
cd console && npm install && cd ..

# 3. Java dependencies and build (see §3 for the Linux JAVA_HOME form)
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
mvn -f shortener/pom.xml -B package -DskipTests

# 4. Agent sandbox images — REQUIRED before run_tests works.
#    A provisioning step on purpose: the runtime can only *check* for an image, never build one.
ops/sandbox/build-images.sh all
```

Databases and migrations are §6.

## 6. Start PostgreSQL

Two databases. Docker is the supported local path.

### 6a. Local development databases (fastest)

> **Local-development-only credentials.** The passwords below are disposable and must never be
> used anywhere real. Production provisioning is §6b.

**Reset first.** `docker run --name` does **not** replace an existing container — it fails with a
name conflict, and if that error scrolls past you keep running the *old* container. A container
left from an earlier development session can carry different credentials and stale data than the
commands below specify, and every check in this section will still pass while the application
cannot authenticate (this exact failure was found during T103 validation).

```bash
docker rm -f shortener-local orchestrator-local 2>/dev/null || true
```

Safe here because both containers are disposable and created with `--rm`. **Do not run a
force-remove against any database you care about** — this step is for the throwaway quickstart
containers only.

```bash
docker run -d --rm --name shortener-local -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=shortener -e POSTGRES_PASSWORD=local-dev-only \
  -e POSTGRES_DB=shortener_db postgres:16-alpine

docker run -d --rm --name orchestrator-local -p 127.0.0.1:55433:5432 \
  -e POSTGRES_USER=orchestrator -e POSTGRES_PASSWORD=local-dev-only \
  -e POSTGRES_DB=orchestrator_db postgres:16-alpine
```

| Container | Port | Database |
|---|---|---|
| `shortener-local` | 55432 | `shortener_db` |
| `orchestrator-local` | 55433 | `orchestrator_db` |

No script depends on these container names. `perf/run_baseline.sh` creates and destroys its
**own** container named `shortener-perf` on port **55432** — stop `shortener-local` first, or the
port collides (§21).

### 6b. Four-role provisioning (the production-shaped path, HUMAN task T006/T007)

Creates `shortener_owner`, `shortener_app`, `orchestrator_owner`, `orchestrator_app` with
cross-database CONNECT revoked and audit immutability enforced by privilege. Passwords are read
from the environment and passed base64 over **stdin**, never as command-line arguments.

```bash
# Connect as a superuser via standard libpq variables (PGHOST/PGPORT/PGUSER/PGPASSWORD)
SHORTENER_OWNER_PW=... SHORTENER_APP_PW=... \
ORCH_OWNER_PW=...      ORCH_APP_PW=...      \
  ops/db/provision.sh cluster      # roles, databases, isolation, default privileges

# ... apply migrations as the *_owner roles (see below) ...

ops/db/provision.sh grants         # runtime grants; needs no passwords
```

`ops/db/provision.sh` documents an accepted operational risk: `CREATE ROLE ... PASSWORD` transmits
plaintext to the server, so run it with `log_statement` not set to `all`/`ddl`. See
[docs/security/security-review.md](docs/security/security-review.md) §5.4.

### Migrations

**Shortener** — Flyway runs automatically at application startup (`spring.flyway.enabled: true`),
applying `V1__baseline.sql` and `V2__short_links.sql`. No separate command is needed.

**Orchestrator** — apply the six SQL migrations explicitly:

```bash
ORCHESTRATOR_DB_URL="postgresql+psycopg://orchestrator:local-dev-only@127.0.0.1:55433/orchestrator_db" \
.venv/bin/python -c "
import sys, os; sys.path.insert(0, 'orchestrator')
from src.store.repository import make_engine, apply_migrations
print('applied:', apply_migrations(make_engine(os.environ['ORCHESTRATOR_DB_URL'])))
"
```

### Verify both databases are healthy

**Step 1 — wait for the servers to accept connections.** Deterministic, rather than running
`pg_isready` once and hoping the container has finished initialising:

```bash
until docker exec shortener-local    pg_isready -U shortener    >/dev/null 2>&1; do sleep 1; done
until docker exec orchestrator-local pg_isready -U orchestrator >/dev/null 2>&1; do sleep 1; done
echo "both servers accepting connections"
```

**Step 2 — prove the documented credentials actually work from the host.**

> `pg_isready` and a `psql` run *inside* the container prove the **server is up**. They do **not**
> prove password authentication: the official image's `pg_hba.conf` uses `trust` for in-container
> loopback, so an in-container `psql` succeeds whatever the password is. The application connects
> from the **host**, over TCP, with a password — so that is the path the quickstart must verify.

This uses the project virtualenv, so a host `psql` client stays optional (§3):

```bash
.venv/bin/python -c "
from sqlalchemy import create_engine, text
for name, dsn in [
    ('orchestrator', 'postgresql+psycopg://orchestrator:local-dev-only@127.0.0.1:55433/orchestrator_db'),
    ('shortener',    'postgresql+psycopg://shortener:local-dev-only@127.0.0.1:55432/shortener_db'),
]:
    with create_engine(dsn).begin() as c:
        c.execute(text('select 1'))
    print(name, 'credentials OK')
"
```

Expected: `orchestrator credentials OK` then `shortener credentials OK`. It **fails loudly** on a
wrong password — `FATAL: password authentication failed` — which is the whole point. The
orchestrator DSN here is character-for-character the one §8 starts the service with.

**Step 3 — schema.**

```bash
docker exec shortener-local psql -U shortener -d shortener_db \
  -c "\dt"      # expect short_link, redirect_event (after the shortener has started once)
docker exec orchestrator-local psql -U orchestrator -d orchestrator_db \
  -c "\dt"      # expect 15 tables including audit_event, task_node, approval_request
```

## 7. Run the URL shortener

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
SHORTENER_DB_URL="jdbc:postgresql://localhost:55432/shortener_db" \
SHORTENER_DB_USER=shortener \
SHORTENER_DB_PASSWORD=local-dev-only \
  mvn -f shortener/pom.xml spring-boot:run
```

Listens on **:8080**. Health: `http://localhost:8080/actuator/health` → `{"status":"UP"}`
(only `health` and `info` are exposed).

**`X-Client-Id`** identifies the creating client and scopes ownership. It is required on create,
revoke and analytics; a missing header returns **401**, and a different client returns **403**.
It is *not* authentication — see §20.

```bash
# Health
curl -s http://localhost:8080/actuator/health

# Create
curl -s -X POST http://localhost:8080/v1/links \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: demo-client" \
  -d '{"destination":"https://www.google.com"}'
# → {"code":"an91nwy","destination":"https://www.google.com","created_at":"..."}

# Resolve — do NOT follow, so you can see the 302 and its headers
curl -s -D - -o /dev/null http://localhost:8080/an91nwy
# → HTTP/1.1 302 · Location: https://www.google.com
#   Cache-Control: no-store, no-cache, must-revalidate · Pragma: no-cache · Expires: 0

# Analytics (owner only)
curl -s -H "X-Client-Id: demo-client" http://localhost:8080/v1/links/an91nwy/analytics
# → {"code":"an91nwy","total_redirects":1,"first_redirect_at":"...","last_redirect_at":"..."}

# Revoke (owner only) — afterwards, resolve returns 410 {"error":"revoked"}
curl -s -X POST -H "X-Client-Id: demo-client" http://localhost:8080/v1/links/an91nwy/revoke
```

Replace `an91nwy` with the code returned by your own create call.

## 8. Run the orchestrator

```bash
ORCHESTRATOR_DB_URL="postgresql+psycopg://orchestrator:local-dev-only@127.0.0.1:55433/orchestrator_db" \
ORCHESTRATOR_APPROVERS="human:lead" \
  .venv/bin/python -m uvicorn src.api.app:app --app-dir orchestrator --host 127.0.0.1 --port 8000
```

Listens on **:8000**.

**Liveness is not readiness — check both.**

| Endpoint | Proves | Does **not** prove |
|---|---|---|
| `GET /health` → `{"status":"up","service":"orchestrator"}` | The process is **live** and serving HTTP | Anything about the database. It touches no database and returns 200 even when every data endpoint is failing |
| `GET /v1/runs` → `[]` with **HTTP 200** | The application is **ready**: the DSN is correct, the credentials authenticate, and the schema is present | — |

**Do not declare the orchestrator ready on `/health` alone.** During T103 validation a process with
an unreachable database returned `/health` 200 while every data endpoint returned 500; `/v1/runs`
is what catches that.

| Variable | Required | Purpose |
|---|---|---|
| `ORCHESTRATOR_DB_URL` | yes | SQLAlchemy DSN. The egress allow-list derives the permitted database host from this, so the guard and the application cannot disagree |
| `ORCHESTRATOR_APPROVERS` | no (default `human:lead`) | Comma-separated human actor ids holding the approver role. **Any id beginning `agent:` is filtered out and can never approve** |
| `ANTHROPIC_BASE_URL` | no (default `https://api.anthropic.com`) | The single permitted external endpoint |
| `ANTHROPIC_API_KEY` | only for live agent dispatch | Not needed to run the API, the console, or any test in §12 |
| `ORCHESTRATOR_DB_HOST` | no | Legacy override; the DSN is used when unset |

An egress allow-list is installed **at import time**, before any router or connection pool exists:
the configured Claude host, the database host, and loopback are permitted; everything else raises
`EgressDenied`.

**If Docker or a sandbox image is unavailable**, `run_tests` raises `SandboxUnavailable`, the task
takes the **safe-stop** path with state preserved and the reason audited, and
`SAFE_STOP_SANDBOX_UNAVAILABLE` is recorded. It **never** falls back to running tests on the host.
Every other orchestration function works without a Docker daemon.

> **`X-Actor-Id` is demo identity, not production authentication.** It stands in for an
> authenticated session and any caller may assert any value. *Authorization* is real — roles come
> from the server-side directory, ownership is enforced, and no agent identity can approve — but
> *authentication* is not implemented. Do not expose this service on a shared network. See §20.

## 9. Run the React console

```bash
cd console && npm run dev
```

Serves **:5173**. `vite.config.ts` proxies **`/v1`** and **`/health`** to
`http://127.0.0.1:8000`, so the client uses relative URLs and no hostname is compiled into
production logic. **The orchestrator must be running**, or API calls fail — visibly, with an
`ApiClientError` naming the path, status and content type, rather than a blank screen.

With no run selected (`http://localhost:5173/` with no `?run=` parameter) the console renders
**"No workflow runs yet"** with both tabs present, and issues **no API request at all**. Open a
specific run with `http://localhost:5173/?run=<run_id>&actor=human:lead`.

## 10. Full local startup order

```bash
# 1. Databases
docker run -d --rm --name shortener-local -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=shortener -e POSTGRES_PASSWORD=local-dev-only \
  -e POSTGRES_DB=shortener_db postgres:16-alpine
docker run -d --rm --name orchestrator-local -p 127.0.0.1:55433:5432 \
  -e POSTGRES_USER=orchestrator -e POSTGRES_PASSWORD=local-dev-only \
  -e POSTGRES_DB=orchestrator_db postgres:16-alpine
until docker exec shortener-local pg_isready -U shortener >/dev/null 2>&1; do sleep 1; done
until docker exec orchestrator-local pg_isready -U orchestrator >/dev/null 2>&1; do sleep 1; done

# 2. Migrations (shortener migrates itself via Flyway at startup)
ORCHESTRATOR_DB_URL="postgresql+psycopg://orchestrator:local-dev-only@127.0.0.1:55433/orchestrator_db" \
.venv/bin/python -c "
import sys, os; sys.path.insert(0, 'orchestrator')
from src.store.repository import make_engine, apply_migrations
print('applied:', apply_migrations(make_engine(os.environ['ORCHESTRATOR_DB_URL'])))
"

# 3. Sandbox images (needed for run_tests and the sandbox tests)
ops/sandbox/build-images.sh all

# 4. Shortener  — new terminal
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
SHORTENER_DB_URL="jdbc:postgresql://localhost:55432/shortener_db" \
SHORTENER_DB_USER=shortener SHORTENER_DB_PASSWORD=local-dev-only \
  mvn -f shortener/pom.xml spring-boot:run

# 5. Orchestrator — new terminal
ORCHESTRATOR_DB_URL="postgresql+psycopg://orchestrator:local-dev-only@127.0.0.1:55433/orchestrator_db" \
ORCHESTRATOR_APPROVERS="human:lead" \
  .venv/bin/python -m uvicorn src.api.app:app --app-dir orchestrator --host 127.0.0.1 --port 8000

# 6. Console — new terminal
cd console && npm run dev

# 7. Verify
curl -s http://localhost:8080/actuator/health
curl -s http://127.0.0.1:8000/health
curl -s -o /dev/null -w "console: %{http_code}\n" http://localhost:5173/
```

## 11. Quick verification

```bash
# Services
curl -s http://localhost:8080/actuator/health                       # {"status":"UP"}
curl -s http://127.0.0.1:8000/health                                # {"status":"up",...}
curl -s -o /dev/null -w "console: %{http_code}\n" http://localhost:5173/   # 200
curl -s http://127.0.0.1:8000/v1/runs                               # [] on a fresh system — READINESS, not just liveness

# Unknown-run negative control: the detail endpoint must distinguish a missing run
curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8000/v1/runs/no-such-run
# → HTTP 404 · {"error":"not_found","message":"unknown run no-such-run"}

# Databases
docker exec shortener-local    pg_isready -U shortener
docker exec orchestrator-local pg_isready -U orchestrator

# End-to-end create + resolve, with header assertions and a 404 control
ops/smoke/t022-path-check.sh
```

`ops/smoke/t022-path-check.sh` creates a link, asserts the 302 and all four redirect headers,
follows the redirect, and requires an unissued code to return 404. It exits non-zero on failure.
It is a **technical pre-flight, not the SC-001 usability observation** (§12).

## 12. How to run tests

### Java shortener tests

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 21)

mvn -f shortener/pom.xml test -Dtest='**/unit/*Test'       # unit — 27 tests
mvn -f shortener/pom.xml test -Dtest='**/contract/*Test'   # contract + OpenAPI parity — 44 tests
mvn -f shortener/pom.xml verify                            # integration + failure paths (Testcontainers)
```

The contract layer regenerates the OpenAPI document from the running application and fails if it
drifts from the approved contract or the committed artifact.

### Python orchestrator lint and tests

**Lint is a CI gate — run it, not just the tests.**

```bash
.venv/bin/python -m ruff check orchestrator     # CI runs the equivalent: ruff check orchestrator
```

Expected: `All checks passed!`

> **This was a real verification gap, found by CI rather than locally.** `ruff` is declared in
> `orchestrator[dev]`, but if the virtualenv was created without that extra installed, the command
> fails with `No module named ruff` — and every local verification pass silently skipped the lint
> gate that CI enforces, while the test layers all reported green. Install the dev extra (§5) and
> confirm `ruff --version` works before treating a local run as complete. This is a
> **verification-process** finding about how the checks were run; it does not affect the T102,
> T103 or T104 decisions, which stand as recorded.

```bash
.venv/bin/python -m pytest orchestrator/tests -q                                    # everything
.venv/bin/python -m pytest orchestrator/tests -q -m unit
.venv/bin/python -m pytest orchestrator/tests -q -m "workflow and not integration"
.venv/bin/python -m pytest orchestrator/tests -q -m integration    # real PostgreSQL via Testcontainers
.venv/bin/python -m pytest orchestrator/tests -q -m failure        # failure/resilience — 157 tests
.venv/bin/python -m pytest orchestrator/tests -q -m contract       # OpenAPI + traceability consistency
```

**Known gap, stated rather than hidden:** the `unit` marker currently selects one test, and that
test is an endpoint test filed under `tests/integration/`. The orchestrator's logic is covered at
the workflow and failure layers; the missing thing is the layer Principle IV names separately.
Recorded in [docs/traceability/requirements-traceability.md](docs/traceability/requirements-traceability.md) §6.2.

### React console tests

```bash
cd console
npx vitest run          # 49 tests
npx tsc -b --force      # typecheck — expect "No errors found"
```

### Traceability checks

```bash
.venv/bin/python -m pytest orchestrator/tests/contract/test_traceability_matrix.py -q
```

Expected: **11 passed**, against a matrix summarising

```
79 total requirements
77 COVERED
 2 DEFERRED_APPROVED
 0 GAP
```

The check fails the build if a requirement disappears from the matrix, a cited task id stops
existing, a new GAP appears, or a deferred capability is implemented without the register being
updated.

### Sandbox and security verification

```bash
.venv/bin/python -m pytest orchestrator/tests/failure/test_capability_boundary.py -q          # 14 — four tools, nothing more
.venv/bin/python -m pytest orchestrator/tests/failure/test_sandbox_escape.py -q               # 15 — real containers
.venv/bin/python -m pytest orchestrator/tests/failure/test_integration_sandbox_topology.py -q # 8  — internal network
.venv/bin/python -m pytest orchestrator/tests/failure/test_egress_boundary.py -q              # 14 — real DNS/connect denials
.venv/bin/python -m pytest orchestrator/tests/failure/test_fail_closed_real.py -q             # 5  — real unreachable daemon
.venv/bin/python -m pytest orchestrator/tests/failure/test_audit_secret_safety.py -q          # 5
.venv/bin/python -m pytest orchestrator/tests/failure/test_approval_integrity.py -q           # 9
```

The sandbox and topology suites require Docker and the images from §5.

### Performance test

```bash
./perf/run_baseline.sh
```

**Prerequisites:** Docker, Java 21, and the project virtualenv at `.venv`. The script creates its
own PostgreSQL container named `shortener-perf` on port **55432**, builds the jar, starts the
application, seeds **100,000** links, runs a warm-up, then two 120-second profiles at **100
redirects/sec** — nominal, and a hot-link skew putting 70% of traffic on 5 links. Stop
`shortener-local` first if it holds port 55432.

Current baseline: **100.0 rps sustained, p95 ≈ 6.8 ms against a 150 ms budget, p99 ≈ 11 ms against
400 ms, zero errors across 24,000 redirects.** Full method, per-profile figures and limitations:
[perf/baseline-2026-08-20.md](perf/baseline-2026-08-20.md).

### HUMAN-only validation (not automated)

Three tasks are human judgement and are **not** covered by any command above: the security review
(T102), the quickstart scenario run (T103), and the Constitution gate re-evaluation (T104). All
three are currently **open**. The SC-001 usability observation (T022) is complete and recorded in
[specs/001-agentic-url-shortener/baseline.md](specs/001-agentic-url-shortener/baseline.md).

## 13. Three demo scenarios

> **Read this first.** The orchestrator API is deliberately **nine reads and two writes** — decide
> an approval, answer a clarification. **There is no run-creation endpoint**, and no CLI that
> submits a requirement. Runs are constructed programmatically, so the executable form of each
> scenario is its test suite; the REST endpoints below are how you *inspect* a run that exists.
> Nothing here invents a command the repository does not have. The narrative walkthrough is
> [specs/001-agentic-url-shortener/quickstart.md](specs/001-agentic-url-shortener/quickstart.md)
> scenarios 4–6.

### Scenario A — Greenfield

Requirement interpretation → DAG creation → gates → concurrent execution → validation.

```bash
.venv/bin/python -m pytest orchestrator/tests/workflow/test_interpretation.py \
  orchestrator/tests/workflow/test_graph_validity.py \
  orchestrator/tests/workflow/test_gates.py \
  orchestrator/tests/workflow/test_parallel_sync.py \
  orchestrator/tests/workflow/test_resume.py -v
```

28 tests. What each stage demonstrates:

| Stage | Assertion |
|---|---|
| Interpretation | `test_decomposition_refused_before_interpretation` — a written interpretation exists **before** any task |
| | `test_task_without_requirement_reference_is_refused` — no task without a requirement (FR-035) |
| DAG creation | `test_direct_cycle_is_rejected_before_execution`, `test_longer_cycle_is_rejected` |
| Gates | `test_entry_gate_blocks_stage_from_starting`, `test_exit_gate_blocks_stage_from_completing`, `test_passing_evaluations_are_recorded_too` |
| Execution | `test_independent_tasks_execute_concurrently`, `test_sync_node_waits_for_every_inbound_branch` |
| Validation / resume | `test_resume_does_not_re_execute_completed_work`, `test_every_transition_is_persisted` |

Inspect a run that exists (`RUN_ID` from `GET /v1/runs`):

```bash
curl -s http://127.0.0.1:8000/v1/runs
curl -s http://127.0.0.1:8000/v1/runs/$RUN_ID          # state + metrics + replans
curl -s http://127.0.0.1:8000/v1/runs/$RUN_ID/graph    # nodes, edges, per-node state, staleness
curl -s http://127.0.0.1:8000/v1/runs/$RUN_ID/gates    # every evaluation, pass or fail
curl -s http://127.0.0.1:8000/v1/runs/$RUN_ID/decisions
curl -s http://127.0.0.1:8000/v1/runs/$RUN_ID/audit
# Bidirectional traceability. Exactly one of requirement / change / run is required.
curl -s "http://127.0.0.1:8000/v1/trace?requirement=FR-001"   # forward: requirement → tasks, changes, tests
curl -s "http://127.0.0.1:8000/v1/trace?change=$CHANGE_ID"    # reverse: change → originating requirement
curl -s "http://127.0.0.1:8000/v1/trace?run=$RUN_ID"          # changes with no originating requirement
```

**Final summary:** the run's own metrics (`GET /v1/runs/$RUN_ID`) carry success rate, retries,
rollbacks, MTTR and end-to-end latency, with **`null` meaning unknown and `0` meaning measured
zero** — the console renders those differently on purpose.

### Scenario B — Brownfield / change

```bash
.venv/bin/python -m pytest orchestrator/tests/workflow/test_selective_replan.py -v
```

18 tests:

| Concern | Assertion |
|---|---|
| Change request | `test_change_request_is_persisted_and_linked_to_the_prior_run` |
| Impact analysis | `test_one_change_invalidates_only_its_dependency_closure` |
| Selective replanning | `test_the_whole_dag_is_not_rebuilt`, `test_replacements_are_created_only_for_stale_work` |
| Superseded tasks | `test_replacement_links_to_what_it_supersedes_and_prior_results_stay_queryable` |
| Preserved work | `test_unaffected_successful_nodes_remain_succeeded`, `test_repeated_replanning_does_not_duplicate_unaffected_work` |
| Approval on architecture scope | `test_a_new_component_halts_for_approval_and_implements_nothing`, `test_rejected_architecture_approval_keeps_the_prior_architecture` |
| Mode safety | `test_execution_mode_is_recalculated_but_never_silently_escalated` |

Stale nodes keep `SUCCEEDED` **and** their result — staleness is a flag, not an erasure — so
"what did we previously conclude, and why are we redoing it" stays answerable. The optimisation
ladder is asserted too: `test_default_choice_is_the_cheapest_rung_not_redis`.

### Scenario C — Ambiguous requirement

The supported ambiguous example is **"make links smarter"** — the qualifier is recognised by
`orchestrator/src/engine/ambiguity.py`, which maps `smarter` to the `scope` category. Note the
discrimination: *"make links smarter: add an optional expiry of up to 90 days"* is **not** flagged,
because it says what to build.

```bash
.venv/bin/python -m pytest orchestrator/tests/workflow/test_ambiguity_halt.py -v
```

22 tests:

| Concern | Assertion |
|---|---|
| Ambiguity detected | `test_the_scenario_requirement_is_detected_as_ambiguous`, `test_questions_are_specific_rather_than_a_general_complaint` |
| No work performed | `test_ambiguous_requirement_halts_and_creates_no_tasks`, `test_the_bounded_coding_agent_is_never_dispatched_while_unresolved` |
| Clarification persisted | `test_clarification_questions_are_persisted_against_the_requirement` |
| `WAITING_FOR_HUMAN` | `test_run_is_waiting_for_human`, `test_requirement_is_marked_awaiting_clarification` |
| Answer submitted | `test_answer_is_persisted_before_the_run_resumes`, `test_answer_carries_actor_timestamp_requirement_and_lineage` |
| Run resumes | `test_resume_re_interprets_using_the_clarification` |
| Bounded safe-stop | `test_clarification_rounds_are_bounded_and_end_in_safe_stop` |
| No drift while waiting | `test_resume_without_an_answer_leaves_the_run_waiting`, `test_restart_resumes_from_persisted_state_alone` |

Against a live waiting run, the pending question and the answer submission use the two write
endpoints that exist:

```bash
curl -s http://127.0.0.1:8000/v1/runs/$RUN_ID/pending
curl -s -X POST http://127.0.0.1:8000/v1/runs/$RUN_ID/clarifications/$REQUEST_ID \
  -H "Content-Type: application/json" -H "X-Actor-Id: human:lead" \
  -d '{"answer":"Add an optional expiry of up to 90 days."}'
```

## 14. Human approval flow

1. **Approval request.** A checkpoint-crossing tool call raises `CheckpointCrossing` **before**
   anything is applied. An `approval_request` row is written and the run parks in
   `WAITING_FOR_HUMAN`. Nothing has been mutated.
2. **Action fingerprint.** The request carries `action_fingerprint` — SHA-256 over canonical JSON
   of the request detail — so an approval authorises **one action**, not a standing permission.
3. **Server-side approver role.** Identity comes from `X-Actor-Id`; **roles come from
   `ORCHESTRATOR_APPROVERS`**, never from the request. A client asserting `X-Actor-Roles` is
   ignored.
4. **No agent self-approval.** Ids beginning `agent:` are filtered out of the role directory, so an
   agent identity can never hold the approver role.
5. **Scope widening requires explicit approval.** Out-of-scope work halts and surfaces for a
   decision rather than being absorbed; a rejected scope request widens nothing.

```bash
# What needs a human
curl -s http://127.0.0.1:8000/v1/runs/$RUN_ID/pending

# Approve — rationale is mandatory
curl -s -X POST http://127.0.0.1:8000/v1/runs/$RUN_ID/approvals/$REQUEST_ID \
  -H "Content-Type: application/json" -H "X-Actor-Id: human:lead" \
  -d '{"decision":"approved","rationale":"Interface matches the approved contract."}'

# Reject — authorises nothing; the artifact stays byte-identical
curl -s -X POST http://127.0.0.1:8000/v1/runs/$RUN_ID/approvals/$REQUEST_ID \
  -H "Content-Type: application/json" -H "X-Actor-Id: human:lead" \
  -d '{"decision":"rejected","rationale":"Introduces a component outside approved scope."}'

# An agent identity is refused and audited
curl -s -X POST http://127.0.0.1:8000/v1/runs/$RUN_ID/approvals/$REQUEST_ID \
  -H "Content-Type: application/json" -H "X-Actor-Id: agent:t1" \
  -d '{"decision":"approved","rationale":"self"}'      # → forbidden
```

Behaviour proof without a live run:
`.venv/bin/python -m pytest orchestrator/tests/failure/test_approval_integrity.py -v`

## 15. Failure and safe-stop behaviour

| Condition | How to demonstrate | Result |
|---|---|---|
| **Docker unavailable** | `DOCKER_HOST=unix:///nonexistent/docker.sock .venv/bin/python -m pytest orchestrator/tests/failure/test_fail_closed_real.py -v` | `SandboxUnavailable`; safe-stop; state preserved; `SAFE_STOP_SANDBOX_UNAVAILABLE` audited |
| **Sandbox image missing** | same suite — `test_real_absent_image_raises_sandbox_unavailable` | `SandboxUnavailable` naming `build-images.sh`; the runtime does **not** build or pull |
| **Bounded timeout** | `.venv/bin/python -m pytest orchestrator/tests/failure/test_bounds.py -v -k timeout` | Per-attempt timeout; the operation cannot widen its own budget |
| **Retry exhaustion** | same suite — `test_max_attempts_exhausted_raises_and_stops`, `test_no_attempt_occurs_after_exhaustion` | Declared fallback fires; an undeclared fallback cannot be invented |
| **Rejected approval** | `.venv/bin/python -m pytest orchestrator/tests/failure/test_halt_before_apply.py -v` | `test_rejected_approval_leaves_the_artifact_unchanged` |
| **Unresolved ambiguity** | `.venv/bin/python -m pytest orchestrator/tests/workflow/test_ambiguity_halt.py -v -k bounded` | Clarification rounds bounded, ending in safe-stop — never an open loop |
| **Waiting costs nothing** | `.venv/bin/python -m pytest orchestrator/tests/failure/test_waiting_quiescence.py -v` | No thread, timer or worker; never expires into autonomous execution |

**The system never falls back to unsandboxed execution.** A missing boundary is a stop, not a
degradation: `test_real_unreachable_daemon_does_not_fall_back_to_host_execution` intercepts
`subprocess.run` and asserts **no non-`docker` process was started**.

## 16. Security model

- **Database isolation** — two databases, four roles, no credential spanning both. Cross-database
  CONNECT is revoked: `shortener_app` cannot reach `orchestrator_db` and vice versa (verified live).
- **Append-only audit** — `orchestrator_app` holds `INSERT` + `SELECT` on `audit_event` and nothing
  else. `UPDATE`, `DELETE` and `TRUNCATE` are refused by the database; `AuditRepository` exposing no
  mutation method is the second layer.
- **Four model-visible tools** — `read_file`, `write_file`, `run_tests`, `report`. No shell, git,
  package-install, HTTP or MCP tool; `web_search`/`web_fetch`/`code_execution` are never declared.
  `run_tests` accepts an **enum**, never a command.
- **Sandbox** — ephemeral container, `--network none`, non-root, `cap-drop ALL`,
  `no-new-privileges`, cpu/memory/pids/wall-clock caps, no Docker socket, no host home or secrets,
  disposable copy of one surface; the authoritative repository is never mounted.
- **Egress controls** — allow-list covering the Claude endpoint, the configured database host and
  loopback; everything else raises `EgressDenied`. Credential-bearing URLs are redacted, and audit
  payloads are rejected on both key names and value shapes.
- **No server-side URL fetch** — destinations are validated syntactically, stored and returned;
  never dereferenced. A test watches a real HTTP listener record **zero** requests across creation,
  resolution, analytics, revocation and rejection. **SSRF is therefore not introduced by the
  shortener path**, and Constitution gate V-a is correctly N-A.
- **Known demo limitations** — see §20.

Evidence: [docs/security/egress-verification.md](docs/security/egress-verification.md) ·
[docs/security/security-review.md](docs/security/security-review.md) *(evidence package; the human
sign-off section is deliberately blank — T102 is open)*

## 17. Performance and the Redis decision

Target: **100 redirects/sec** against **100,000 stored links**, p95 < 150 ms, p99 < 400 ms.

Measured (two profiles, 120 s each, open-loop, redirects not followed, synchronous analytics not
bypassed): **100.0 rps, p95 6.82 ms nominal / 6.62 ms under hot-link skew, p99 10.84 / 11.64 ms,
zero errors.** Roughly 22× headroom on p95 and 34× on p99.

The database stayed well within budget: ~0.24 ms of database time in a ~5.4 ms request, active
connections peaking at 2 of 16, and hot-row counter contention measurable but immaterial (counter
`UPDATE` mean 0.072 → 0.088 ms).

**Redis was intentionally not introduced.** Research R13 permits a cache tier only on a *measured*
budget breach attributed to datastore access, with cheaper rungs exhausted first. The first
condition is not met, so the ladder never begins. Adding Redis would have bought a few milliseconds
of a 150 ms allowance while adding cache invalidation on revoke and expiry, a second datastore to
provision and secure, and a new failure mode on the path NFR-002 exists to protect.

This is enforced, not merely documented: `CACHE_TIER` sits in `NEW_COMPONENT_OPTIONS`, so proposing
it halts for human architecture approval and implements nothing. **Redis remains reconsiderable
through brownfield selective replanning** if future measurements clear all three R13 conditions —
that is exactly the judgement Scenario B exercises.

Full evidence: [perf/baseline-2026-08-20.md](perf/baseline-2026-08-20.md)

## 18. Traceability

[docs/traceability/requirements-traceability.md](docs/traceability/requirements-traceability.md)

| | |
|---|---|
| Total requirements | **79** (FR 49 · NFR 9 · SC 21) |
| `COVERED` | **77** |
| `DEFERRED_APPROVED` | **2** |
| `GAP` | **0** |

The two approved deferrals:

- **Custom aliases (FR-005)** — designed with contract and conflict semantics specified; not built.
- **Creation rate limiting (FR-015)** — designed; R8 fixes the policy at 60/min, burst 10.

Both are registered in `specs/001-agentic-url-shortener/tasks.md` § Deferred Capabilities, and
their absence is verified by probing the API rather than trusting the register: the OpenAPI
document contains no alias or rate-limit surface, and their error identifiers are declared but
unreachable.

## 19. Architecture documentation

- [docs/HLD.md](docs/HLD.md) — problem, context, components, control/data-plane separation,
  autonomy and approval models, sandbox boundary, lineage, replanning, resilience, observability,
  performance, trade-offs, why Redis was excluded, deployment assumptions, limitations.
- [docs/LLD.md](docs/LLD.md) — module layout, state machine, `TaskNode` immutability,
  `OperationPolicy`, fingerprint flow, clarification lifecycle, audit linkage, rollback and replan
  algorithms, sandbox lifecycle, egress internals, schema, endpoint inventory, redirect sequence,
  error model, test-layer mapping, and public-interface rationale.

## 20. Known limitations

- **`X-Actor-Id` / `X-Client-Id` are demo identity, not production authentication.** Any caller may
  assert any value. Authorization is real; authentication is not implemented. **Do not expose these
  services on a shared network.** This is the most material limitation.
- **Collection inspection endpoints do not distinguish an unknown parent run.**
  `GET /v1/runs/{id}` returns **404** for a run that does not exist, but
  `/graph`, `/gates`, `/audit`, `/decisions` and `/pending` return **200 with empty results** —
  so "this run has zero gates" and "this run does not exist" look identical on those five paths.
  No current requirement mandates 404 there, and the console always requests a run it has already
  listed. **Consistent parent-existence validation is recommended for a future API revision.**
  This is API semantic debt, not a security defect and not a blocker: recorded during T103
  validation and deliberately left unchanged, because altering it would reshape an already
  published, CI-gated public contract. Use `GET /v1/runs/{id}` when you need to know whether a run
  exists.
- **The Python egress guard is defense in depth**, covering the orchestrator process only. It
  cannot bound a child process.
- **A raw `socket.socket().connect()` bypasses the guard by construction** — it wraps
  `getaddrinfo` and `create_connection`, which is every HTTP client, but cannot wrap the syscall
  those wrappers call. **Container networking (`--network none`, `--internal`) is the real boundary
  for untrusted agent-authored code.** Asserted by a test so the property stays recorded.
- **Host thread timeout limitation.** `BoundedExecutor` uses a worker thread and
  `shutdown(wait=False)`; Python cannot forcibly kill a thread, so the timeout guarantees the
  *caller* stops waiting and the fallback fires, not that the runaway work stops. Untrusted work
  runs in a container whose wall-clock limit is enforced by `docker kill`, which is a real kill.
- **Local environment assumptions** — single region, single instance per service, no TLS, no
  secret manager, no identity provider, no HA. Ports 8080 / 8000 / 5173 / 55432 / 55433 assumed
  free.
- **Approved deferrals** — custom aliases, rate limiting, paginated event history, event retention
  sweep, separate console screens for gates/replan/metrics/audit.
- **Other** — the orchestrator `unit` test layer is effectively empty (§12); the performance
  baseline is single-host; SC-001 rests on one observation; ten tasks cite research decisions
  instead of requirement ids. All recorded in the traceability audit.

## 21. Troubleshooting

**Java 21 not selected** — the default JDK may be Java 8.
```bash
java -version                                   # what is actually on PATH
export JAVA_HOME=$(/usr/libexec/java_home -v 21)   # macOS
$JAVA_HOME/bin/java -version                    # expect 21.x
```

**Docker unavailable** — sandbox tests skip and `run_tests` safe-stops.
```bash
docker info --format '{{.ServerVersion}}'       # non-zero exit means no daemon
```

**Sandbox image missing** — `SandboxUnavailable` naming the provisioning step.
```bash
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep agent-sandbox
ops/sandbox/build-images.sh all
```

**PostgreSQL not running**
```bash
docker ps --format '{{.Names}}\t{{.Ports}}'
docker exec shortener-local pg_isready -U shortener
docker logs --tail 20 shortener-local
```

**Password authentication failed for user "orchestrator" / "shortener"** — a container created
earlier with different credentials is still running, so the connection string in §6a does not match
it. Symptom: services start and `/health` returns 200, but every data endpoint returns **500**.
```bash
docker inspect orchestrator-local --format '{{range .Config.Env}}{{println .}}{{end}}' | grep POSTGRES_USER
docker logs --tail 5 orchestrator-local
```
Either supply the password the container was actually created with, or recreate it from §6a:
`docker rm -f orchestrator-local` and re-run the `docker run` command. Recreating discards that
container's data.

**Wrong database port** — the shortener defaults to 5432, the containers above publish 55432 /
55433. Symptom: connection refused at startup. Set `SHORTENER_DB_URL` and `ORCHESTRATOR_DB_URL`
explicitly, and check what is actually published with `docker ps`.

**Vite proxy / API routing problem** — symptom historically was
`TypeError: gates.filter is not a function`, caused by the dev server answering `/v1` with
`index.html` at HTTP 200. The proxy now lives in `console/vite.config.ts`; the client also raises
`ApiClientError` instead of fabricating an object.
```bash
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:5173/v1/runs
# expect: 200 application/json
```
Read the result as follows:

| Result | Meaning |
|---|---|
| `200 application/json` | Working |
| `200 text/html` | The proxy is **not** active — restart `npm run dev` after any `vite.config.ts` change |
| `500 text/plain` | The proxy **is** active and forwarding, but the orchestrator is failing — check its terminal or `curl -s http://127.0.0.1:8000/v1/runs` directly |
| `502` / connection refused | The orchestrator is not running |

**Orchestrator DB URL / host configuration** — the egress allow-list derives the permitted database
host from `ORCHESTRATOR_DB_URL`. A mismatch shows up as `EgressDenied`.
```bash
ORCHESTRATOR_DB_URL="postgresql+psycopg://orchestrator:local-dev-only@127.0.0.1:55433/orchestrator_db" \
.venv/bin/python -c "
import sys; sys.path.insert(0,'orchestrator')
from src.agent.config import build_policy
print('allow-list:', sorted(build_policy().allowed_hosts))"
```

**Port already in use**
```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN     # also 8000, 5173, 55432, 55433
```
`perf/run_baseline.sh` needs port **55432** for its own `shortener-perf` container — stop
`shortener-local` first: `docker rm -f shortener-local`.

## 22. Reviewer fast path

Five to ten minutes, assuming §5 setup is done.

```bash
# 1. Start databases and both services (see §10 for the full sequence)

# 2. Health
curl -s http://localhost:8080/actuator/health && curl -s http://127.0.0.1:8000/health

# 3. Create and resolve a link
ops/smoke/t022-path-check.sh

# 4. Run one orchestrator scenario — ambiguity is the safety demonstration
.venv/bin/python -m pytest orchestrator/tests/workflow/test_ambiguity_halt.py -q

# 5. Traceability — expect 11 passed against 79 / 77 / 2 / 0
.venv/bin/python -m pytest orchestrator/tests/contract/test_traceability_matrix.py -q

# 6. Security and performance evidence
.venv/bin/python -m pytest orchestrator/tests/failure/test_capability_boundary.py -q
open docs/security/egress-verification.md perf/baseline-2026-08-20.md   # or your reader of choice
```

If you read only two documents, read [docs/HLD.md](docs/HLD.md) §7–§9 (controlled autonomy, human
approval, sandbox boundary) and
[docs/traceability/requirements-traceability.md](docs/traceability/requirements-traceability.md) §1.

## 23. Clean shutdown

```bash
# Java shortener, orchestrator, console — Ctrl-C in each terminal, or:
lsof -ti:8080 | xargs kill      # shortener
lsof -ti:8000 | xargs kill      # orchestrator
lsof -ti:5173 | xargs kill      # console

# Database containers (started with --rm, so removal is enough)
docker rm -f shortener-local orchestrator-local

# Sandbox resources — run_tests cleans up after itself on every path, including failure.
# Only if a run was interrupted mid-execution:
docker ps -a --format '{{.Names}}' | grep -E '^agent-(sbx|pg)-' | xargs -r docker rm -f
docker network ls --format '{{.Name}}' | grep -E '^agent-net-'  | xargs -r docker network rm

# Perf harness, if ./perf/run_baseline.sh was interrupted
docker rm -f shortener-perf
```

Sandbox **images** are provisioned artifacts; leave them unless you want a clean rebuild
(`docker image rm agent-sandbox/orchestrator:latest agent-sandbox/shortener:latest agent-sandbox/console:latest`).

## 24. Evidence index

| Artifact | Path |
|---|---|
| High-level design | [docs/HLD.md](docs/HLD.md) |
| Low-level design | [docs/LLD.md](docs/LLD.md) |
| Requirements traceability | [docs/traceability/requirements-traceability.md](docs/traceability/requirements-traceability.md) |
| Performance baseline | [perf/baseline-2026-08-20.md](perf/baseline-2026-08-20.md) |
| Egress verification | [docs/security/egress-verification.md](docs/security/egress-verification.md) |
| Security review *(evidence package; sign-off blank, T102 open)* | [docs/security/security-review.md](docs/security/security-review.md) |
| T022 time-to-first-success baseline | [specs/001-agentic-url-shortener/baseline.md](specs/001-agentic-url-shortener/baseline.md) |
| Generated OpenAPI — shortener | [docs/contracts/shortener-openapi.json](docs/contracts/shortener-openapi.json) |
| Generated OpenAPI — orchestrator | [docs/contracts/orchestrator-openapi.json](docs/contracts/orchestrator-openapi.json) |
| Written API contracts | [specs/001-agentic-url-shortener/contracts/](specs/001-agentic-url-shortener/contracts/) |
| Quickstart scenarios | [specs/001-agentic-url-shortener/quickstart.md](specs/001-agentic-url-shortener/quickstart.md) |
| Specification | [specs/001-agentic-url-shortener/spec.md](specs/001-agentic-url-shortener/spec.md) |
| Implementation plan | [specs/001-agentic-url-shortener/plan.md](specs/001-agentic-url-shortener/plan.md) |
| Task list | [specs/001-agentic-url-shortener/tasks.md](specs/001-agentic-url-shortener/tasks.md) |
| Constitution | [.specify/memory/constitution.md](.specify/memory/constitution.md) |
