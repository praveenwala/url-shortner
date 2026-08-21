---

description: "Task list template for feature implementation"
---

# Tasks: Agentic URL Shortener

**Input**: Design documents from `/specs/001-agentic-url-shortener/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Architecture**: Approved 2026-08-18 (plan.md § Architecture Approval Record; Gate II cleared). Java 21 + Spring Boot 3 shortener · Python 3.13 orchestrator · React + TypeScript console · PostgreSQL, two databases with separate credentials · no Redis, no broker, single persistence model. **Unchanged by this rescope.**

**Delivery budget**: 2–3 days. This list is scoped to that budget and prioritises the **orchestration system over URL-shortener feature breadth**. Requirements are unchanged; several are deferred at the *implementation* level and listed in [Deferred Capabilities](#deferred-capabilities) below.

**Tests**: REQUIRED per Constitution Principle IV. Critical business behavior, orchestration behavior, failure paths, and contract boundaries have test tasks, written before implementation and observed failing first.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [MODE] [P?] [Story] Description (REQ)`

- **[MODE]**: `[AGENT]` or `[HUMAN]` — execution mode, declared here at planning time and **not escalatable during execution** (FR-042). This is the same rule the orchestrator enforces on its own task nodes, applied to its own construction.
- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- **(REQ)**: Requirement IDs this task satisfies, carried as a trailing parenthetical so the strict checklist format stays valid — MANDATORY per Constitution Principle III. A task with no requirement is out of scope (FR-035)
- Include exact file paths in descriptions

### What makes a task HUMAN

A task is `[HUMAN]` when it establishes or verifies a boundary that an agent must not be able to move. Six categories:

1. **Privilege and provisioning** — database roles, grants, audit immutability
2. **Security boundary** — process egress restriction
3. **The agent capability model itself** — its tools, its allow-list, its approval hook, and the tests that prove them. *An agent must not implement, test, or approve its own confinement* (FR-041, FR-042, Principle II)
4. **Approval machinery** — approver role verification and identity separation (FR-029, FR-050)
5. **Governance enforcement** — scope boundaries and governance-artifact protection (FR-039, FR-040)
6. **Release readiness and self-governance** — security review, quickstart validation, Constitution compliance (Principle XII)

## Path Conventions

- **Shortener (Java)**: `shortener/src/main/java/.../shortener/`, tests in `shortener/src/test/java/`
- **Orchestrator (Python)**: `orchestrator/src/`, tests in `orchestrator/tests/`
- **Console (TypeScript)**: `console/src/`, tests in `console/tests/`
- **Operational scripts**: `ops/` — provisioning and database roles. Not runtime code, not imported by any service
- **No shared runtime module**: the services share contracts only (`contracts/`), never implementation

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and toolchain for three surfaces

- [X] T001 [AGENT] Create the three-surface repository structure — `shortener/`, `orchestrator/`, `console/`, plus `ops/` for operational scripts. No shared runtime module: the services share contracts only (plan § Structure Decision)
- [X] T002 [AGENT] [P] Initialize the Java 21 + Spring Boot 3 project in `shortener/` with Web MVC, Bean Validation, Spring Data JPA, Actuator, springdoc-openapi (R4)
- [X] T003 [AGENT] [P] Initialize the Python 3.13 project in `orchestrator/pyproject.toml` with FastAPI and the `anthropic` SDK (R1, R6)
- [X] T004 [AGENT] [P] Initialize the React + TypeScript console in `console/` with Vite, building to static assets — **done in checkpoint 2f (T075)**, which un-deferred it (R5)
- [X] T005 [AGENT] Configure consolidated formatting, linting, and the four-layer CI targets across all three surfaces in `.github/workflows/ci.yml` (IV, R10, X)
- [X] T006 [HUMAN] Provision PostgreSQL with two databases and two roles — `shortener_db`, `orchestrator_db`, neither able to read the other — in `ops/db/provision.sql` (R3, NFR-006)
- [X] T007 [HUMAN] Grant the orchestrator role `INSERT` and `SELECT` but **not** `UPDATE` or `DELETE` on `audit_event` in `ops/db/provision.sql` (FR-036, approval record item 6)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T008 [AGENT] [P] Implement each service's own correlation and trace identifier helper — no cross-language import — against the field names fixed in `contracts/correlation.md`, in `shortener/src/main/java/.../shortener/trace/` and `orchestrator/src/trace/` (VIII, NFR-007)
- [X] T009 [AGENT] [P] Define the stable error identifier set and response shapes in `shortener/src/main/java/.../shortener/web/errors/` and `orchestrator/src/api/errors.py` (FR-009, FR-016, SC-004)
- [X] T010 [AGENT] [P] Build the Testcontainers PostgreSQL harnesses in `shortener/src/test/java/support/` and `orchestrator/tests/support/` (R3, R10)
- [X] T011 [AGENT] Implement the Spring Boot skeleton with Actuator health and the FastAPI skeleton with health in `shortener/src/main/java/.../shortener/` and `orchestrator/src/api/app.py` (NFR-007)
- [X] T012 [AGENT] Implement the console shell and typed API client in `console/src/api/` — **done in checkpoint 2f (T075)** (FR-045, FR-048)
- [X] T013 [AGENT] Configure migration tooling and baselines for both databases in `shortener/src/main/resources/db/migration/` and `orchestrator/src/store/migrations/` (NFR-003)
- [X] T014 [AGENT] Configure separate connection pools for the redirect path and analytics serving in `shortener/src/main/resources/application.yaml` (NFR-002, R14)
- [X] T015 [HUMAN] Restrict orchestrator process egress to the configured Claude endpoint only, in `orchestrator/src/agent/config.py` — **implemented by T056**, which is the same work; T015 predates the 2d rewrite and is retained so its Phase 2 position is not silently dropped (R6, SC-017)

> **T006 / T007 completion note (HUMAN tasks, executed 2026-08-18 under explicit owner
> authorisation).** `ops/db/provision.sh`, `01-provision-cluster.sql`, and
> `02-apply-runtime-grants.sql` were written, reviewed, and executed end to end against a
> disposable PostgreSQL 16 container with throwaway credentials. Verified behaviourally, not
> by reading grants: all four roles authenticate (base64 round-trip correct); re-running the
> cluster step creates nothing (idempotent); every cross-database connection is denied in
> both directions while each role reaches its own database; `orchestrator_app` can INSERT and
> SELECT `audit_event` but is denied UPDATE, DELETE, and TRUNCATE; an attempt by
> `orchestrator_app` to GRANT itself UPDATE granted nothing, because `audit_event` is owned by
> `orchestrator_owner`. **Scope limit:** this verified the scripts, not any real environment.
> Provisioning a target database remains a separate operator act with real credentials, under
> the operational risk recorded in plan.md § Recorded risks.

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Shorten a link and follow it (Priority: P1) 🎯 MVP

**Goal**: A client turns a valid HTTP/HTTPS destination into a short link; anyone following it lands on the destination; the creator can set an expiry and revoke. **Core only** — custom aliases and rate limiting are deferred.

**Independent Test**: Submit a valid destination, receive a short link, follow it in a browser, land on the destination. Submit invalid and non-HTTP(S) destinations and receive distinct refusals with no link created. Requires none of the orchestration system.

### Tests for User Story 1 (REQUIRED - Principle IV) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T016 [AGENT] [P] [US1] Contract test for link creation and for the distinct outcomes of unknown, expired, malformed, and revoked resolution in `shortener/src/test/java/contract/LinkContractTest.java` (FR-001, FR-003, FR-009, FR-016, SC-004)
- [X] T017 [AGENT] [P] [US1] Contract test asserting the redirect is temporary and explicitly non-cacheable in `shortener/src/test/java/contract/RedirectContractTest.java` (FR-007, clarification 2026-08-18)
- [X] T018 [AGENT] [P] [US1] Integration test rejecting the non-HTTP(S) scheme corpus with no link stored in `shortener/src/test/java/integration/SchemeRejectionTest.java` (FR-002, FR-010, SC-003)
- [X] T019 [AGENT] [P] [US1] Concurrency test proving no code collision overwrites an existing link in `shortener/src/test/java/integration/CodeUniquenessTest.java` (FR-004, SC-005, R12)
- [X] T020 [AGENT] [P] [US1] Failure test asserting a redirect whose count cannot be durably recorded fails rather than serving uncounted in `shortener/src/test/java/failure/RedirectRecordingFailureTest.java` (R14, approval record item 7)
- [X] T021 [AGENT] [P] [US1] Unit tests for code generator alphabet, length, and bounded collision retry in `shortener/src/test/java/unit/CodeGeneratorTest.java` (FR-004, R12, VII)
- [X] T022 [HUMAN] [US1] Time-to-first-success validation — an untrained person creates and follows a short link, timed, recorded in `specs/001-agentic-url-shortener/baseline.md` (SC-001)

> **T022 completed 2026-08-20 — HUMAN-EXECUTED.** The session was performed and timed by a human
> participant; the elapsed time is human-provided and was not measured, inferred, or recomputed
> by an agent, and no part of the participant's task was performed by an agent. Result recorded
> in `specs/001-agentic-url-shortener/baseline.md`: untrained participant, no assistance,
> **approximately 0.5 seconds** against SC-001's 30-second budget — **PASS**.
>
> Agent contribution was verification only, before and after: environment pre-flight
> (`ops/smoke/t022-path-check.sh`) and six independent technical checks on the participant's own
> link `Ii2L2v2` — short_link exists, destination matches, `redirect_count >= 1`,
> `first_redirect_at` populated, matching `redirect_event` (id 12), and a live resolve returning
> `302` to `https://www.google.com`.

### Implementation for User Story 1

- [X] T023 [AGENT] [P] [US1] Write the `short_link` and `redirect_event` migrations — simple indexed event table, no partitioning — in `shortener/src/main/resources/db/migration/` (FR-004, FR-008, FR-012, FR-013)
- [X] T024 [AGENT] [US1] Implement the `ShortLink` and `RedirectEvent` JPA entities in `shortener/src/main/java/.../shortener/domain/` (FR-004, FR-007, FR-013)
- [X] T025 [AGENT] [P] [US1] Implement destination validation, canonicalisation, and the reserved path registry in `shortener/src/main/java/.../shortener/validation/` (FR-002, FR-003, FR-006, FR-011, NFR-006)
- [X] T026 [AGENT] [US1] Implement the short code generator — random, 7 characters, 62-symbol alphabet, bounded collision retry — in `shortener/src/main/java/.../shortener/domain/CodeGenerator.java` (FR-004, R12, VII)
- [X] T027 [AGENT] [US1] Implement create, resolve, and revoke with expiry and revocation checks in `shortener/src/main/java/.../shortener/service/LinkService.java` (FR-001, FR-007, FR-008, FR-009, FR-012)
- [X] T028 [AGENT] [US1] Implement the redirect transaction — counter and event committed before the response is issued — in `shortener/src/main/java/.../shortener/service/RedirectService.java` (FR-013, R14, SC-006)
- [X] T029 [AGENT] [US1] Implement the `/v1` create and revoke controllers, the unversioned redirect controller, and the exception handler mapping every failure to a stable error identifier, in `shortener/src/main/java/.../shortener/web/` (FR-007, FR-009, FR-010, FR-012, FR-016, SC-004, R9)
- [X] T030 [AGENT] [US1] Publish the generated OpenAPI contract and verify it matches the approved contract — **complete for both services**: `docs/contracts/orchestrator-openapi.json` vs `contracts/orchestrator-api.md` (17 Python contract tests) and `docs/contracts/shortener-openapi.json` vs `contracts/shortener-api.md` (24 Java contract tests). Both artifacts are generated from the running application, reconciled in the contracts, and gated in CI (FR-016, FR-017, R4)

> **US1 core completed 2026-08-19.** Create, resolve, revoke, and the analytics summary, on
> Java 21 + Spring Boot 3 + Spring Data JPA + PostgreSQL. Tests were written before each
> implementation and observed failing first. 58 Java tests pass.
>
> Three real defects surfaced by running them: the scheme allow-list was evaluated *after* URI
> parsing, so `data:text/html,<script>` was reported as malformed rather than as a rejected
> scheme — the security control was being masked by a syntax error; a missing `X-Client-Id`
> returned 403 where 401 is correct; and an unrecordable redirect escaped as an unhandled 500
> instead of the controlled `redirect_not_recorded` the R14 decision implies.
>
> **Deferred as agreed**: custom aliases (FR-005), rate limiting (FR-015), paginated event
> history (FR-014 history half), and the retention sweep (FR-013 retention half). No Redis, no
> partitioning.

**Checkpoint**: User Story 1 fully functional and testable independently — quickstart scenarios 1 and 3

---

## Phase 4: User Story 2 - Greenfield delivery through the orchestrated workflow (Priority: P1)

**Goal**: An engineering lead submits a requirement; the system records its interpretation, decomposes into a dependency graph, executes with parallelism and synchronisation, halts at gates and approvals, and produces a complete audit trail.

**Independent Test**: Submit the greenfield requirement, inspect the graph before execution, watch parallel branches converge, approve the architecture checkpoint, then trace any produced change back to its requirement and forward to its validating test.

**Six checkpoints, each independently testable and demonstrable.** If time runs short, 2a–2c alone demonstrate stateful orchestration without agent authorship.

### Checkpoint 2a — Persistence + state model

**Demonstrable when**: schema migrates, states are enumerated, audit has no update path.

- [X] T031 [AGENT] [P] [US2] Integration test asserting migrations apply, states are enumerable, and the store exposes no audit update or delete path in `orchestrator/tests/integration/test_store_shape.py` (FR-025, FR-036, NFR-004)
- [X] T032 [AGENT] [US2] Write all orchestrator migrations — requirement, workflow_run, task_node, task_dependency, gate, approval_record, decision_record, change_record, audit_event, replan_event, trace_link — in `orchestrator/src/store/migrations/` (FR-020, FR-025, FR-027, FR-033, FR-036, data-model)
- [X] T033 [AGENT] [P] [US2] Implement the run and node state enumerations in `orchestrator/src/models/states.py` (R7, FR-025)
- [X] T034 [AGENT] [US2] Implement the store layer with no update or delete path for audit records in `orchestrator/src/store/repository.py` (FR-036, NFR-004)

### Checkpoint 2b — Requirement interpretation + DAG planning

**Demonstrable when**: a requirement becomes a recorded interpretation and an acyclic graph; a cycle is rejected.

- [X] T035 [AGENT] [P] [US2] Workflow test asserting a written interpretation is recorded before any implementation task exists in `orchestrator/tests/workflow/test_interpretation.py` (FR-020)
- [X] T036 [AGENT] [P] [US2] Workflow test asserting the plan is a DAG and a cycle is rejected before execution in `orchestrator/tests/workflow/test_graph_validity.py` (FR-022)
- [X] T037 [AGENT] [US2] Implement requirement intake and interpretation recording in `orchestrator/src/engine/intake.py` (FR-020)
- [X] T038 [AGENT] [US2] Implement decomposition into task nodes with mandatory requirement references, declared execution mode, and **declared inputs/outputs frozen at planning time** in `orchestrator/src/engine/decompose.py` (FR-021, FR-035, FR-041, FR-042)
- [X] T039 [AGENT] [US2] Implement DAG construction with cycle rejection and readiness computation in `orchestrator/src/graph/builder.py` (FR-022, FR-023)

> **T038 reopened and corrected, 2026-08-18.** The original implementation left
> `TaskNode.inputs`/`outputs` unpopulated, which would have forced checkpoint 2d to derive an
> agent's write allow-list from the whole surface rather than from the approved task — weaker
> than FR-041 requires. Decomposition now declares explicit repo-relative artifact paths inside
> the task's own surface; an agent-authored non-sync task with no outputs is refused; the
> declared sets are tuples on a node that rejects reassignment of planning-time fields, so they
> cannot be widened during execution; widening goes through `replan_outputs`, which returns a
> replacement node rather than mutating the original; and the sets round-trip through
> PostgreSQL (migration `002_declared_io.sql`). 26 new tests in
> `tests/workflow/test_declared_io.py` plus one persistence assertion in `test_resume.py`.
> Checkpoint 2b behaviour is otherwise unchanged — the four existing test helpers gained a
> default output, and no existing assertion was altered. This is a correction under FR-021 and
> FR-041, not an architecture change: Gate II is untouched.

### Checkpoint 2c — Execution + synchronization + gates

**Demonstrable when**: parallel branches run and converge, gates block, an interrupted run resumes.

- [X] T040 [AGENT] [P] [US2] Workflow test asserting independent tasks run concurrently and a sync node waits for every inbound branch in `orchestrator/tests/workflow/test_parallel_sync.py` (FR-023, FR-024, SC-008)
- [X] T041 [AGENT] [P] [US2] Workflow test asserting entry and exit gates block and record outcome and reason in `orchestrator/tests/workflow/test_gates.py` (FR-026)
- [X] T042 [AGENT] [P] [US2] Workflow test asserting an interrupted run resumes with no completed task re-executed and no lost transition in `orchestrator/tests/workflow/test_resume.py` (FR-025, SC-012)
- [X] T043 [AGENT] [US2] Implement the concurrent scheduler and synchronisation node semantics in `orchestrator/src/engine/scheduler.py` and `orchestrator/src/graph/sync.py` (FR-023, FR-024)
- [X] T044 [AGENT] [US2] Implement gate definition, evaluation, and recording in `orchestrator/src/engine/gates.py` (FR-026)
- [X] T045 [AGENT] [US2] Implement state persistence at every transition and resume-from-persisted-state in `orchestrator/src/engine/state.py` (FR-025, NFR-003, SC-012)

### Checkpoint 2d — Bounded agent runtime (HUMAN-approved boundary)

**Demonstrable when**: an agent completes a bounded task, cannot reach outside its allow-list,
and code it writes cannot escape the ephemeral test sandbox.

> **Capability-boundary decisions are HUMAN-APPROVED (2026-08-18).** The requirement owner made
> the security decisions in research R15 — ephemeral Docker test sandbox, never mounting the
> authoritative repository, per-invocation disposable surface copy, network/socket/secret/
> privilege/resource restrictions, integration-test network isolation, exactly four
> model-visible tools, and the socket allow-list demoted to defense in depth. **Implementation
> below is agent-assisted under that approved boundary.** No architecture approval was recorded
> by an agent; Gate II is untouched.

- [X] T046 [HUMAN] [P] [US2] Failure test asserting an agent write outside its declared-output allow-list is refused and that the tool set exposes no shell, network, package-install, or git capability, with server-side web search, web fetch, and code execution not declared, in `orchestrator/tests/failure/test_capability_boundary.py` (FR-041, R6, SC-017)
- [X] T047 [HUMAN] [P] [US2] Failure test asserting execution mode cannot be escalated from human-executed to agent-authored mid-run, and declared outputs cannot be widened, in `orchestrator/tests/failure/test_mode_escalation.py` (FR-041, FR-042, SC-019)
- [X] T048 [HUMAN] [P] [US2] Sandbox escape tests asserting agent-authored test code cannot reach arbitrary internet hosts, cannot access `ops/`, `.git/`, host secrets, or the Docker socket, cannot persist mutations to the authoritative repository, and is terminated safely by timeout and resource limits, in `orchestrator/tests/failure/test_sandbox_escape.py` (R15, FR-041, SC-017)
- [X] T049 [HUMAN] [US2] Implement the ephemeral Docker test sandbox — disposable task-scoped surface copy, authoritative repository never mounted, `--network none`, no Docker socket, no host home, no secrets, non-privileged, `no-new-privileges`, bounded CPU/memory/PIDs/output/wall-clock — in `orchestrator/src/agent/sandbox.py` (R15, FR-030, NFR-009)
- [X] T050 [HUMAN] [US2] Implement the fixed per-surface test commands and the integration-test path — orchestrator provisions a disposable PostgreSQL externally on a dedicated isolated network, test runner gets no Docker socket, credentials test-only — in `orchestrator/src/agent/testrunner.py` (R15, R10)
- [X] T051 [HUMAN] [US2] Implement the four bounded tools and per-task read/write allow-list derivation from `TaskNode.declared_outputs` in `orchestrator/src/agent/tools.py` and `orchestrator/src/agent/allowlist.py` (FR-041, R6)
- [X] T052 [HUMAN] [US2] Implement prior-state capture and atomic write producing revertible `ChangeRecord` values in `orchestrator/src/agent/changes.py` (FR-032, FR-044)
- [X] T053 [HUMAN] [US2] Implement the Claude client with adaptive thinking, per-task-class effort, and a declared task budget, with server-side tools deliberately not declared, in `orchestrator/src/agent/client.py` (FR-030, NFR-009, R6)
- [X] T054 [HUMAN] [US2] Implement the per-turn approval hook that halts a checkpoint-crossing tool call before it is applied in `orchestrator/src/agent/approval_hook.py` (FR-043, R6)
- [X] T055 [HUMAN] [US2] Implement bounded-task precondition checking, tier A/B/C violation handling, bounded retry and safe-stop in `orchestrator/src/agent/dispatch.py` (FR-041, FR-042, FR-030, FR-031)
- [X] T056 [HUMAN] [US2] Implement the orchestrator process egress allow-list and socket guard — **defense in depth for this process only, not the sandbox** — in `orchestrator/src/agent/config.py` (T015, R6, SC-017)

- [X] T057 [HUMAN] [US2] Record the Gate II addendum scoping Docker to the `run_tests` capability, and make `run_tests` fail closed with a typed `SandboxUnavailable` error onto the safe-stop path — never skipping, never executing on the host — in `orchestrator/src/agent/sandbox.py`, `testrunner.py`, `dispatch.py` (R15, FR-031, plan § Gate II addendum)
- [X] T058 [HUMAN] [US2] Add minimal, non-root, secret-free per-surface sandbox images for Python, Java/Maven, and Node in `ops/sandbox/Dockerfile.orchestrator`, `Dockerfile.shortener`, `Dockerfile.console` (R15)
- [X] T059 [HUMAN] [US2] Make sandbox image build a provisioning step the runtime cannot trigger, in `ops/sandbox/build-images.sh` (R15, FR-041)
- [X] T060 [HUMAN] [P] [US2] End-to-end `run_tests` tests executing the orchestrator and shortener suites inside the real sandbox images, and fail-closed tests for a missing daemon or image, in `orchestrator/tests/failure/test_run_tests_end_to_end.py` and `test_sandbox_unavailable.py` (R15, IV)

> **Checkpoint 2d completed 2026-08-18, operational gaps closed the same day. Capability-boundary decisions HUMAN-APPROVED;
> implementation agent-assisted under that approved boundary.** The requirement owner made the
> security decisions recorded in research R15 — ephemeral Docker test sandbox, authoritative
> repository never mounted, per-invocation disposable surface copy, network/socket/secret/
> privilege/resource restrictions, integration-test network isolation, exactly four
> model-visible tools, and the socket allow-list demoted to defense in depth for the
> orchestrator process. An agent implemented against that boundary; **no architecture approval
> was recorded by an agent, and Gate II is untouched.**
>
> Verified by 59 failure-path tests, 15 of which run real containers: agent-authored test code
> cannot reach the internet or resolve DNS, cannot see `ops/`, `.git/`, host secrets, the Docker
> socket, or another surface; mutations to the disposable copy leave the authoritative
> repository byte-identical; the copy is discarded on every path; containers run non-root with
> `NoNewPrivs`; and wall-clock, memory, and output bounds terminate execution safely.
>
> **Operational closure (T057–T060).** Docker is scoped by a HUMAN-approved Gate II addendum to
> the `run_tests` capability alone; every other orchestration function runs without a daemon.
> An unavailable daemon or missing image now fails closed with a typed `SandboxUnavailable`,
> safe-stops the task, preserves state, and audits `SAFE_STOP_SANDBOX_UNAVAILABLE` — it never
> skips and never runs on the host. Three minimal non-root images are provisioned by
> `ops/sandbox/build-images.sh`; the runtime can only *check* for an image, verified by an AST
> test asserting no `docker build`/`pull` exists in the runtime. End-to-end runs execute the
> real orchestrator (Python) and shortener (Java/Maven) suites inside those images, offline,
> leaving the authoritative repository byte-identical.

### Checkpoint 2e — Approvals + lineage + audit + governance guardrails

**Demonstrable when**: a checkpoint halts for a role-holding approver, out-of-scope work is refused, and the run is reconstructable from its audit trail.

- [X] T061 [HUMAN] [P] [US2] Workflow test asserting checkpoints halt for approval, no agent can self-approve, and an approval from an identity lacking the approver role is rejected and audited in `orchestrator/tests/workflow/test_approvals.py` (FR-029, FR-043, FR-050, SC-009)
- [X] T062 [HUMAN] [P] [US2] Failure test asserting work outside the approved scope of the run is blocked and surfaced for human decision, and that governance artifacts — constitution, approval policy, gate definitions — cannot be modified without explicit human approval, in `orchestrator/tests/failure/test_governance_guardrails.py` (FR-039, FR-040)
- [X] T063 [AGENT] [P] [US2] Workflow test asserting bidirectional traceability from requirement to tests and from change to requirement in `orchestrator/tests/workflow/test_traceability.py` (FR-034, FR-035, SC-007)
- [X] T064 [HUMAN] [US2] Implement the approval request and record flow with approver role verification and agent-identity exclusion in `orchestrator/src/engine/approvals.py` (FR-029, FR-050)
- [X] T065 [HUMAN] [US2] Implement scope-boundary enforcement and governance-artifact protection in `orchestrator/src/engine/guardrails.py` (FR-039, FR-040)
- [X] T066 [AGENT] [US2] Implement change record capture including prior artifact state before apply, and decision lineage recording, in `orchestrator/src/engine/changes.py` and `orchestrator/src/engine/decisions.py` (FR-027, FR-043, FR-044)
- [X] T067 [AGENT] [US2] Implement traceability link construction and bidirectional query in `orchestrator/src/audit/trace.py` (FR-034, FR-035)
- [X] T068 [AGENT] [US2] Implement append-only audit emission for every action, decision, gate, approval, retry, failure, rollback, replan, and transition in `orchestrator/src/audit/events.py` (FR-036, FR-038)

- [X] T069 [AGENT] [US2] Implement rollback linkage — persisted `ChangeRecord` with run/task reference and prior state, `rollback_event` linked to the change it reverses, failed rollback safe-stops and is audited — in `orchestrator/src/engine/rollback.py` and `orchestrator/src/store/repository.py` (FR-032, FR-044)
- [X] T070 [AGENT] [US2] Implement the approvals and lineage API surface — pending checkpoints, decide, merged decision lineage, audit trail, bidirectional trace — in `orchestrator/src/api/approvals_api.py` (FR-029, FR-027, FR-034, FR-036)

> **Checkpoint 2e completed 2026-08-18.** Approval integrity, halt-before-apply, decision
> lineage, append-only audit persistence, scope boundary (FR-039), governance protection
> (FR-040), rollback linkage, and the approvals/lineage API. Tests were written before each
> implementation and observed failing first.
>
> Verified by 41 new tests: an agent cannot self-approve and cannot even be *constructed*
> holding the approver role; a non-approver human is refused; an approval covers exactly the
> action it was requested for and nothing else; a rejected approval authorises nothing; a
> checkpoint-crossing write parks the run in `WAITING_FOR_HUMAN` with the artifact
> byte-identical; out-of-scope work halts and surfaces rather than widening the run's own
> scope; governance paths require an explicit approval per file; the runtime database role is
> refused `UPDATE`, `DELETE`, and `TRUNCATE` on `audit_event` by PostgreSQL itself; rollback
> links to the change it reverses and a failed rollback safe-stops and is audited; and
> requirement → task → change → test resolves in both directions.

### Checkpoint 2f — API + minimal console

**Demonstrable when**: a reviewer follows and acts on a live run from two console views.

- [X] T071 [AGENT] [P] [US2] Contract test asserting every field the console renders is present in an orchestrator API response in `console/tests/api-parity.test.tsx` (FR-048, R5)
- [X] T072 [AGENT] [US2] Implement the orchestrator `/v1` routes — requirement, run, graph, gates, pending, approvals, clarifications, decisions, audit, metrics, trace — in `orchestrator/src/api/routes.py` (FR-045, FR-048, contracts/orchestrator-api.md)
- [X] T073 [AGENT] [US2] Implement the console **Run view** — dependency graph with node state, gates, and audit timeline — in `console/src/views/RunView.tsx` (FR-045, FR-048, R5)
- [X] T074 [AGENT] [US2] Implement the console **Human action view** — pending approvals and clarification requests, with submission confirmed by re-reading the run rather than optimistic update — in `console/src/views/HumanActionView.tsx` (FR-045, FR-046, FR-048, SC-020, R5)

- [X] T075 [AGENT] [US2] Initialise the React + TypeScript console with Vite and Vitest, and implement the typed API client with no client-side store in `console/package.json` and `console/src/api/client.ts` (R5, FR-048)
- [X] T076 [AGENT] [US2] Implement clarification requests, human answers persisted before resume, and the server-side role directory in `orchestrator/src/engine/clarifications.py` and `orchestrator/src/api/deps.py` (FR-028, FR-046, FR-049, FR-050)

> **Checkpoint 2f completed 2026-08-18.** Orchestration API and a two-view console. Tests were
> written before each implementation and observed failing first.
>
> Verified by 17 API tests and 25 console tests: roles come from a server-side directory, so a
> client sending `X-Actor-Roles: approver` is still refused; an agent identity is never accepted
> as an approver; a stale already-decided request returns 409 rather than silently re-deciding;
> an approval authorises only its own fingerprint; a clarification answer is persisted before the
> run leaves `WAITING_FOR_HUMAN`, and the console exposes no transition call at all; a rejected
> decision leaves the item on screen because nothing was removed optimistically; a remount
> re-reads every value from the API. The DAG is laid out by dependency depth in ~40 lines — no
> graph framework was introduced.

**Checkpoint**: User Stories 1 AND 2 both work independently

---

## Phase 5: User Story 3 - Ambiguous requirement stops for human clarification (Priority: P2)

**Goal**: A deliberately unclear requirement produces no implementation and no code changes; the system records specific answerable questions and halts until a human answers.

**Independent Test**: Submit the ambiguous requirement, confirm zero implementation tasks and specific recorded questions with the run halted in `WAITING_FOR_HUMAN`, then answer and confirm planning resumes.

### Tests for User Story 3 (REQUIRED - Principle IV) ⚠️

- [X] T077 [AGENT] [P] [US3] Workflow test asserting an ambiguous requirement produces zero implementation tasks and zero code changes, with ambiguities recorded as specific answerable questions, in `orchestrator/tests/workflow/test_ambiguity_halt.py` (FR-028, SC-010)
- [X] T078 [AGENT] [P] [US3] Workflow test asserting `WAITING_FOR_HUMAN` survives process restart with its pending request intact in `orchestrator/tests/workflow/test_waiting_persistence.py` (FR-049, SC-021)
- [X] T079 [AGENT] [P] [US3] Failure test asserting no agent loop, retry timer, or polling cycle remains active while waiting, and the state never expires into autonomous execution, in `orchestrator/tests/failure/test_waiting_quiescence.py` (FR-049, SC-021)
- [X] T080 [AGENT] [P] [US3] Integration test asserting a clarification answer resumes planning and is recorded in decision lineage attributed to its human actor in `orchestrator/tests/integration/test_clarification_resume.py` (FR-028, FR-046)

### Implementation for User Story 3

- [X] T081 [AGENT] [US3] Implement ambiguity identification that halts when scope, security posture, or user-visible behaviour is undetermined in `orchestrator/src/engine/ambiguity.py` (FR-028)
- [X] T082 [AGENT] [US3] Implement the `WAITING_FOR_HUMAN` transition that quiesces all loops and timers for the run in `orchestrator/src/engine/waiting.py` (FR-049, NFR-009)
- [X] T083 [AGENT] [US3] Implement clarification request creation, answer recording, and resumption of planning in `orchestrator/src/engine/clarifications.py` (FR-028, FR-046)

> **US3 completed 2026-08-19.** Ambiguity detection halts before decomposition; the bounded
> coding agent is never dispatched while a requirement is unresolved. Tests were written first
> and observed failing.
>
> **The rule**: a requirement is materially ambiguous when it asks for a change in *quality*
> without saying what would count as achieving it — a vague qualifier ("smarter", "faster") or
> an open-ended verb ("improve", "modernise") combined with the *absence* of any concrete
> specification. The second half matters: "Make links smarter: add an optional expiry of up to
> 90 days" is not flagged, because it now says what to build. Flagging the adjective alone
> would fire on ordinary prose and train people to route around the gate.
>
> **Bounded**: clarification rounds stop at 3 and then safe-stop. Asking forever is its own
> failure mode (Principle VII).
>
> **Correction found by implementing it**: `SAFE_STOPPED` was unreachable from
> `WAITING_FOR_HUMAN`, so a run that exhausted its clarification budget had nowhere to go.
> Safe-stop is now reachable from every non-terminal state; recorded as an R7 correction.
>
> **Limitation, recorded not hidden**: the detector is a deterministic lexical heuristic, not a
> model. It misses ambiguity phrased without a listed word, and a number added to a vague
> sentence clears the concreteness check whether or not it is the relevant number. It is a
> testable floor under FR-028, not a substitute for judgement.

**Checkpoint**: The safety demonstration — quickstart scenario 5

---

## Phase 6: User Story 4 - Minimum brownfield path for selective replanning (Priority: P2)

**Goal**: The minimum needed to demonstrate selective replanning — blast radius from the dependency closure, staleness that preserves results, and bounded failure handling with rollback.

**Independent Test**: Change an upstream decision partway through a run and confirm the reported blast radius matches the dependency closure, only affected nodes are re-planned, and unaffected completed nodes retain their results.

**Depends on**: US1 (something to enhance) and US2 (the run machinery).

### Tests for User Story 4 (REQUIRED - Principle IV) ⚠️

- [X] T084 [AGENT] [P] [US4] Workflow test asserting the reported blast radius equals the graph's dependency closure and only affected nodes are re-planned in `orchestrator/tests/workflow/test_selective_replan.py` (FR-033, SC-011)
- [X] T085 [AGENT] [P] [US4] Failure test asserting rollback restores prior artifact state exactly and records the attempt and outcome in `orchestrator/tests/failure/test_rollback.py` (FR-032, FR-044, SC-018)
- [X] T086 [AGENT] [P] [US4] Failure test asserting timeout and retry exhaustion terminate in the declared fallback or a safe-stop, never an unbounded loop, in `orchestrator/tests/failure/test_bounded_operations.py` (FR-030, FR-031, SC-016)

### Implementation for User Story 4

- [X] T087 [AGENT] [US4] Implement blast radius computation from the dependency closure and staleness marking that preserves completed results in `orchestrator/src/graph/blast_radius.py` (FR-033, R7)
- [X] T088 [AGENT] [US4] Implement selective subgraph replanning with replan event recording, never defaulting to a full restart, in `orchestrator/src/engine/replan.py` (FR-033, FR-036, SC-011)
- [X] T089 [AGENT] [US4] Implement the rollback executor restoring prior artifact state from the change record in `orchestrator/src/engine/rollback.py` (FR-032, FR-044)
- [X] T090 [AGENT] [US4] Implement per-operation timeout, bounded retry with backoff, declared fallback, and safe-stop in `orchestrator/src/engine/bounds.py` (FR-030, FR-031, NFR-009)

> **US4 minimum brownfield completed 2026-08-19.** Selective replanning against the existing
> shortener run. Tests were written first and failed on import; the implementation then passed
> all 18 on its first run.
>
> **Only the closure moves.** One change to `redirect` marked `redirect` and `analytics` stale
> and left `validate`, `service`, and `revoke` `SUCCEEDED` and unstale. No node was deleted and
> the DAG was not rebuilt.
>
> **Staleness is a flag, not an erasure.** A stale node keeps `SUCCEEDED` and keeps its result;
> its replacement carries `supersedes` back to it, so "what did we previously conclude, and why
> are we redoing it" stays answerable. A second replan creates no duplicates.
>
> **The ladder chooses evidence over habit.** With no measurements it picks index/query/pool
> verification. With counter contention measured it picks batching — a bounded in-datastore
> change. Redis is reachable only when the budget is breached, query path and pooling are
> verified, batching has been attempted, the breach is attributed to datastore access, and a
> cache design preserving expiry/revocation/exact counts exists — and then it stops for a human
> with "optimise PostgreSQL first" preserved in the request. Rejection plans the fallback rather
> than stalling the run.
>
> **Not implemented here, deliberately**: T086/T090 per-operation timeout, bounded retry with
> backoff, and declared fallback as a standalone module. Bounded behaviour exists where it has
> been needed so far (dispatch violation budget and wall-clock ceiling, code-generation retry
> cap, clarification round cap), but the general per-task bounds module remains open.

> **T086/T090 completed 2026-08-20** — the generic bounded-execution requirement, closed with
> one small policy object rather than a new orchestration framework.
> `OperationPolicy(timeout_seconds, max_attempts, backoff_seconds, fallback)` is frozen and is
> **never handed to the operation**: the callable receives an attempt number and nothing else,
> so there is no reference through which it could widen its own budget. Attempts persist per
> attempt, so a process that dies mid-retry resumes with the budget it actually spent. Backoff
> is exponential but capped — doubling forever is unbounded retry wearing a hat. Fallbacks are
> `SAFE_STOP`, `WAIT_FOR_HUMAN`, or a named handler that must be registered *before* dispatch;
> an unregistered handler is rejected before the operation runs, so a fallback cannot be
> invented after a failure. No new schema: `task_node` already carried the budget columns.
>
> **A test caught a real defect**: the first implementation used `with ThreadPoolExecutor(...)`,
> whose `__exit__` joins the worker — so a 1-second timeout waited the operation's full 30
> seconds, defeating the bound it existed to enforce. Fixed by shutting the pool down without
> waiting. Suite runtime fell from 100s to 8s.
>
> **Overlap deliberately not consolidated**: the dispatcher's per-dispatch violation budget and
> wall-clock ceiling, the sandbox's container wall-clock limit, the code generator's collision
> retry cap, and the clarification round cap all bound different things and are tested in their
> own right. Rewriting them into this policy would mean changing working code for symmetry.

**Checkpoint**: Selective replanning demonstrable — quickstart scenario 6

---

## Phase 7: User Story 5 - Basic analytics summary (Priority: P3)

**Goal**: The creating client sees total redirects and first/most-recent timestamps. **Summary only** — paginated event history and the retention sweep are deferred.

**Independent Test**: Create a link, follow it several times, request the summary, and confirm the count and timestamps match exactly.

**Depends on**: US1.

- [X] T091 [AGENT] [P] [US5] Integration test asserting the summary reports total, first, and most recent redirect, and that a non-creating client is refused, in `shortener/src/test/java/integration/AnalyticsSummaryTest.java` (FR-014, SC-006)
- [X] T092 [AGENT] [US5] Implement the analytics summary with owner scoping in `shortener/src/main/java/.../shortener/service/AnalyticsService.java` (FR-014)
- [X] T093 [AGENT] [US5] Implement the `/v1` analytics summary controller on the analytics connection pool in `shortener/src/main/java/.../shortener/web/AnalyticsController.java` (FR-014, FR-016, NFR-002)

> **US5 verified 2026-08-20 — no production code change required.** The summary was
> implemented with US1 and already satisfied the approved scope: total successful redirects,
> first and latest redirect timestamps, owner-scoped access, refused resolutions uncounted.
>
> One claim was asserted but never proven, so two verification tests were added: **lifetime
> counters are independent of event retention** (deleting every `redirect_event` row leaves the
> summary reporting 4) and **first never moves while latest always does**. The counters are
> denormalised onto the link precisely so retention cannot alter them (FR-013) — that design
> now has a test behind it rather than a comment. No retention sweep, no pagination, no Redis.

**Checkpoint**: Analytics summary demonstrable — quickstart scenario 2 (summary portion)

---

## Phase 8: User Story 6 - Reliability metrics and audit, API-level (Priority: P3)

**Goal**: Metrics and audit retrieval available and correct through the API. Console presentation is limited to what the Run view already shows.

**Independent Test**: Execute several runs including a failure and a rollback, request the metrics, and confirm every value matches observed outcomes. Reconstruct a run from its audit trail alone.

**Depends on**: US2.

- [X] T094 [AGENT] [P] [US6] Test asserting metrics match independently observed run outcomes, with time in `WAITING_FOR_HUMAN` excluded from MTTR and latency and reported separately, in `orchestrator/tests/integration/test_metrics.py` (FR-037, SC-014, R11)
- [X] T095 [AGENT] [P] [US6] Test asserting a completed run is reconstructable from its audit trail alone and that the orchestrator role cannot `UPDATE` or `DELETE` audit records in `orchestrator/tests/integration/test_audit_reconstruction.py` (FR-036, NFR-004, SC-013)
- [X] T096 [AGENT] [P] [US6] Test asserting no secrets or personal data appear in audit records, logs, or metrics in `orchestrator/tests/integration/test_no_secrets.py` (FR-038, SC-015)
- [X] T097 [AGENT] [US6] Implement metric computation per the R11 definitions in `orchestrator/src/audit/metrics.py` (FR-037, FR-047, R11)

> **US6 completed 2026-08-20.** Reliability metrics computed from persisted audit and run
> rows in `orchestrator/src/audit/metrics.py`, served on the existing `GET /v1/runs/{id}` and
> rendered inside RunView. No new endpoint, no new screen, no Prometheus or Grafana.
>
> **Nothing is counted in memory**, so metrics survive restart by construction — a test kills
> the service and recomputes identical figures from the same rows.
>
> **`null` and `0` mean different things and are rendered differently.** A rate with no
> denominator is unknown, not zero: reporting "0% retries" for a run that executed nothing
> would be a lie a reviewer could act on. The API returns `null`; the console renders "—".
>
> **Human wait is excluded from MTTR and end-to-end latency and reported separately.** Folding
> it in would make both a measure of how fast someone answered their messages. A safe-stop
> counts as a failure to recover from, not a quiet ending.

**Checkpoint**: Reliability and audit demonstrable — quickstart scenario 7

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Verification and release readiness

- [X] T098 [AGENT] Build one reproducible load baseline at the NFR-005 operating point, recording uniform and hot-link observations, in `shortener/src/test/java/load/` and `specs/001-agentic-url-shortener/baseline.md` (NFR-001, NFR-005, SC-002, plan § Recorded risks)
> **T098 completed 2026-08-20.** `perf/run_baseline.sh` reproduces the measurement;
> `perf/baseline-2026-08-20.md` records environment, methodology, results and limitations; raw
> artifacts are in `perf/results/`. Both profiles **PASS**: 100 rps sustained, p95 6.82 ms
> (nominal) and 6.62 ms (hot skew) against a 150 ms budget, p99 10.84/11.64 ms against 400 ms,
> zero errors across 24,000 redirects. Hot-row contention is real but costs tens of microseconds
> at this load. **Redis remains unjustified** — R13's first condition, a measured breach, is not
> met. Nothing was optimised and no architecture decision was taken; Gate II is unchanged.

- [X] T099 [AGENT] Verify zero outbound requests to caller-supplied destinations across the corpus in `shortener/src/test/java/failure/EgressTest.java` (FR-018, SC-017)
> **T099 completed 2026-08-20.** Scope was widened by human direction beyond the recorded
> shortener-only wording, to real egress verification of the whole runtime boundary:
> `docs/security/egress-verification.md`. `shortener/.../failure/EgressTest.java` covers the
> recorded FR-018/SC-017 requirement (5 passed, including a control proving the listener records
> requests); four new orchestrator suites cover control-plane egress, integration-sandbox
> topology, real fail-closed behaviour, and audit secret safety (orchestrator failure layer:
> 157 passed).
>
> **Four real defects found and fixed**, each pinned by a regression test confirmed to fail when
> the fix is reverted: (1) the egress guard was never installed in the running application — the
> boundary was inert; (2) the allow-list read `ORCHESTRATOR_DB_HOST` while the application
> connects via `ORCHESTRATOR_DB_URL`; (3) `EgressDenied` echoed credentials embedded in a
> configuration URL; (4) the audit secret check inspected keys but not values. No change was made
> to the approved egress architecture and no network product was added.

- [X] T100 [AGENT] Produce the traceability audit in `specs/001-agentic-url-shortener/traceability.md`, classifying every requirement as exactly one of `COVERED` (task, change, and validating test in both directions), `DEFERRED_APPROVED` (citing plan.md § Delivery Scope and tasks.md § Deferred Capabilities — FR-005 and FR-015 only), or `GAP`. Any `GAP` is a failure condition (FR-034, FR-035, III, SC-007)

> **T100 closed 2026-08-20 as the final submission audit**, after T022, T102, T103 and T104 — held
> open deliberately so it closes against the released state rather than a mid-flight one.
> `docs/traceability/requirements-traceability.md` §8.
>
> **79 requirements · 77 COVERED · 2 DEFERRED_APPROVED (FR-005 custom aliases, FR-015 rate
> limiting) · 0 GAP.** Re-verified at close: 79 spec requirements against 79 matrix rows with none
> unclassified; 104/104 tasks complete; 26 HUMAN tasks all human-attributed; **zero** records of an
> agent approving anything; deferred capabilities absent from the published OpenAPI; no Redis in
> any manifest. Suites: orchestrator 280 (unit/workflow/failure/contract) + 176 (integration),
> console 49 + typecheck clean, shortener unit 27.
>
> **Four findings carried into submission, all visible in §8.3:** the ten `(REQ)`-less supporting
> tasks and the thin orchestrator `unit` layer (both ACCEPTED at T104, with explicit prohibitions
> on back-fitting requirement ids or manufacturing test counts); T102's conditions remaining in
> force for the local prototype only; and **one intermittent test failure observed once, whose
> identity was not captured before re-running** — four subsequent full runs were clean. Recorded as
> known intermittency of unknown identity rather than as a passing result.
- [X] T101 [AGENT] [P] Document public interfaces, retention behaviour, non-obvious decisions, and the deferred-capability register with re-entry cost, across all three surfaces in `docs/` (NFR-008, III, XI, X)

> **T101 completed 2026-08-20.** `docs/HLD.md` (problem, context, components, control/data-plane
> split, autonomy and approval models, sandbox boundary, lineage, replanning, resilience,
> observability, performance, trade-offs, why Redis was excluded, deployment assumptions,
> limitations) and `docs/LLD.md` (module layout, state machine, TaskNode immutability,
> OperationPolicy, fingerprint flow, clarification lifecycle, audit linkage, rollback and replan
> algorithms, sandbox lifecycle, egress, schema, endpoint inventory, redirect sequence, error
> model, test-layer mapping). `README.md` created: overview, architecture, run, test, the three
> demo scenarios, and links to every evidence artifact. 11 Mermaid diagrams.
>
> **NFR-008 closed.** LLD §17 documents rationale — why it exists, who calls it, why the boundary
> is shaped this way, why alternatives were rejected — for all six public interfaces: shortener
> REST API, orchestrator REST API, model-visible tool set, database/service boundaries, approval
> interface, console/API boundary. Traceability now **77 COVERED / 2 DEFERRED_APPROVED / 0 GAP**.
> Documentation only; no runtime behaviour changed and Gate II is untouched.
- [X] T102 [HUMAN] Run the security review — input validation, secret handling, least privilege, approver identity separation, agent capability boundary — recording findings in `specs/001-agentic-url-shortener/security-review.md` (NFR-006, FR-050, V)

> **T102 completed 2026-08-20 — HUMAN-REVIEWED, APPROVED WITH CONDITIONS.** The review decision was
> made by the human reviewer (Principal Engineer / Architecture Reviewer) and recorded in
> `docs/security/security-review.md` §7. **No agent made or influenced the decision**; an agent
> assembled the evidence package in §1–§6 only.
>
> **51 controls: 47 PASS, 4 ACCEPT-RISK, 0 FAIL.** The four accepted-risk controls are B7
> (`X-Actor-Id` is demo identity, not authentication), E7 (Python egress guard is defense-in-depth;
> the container is the untrusted-code boundary), G7 (thread timeout bounds the caller, not the
> runaway thread), and I6 (plaintext password at `CREATE ROLE`). All ten §5 risks accepted with the
> reviewer's stated basis recorded. **No new security defect was found.**
>
> **Six binding conditions** (§7.3), summarised: `X-Actor-Id` must never be described as production
> authentication; no shared or production deployment without real auth, TLS and console access
> control; the egress guard must continue to be described as defense-in-depth; rate limiting remains
> an approved deferral rather than a missing control; local credentials must not be presented as
> production practice; and no accepted risk may be silently removed from the documentation.
> A documentation change that weakens any condition invalidates the approval and requires a fresh
> human review.
- [X] T103 [HUMAN] Run the implemented scenarios in `specs/001-agentic-url-shortener/quickstart.md` end to end (quickstart.md)

> **T103 completed 2026-08-20 — HUMAN-EXECUTED.** Every PASS/FAIL/N/A was observed and decided by
> the human reviewer; an agent presented the checklist, extracted commands verbatim from
> `README.md`, diagnosed reported failures, and made documentation edits under direction. **No
> agent executed a validation step on the reviewer's behalf.** Record:
> `docs/validation/quickstart-validation.md`.
>
> **T103 did not pass on the first attempt — it exposed environment and documentation weaknesses,
> which were corrected and then revalidated cleanly.** Two invalidated attempts: (1) stale database
> containers carrying non-README credentials, where `/health` returned 200 while every DB-backed
> endpoint returned 500 and `E4` returned 500 instead of 404; (2) a stale process on `:8000`
> (PID 54311) that prevented the fresh orchestrator from binding. Both were environment faults —
> **no runtime defect was found, and no runtime or OpenAPI change was made.** Two further faults
> were operator-side: a broken line continuation that stopped `SHORTENER_DB_URL` reaching the JVM,
> and an unset `$CODE` at D4.
>
> **Six README corrections resulted:** explicit disposable-container reset; credential-aware
> host-side database verification; liveness (`/health`) vs readiness (`/v1/runs`) distinction;
> deterministic readiness loop; unknown-run 404 negative control; and the documented
> unknown-parent collection-endpoint limitation (human decision: keep current behaviour, record as
> API semantic debt, change nothing during T103).
>
> Clean rerun: sections A–I all required checks **PASS**. H11 **N/A** (T098 baseline retained).
> Accepted limitations recorded in the validation record §10, including A5 and five H test counts
> **not captured** — deliberately recorded as not captured rather than reconstructed.
- [X] T104 [HUMAN] Re-evaluate all thirteen gates in the Constitution Check of `specs/001-agentic-url-shortener/plan.md` before release readiness (XII, plan § Constitution Check)

> **T104 completed 2026-08-20 — HUMAN-REVIEWED, PASS: release-ready for the take-home prototype.**
> The thirteen gate decisions and the release decision were made by the human reviewer and are
> recorded in `docs/validation/constitution-review.md` §4–§5. **No agent made, influenced, or
> recorded any of them**; an agent assembled the evidence in §1–§3 only.
>
> **13 gates re-evaluated: 12 PASS · 1 N-A (Gate V-a, no server-side URL fetch) · 0 FAIL.**
> **Gate II remains valid and requires no re-approval** — the six T103 README corrections are
> documentation-only; no runtime architecture and no OpenAPI/public contract changed during T103
> or T104. Traceability at close: **79 total / 77 COVERED / 2 DEFERRED_APPROVED / 0 GAP**.
>
> **Four reviewer decisions, carried as standing constraints:** (1) the ten supporting tasks
> without `(REQ)` ids are **ACCEPTED** — requirement ids must **not** be back-fitted for cosmetic
> traceability; (2) the thin orchestrator `unit` layer is **ACCEPTED** as a test-organization
> limitation, to be preserved in documentation — unit-test counts must **not** be manufactured for
> appearance; (3) T102 remains **APPROVED WITH CONDITIONS**, all ten accepted risks and six binding
> conditions in force, **for the local take-home prototype only and not for shared or production
> deployment**; (4) release readiness **PASS**.

---

## Deferred Capabilities

Requirements are **unchanged**; these are deferred at the implementation level for the 2–3 day budget. Each is designed — contract, data model, and rationale exist — but not built. T093 carries this register into `docs/` with re-entry cost.

| Capability | Requirement | Status | Re-entry cost |
|-----------|-------------|--------|---------------|
| Custom aliases | FR-005 | `DEFERRED_APPROVED`. Designed, not built; contract and conflict semantics specified | Low — one validation policy plus a conflict path |
| Creation rate limiting | FR-015 | `DEFERRED_APPROVED`. Designed, not built; R8 fixes 60/min, burst 10 | Low — one table and one filter |
| Paginated event history | FR-014 (history half) | Designed, not built. Summary is built | Low — one query and a cursor |
| Event retention sweep | FR-013 (retention half) | Designed, not built. Behaviour documented in T093 | Low — one scheduled chunked delete |
| Monthly range partitioning | R14 mechanism | **Removed** from the plan. Simple indexed table instead | Medium — a migration, only if scale demands |
| Regression exit-gate test | FR-026 (US4 scenario 5) | Deferred; gates themselves are built and tested | Low |
| Console gates/replan/metrics/audit screens | FR-045, FR-047 | API-visible; surfaced in the Run view where simple | Medium — four views |
| Console accessibility pass | X | Baseline quality only | Low |
| Brownfield plan-against-existing test | FR-033 (US4 scenario 1) | Deferred; selective replanning itself is built and tested | Low |

**Not deferred, deliberately**: every governance and safety requirement — FR-028, FR-029, FR-039, FR-040, FR-041–FR-044, FR-049, FR-050 — is implemented and tested. The rescope cut feature breadth, not the boundaries that make autonomy safe.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup - BLOCKS all user stories
- **User Stories (Phase 3+)**: all depend on Foundational
  - US1 and US2 are independent of each other and can proceed in parallel
  - US3 depends on US2; US4 depends on US1 and US2; US5 depends on US1; US6 depends on US2
- **Polish (Phase 9)**: depends on the stories being delivered

### Within Each User Story

- Tests MUST be written and observed FAILING before implementation (Principle IV)
- Migrations before entities; entities before services; services before controllers
- Core implementation before console views
- Within US2, checkpoints 2a → 2b → 2c are sequential; 2d and 2e build on 2c; 2f is last

### Parallel Opportunities

- Setup: T002–T004 in parallel
- Foundational: T008–T010 in parallel
- **US1 and US2 are the largest parallel opportunity** — different languages, services, and databases, sharing no code
- Within every checkpoint, test tasks marked [P] can be written in parallel

---

## Implementation Strategy

### Priority order under the 2–3 day budget

Orchestration first where it competes with shortener breadth. If time runs out, the right thing to be missing is shortener feature breadth, not orchestration depth.

1. Phase 1 + Phase 2 — foundation
2. **Phase 4 checkpoints 2a–2c** — stateful orchestration, demonstrable without any agent authorship
3. Phase 3 — US1 core shortener (the workload the orchestrator acts on)
4. **Phase 4 checkpoints 2d–2f** — bounded agent runtime, approvals, governance, console
5. Phase 5 — US3, the safety demonstration, cheapest story on the list
6. Phase 6 — US4 minimum brownfield
7. Phases 7–8 — analytics summary and metrics
8. Phase 9 — verification and release readiness

### Fallback checkpoints

- **After 2c**: stateful orchestration with a persisted DAG, gates, and resume — demonstrable with human-executed nodes only
- **After US1**: a working shortener, independently demonstrable
- **After 2e**: the full safety argument — bounded agents, approvals, governance guardrails, audit
- **After US3**: all three required scenarios except brownfield

---

## Notes

- [MODE] is declared at planning time and is not escalatable — the same rule FR-042 places on orchestrator task nodes
- [P] tasks = different files, no dependencies
- [Story] and (REQ) labels map each task to its user story and requirement IDs (Principle III)
- Every task carries at least one requirement reference; a task with none is out of scope (FR-035)
- Tests MUST be observed failing before implementation (Principle IV)
- Agent-executed tasks are bounded per FR-041: interface, acceptance criteria, dependencies, and security constraints must all be approved before dispatch, with the path allow-list scoped to one surface
- Commit after each task or logical group; stop at any checkpoint to validate independently
