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

- [ ] T001 [AGENT] Create the three-surface repository structure — `shortener/`, `orchestrator/`, `console/`, plus `ops/` for operational scripts. No shared runtime module: the services share contracts only (plan § Structure Decision)
- [ ] T002 [AGENT] [P] Initialize the Java 21 + Spring Boot 3 project in `shortener/` with Web MVC, Bean Validation, Spring Data JPA, Actuator, springdoc-openapi (R4)
- [ ] T003 [AGENT] [P] Initialize the Python 3.13 project in `orchestrator/pyproject.toml` with FastAPI and the `anthropic` SDK (R1, R6)
- [ ] T004 [AGENT] [P] Initialize the React + TypeScript console in `console/` with Vite, building to static assets (R5)
- [ ] T005 [AGENT] Configure consolidated formatting, linting, and the four-layer CI targets across all three surfaces in `.github/workflows/ci.yml` (IV, R10, X)
- [ ] T006 [HUMAN] Provision PostgreSQL with two databases and two roles — `shortener_db`, `orchestrator_db`, neither able to read the other — in `ops/db/provision.sql` (R3, NFR-006)
- [ ] T007 [HUMAN] Grant the orchestrator role `INSERT` and `SELECT` but **not** `UPDATE` or `DELETE` on `audit_event` in `ops/db/provision.sql` (FR-036, approval record item 6)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T008 [AGENT] [P] Implement each service's own correlation and trace identifier helper — no cross-language import — against the field names fixed in `contracts/correlation.md`, in `shortener/src/main/java/.../shortener/trace/` and `orchestrator/src/trace/` (VIII, NFR-007)
- [ ] T009 [AGENT] [P] Define the stable error identifier set and response shapes in `shortener/src/main/java/.../shortener/web/errors/` and `orchestrator/src/api/errors.py` (FR-009, FR-016, SC-004)
- [ ] T010 [AGENT] [P] Build the Testcontainers PostgreSQL harnesses in `shortener/src/test/java/support/` and `orchestrator/tests/support/` (R3, R10)
- [ ] T011 [AGENT] Implement the Spring Boot skeleton with Actuator health and the FastAPI skeleton with health in `shortener/src/main/java/.../shortener/` and `orchestrator/src/api/app.py` (NFR-007)
- [ ] T012 [AGENT] Implement the console shell and typed API client in `console/src/api/` (FR-045, FR-048)
- [ ] T013 [AGENT] Configure migration tooling and baselines for both databases in `shortener/src/main/resources/db/migration/` and `orchestrator/src/store/migrations/` (NFR-003)
- [ ] T014 [AGENT] Configure separate connection pools for the redirect path and analytics serving in `shortener/src/main/resources/application.yaml` (NFR-002, R14)
- [ ] T015 [HUMAN] Restrict orchestrator process egress to the configured Claude endpoint only, in `orchestrator/src/agent/config.py` (R6, SC-017)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Shorten a link and follow it (Priority: P1) 🎯 MVP

**Goal**: A client turns a valid HTTP/HTTPS destination into a short link; anyone following it lands on the destination; the creator can set an expiry and revoke. **Core only** — custom aliases and rate limiting are deferred.

**Independent Test**: Submit a valid destination, receive a short link, follow it in a browser, land on the destination. Submit invalid and non-HTTP(S) destinations and receive distinct refusals with no link created. Requires none of the orchestration system.

### Tests for User Story 1 (REQUIRED - Principle IV) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T016 [AGENT] [P] [US1] Contract test for link creation and for the distinct outcomes of unknown, expired, malformed, and revoked resolution in `shortener/src/test/java/contract/LinkContractTest.java` (FR-001, FR-003, FR-009, FR-016, SC-004)
- [ ] T017 [AGENT] [P] [US1] Contract test asserting the redirect is temporary and explicitly non-cacheable in `shortener/src/test/java/contract/RedirectContractTest.java` (FR-007, clarification 2026-08-18)
- [ ] T018 [AGENT] [P] [US1] Integration test rejecting the non-HTTP(S) scheme corpus with no link stored in `shortener/src/test/java/integration/SchemeRejectionTest.java` (FR-002, FR-010, SC-003)
- [ ] T019 [AGENT] [P] [US1] Concurrency test proving no code collision overwrites an existing link in `shortener/src/test/java/integration/CodeUniquenessTest.java` (FR-004, SC-005, R12)
- [ ] T020 [AGENT] [P] [US1] Failure test asserting a redirect whose count cannot be durably recorded fails rather than serving uncounted in `shortener/src/test/java/failure/RedirectRecordingFailureTest.java` (R14, approval record item 7)
- [ ] T021 [AGENT] [P] [US1] Unit tests for code generator alphabet, length, and bounded collision retry in `shortener/src/test/java/unit/CodeGeneratorTest.java` (FR-004, R12, VII)
- [ ] T022 [HUMAN] [US1] Time-to-first-success validation — an untrained person creates and follows a short link, timed, recorded in `specs/001-agentic-url-shortener/baseline.md` (SC-001)

### Implementation for User Story 1

- [ ] T023 [AGENT] [P] [US1] Write the `short_link` and `redirect_event` migrations — simple indexed event table, no partitioning — in `shortener/src/main/resources/db/migration/` (FR-004, FR-008, FR-012, FR-013)
- [ ] T024 [AGENT] [US1] Implement the `ShortLink` and `RedirectEvent` JPA entities in `shortener/src/main/java/.../shortener/domain/` (FR-004, FR-007, FR-013)
- [ ] T025 [AGENT] [P] [US1] Implement destination validation, canonicalisation, and the reserved path registry in `shortener/src/main/java/.../shortener/validation/` (FR-002, FR-003, FR-006, FR-011, NFR-006)
- [ ] T026 [AGENT] [US1] Implement the short code generator — random, 7 characters, 62-symbol alphabet, bounded collision retry — in `shortener/src/main/java/.../shortener/domain/CodeGenerator.java` (FR-004, R12, VII)
- [ ] T027 [AGENT] [US1] Implement create, resolve, and revoke with expiry and revocation checks in `shortener/src/main/java/.../shortener/service/LinkService.java` (FR-001, FR-007, FR-008, FR-009, FR-012)
- [ ] T028 [AGENT] [US1] Implement the redirect transaction — counter and event committed before the response is issued — in `shortener/src/main/java/.../shortener/service/RedirectService.java` (FR-013, R14, SC-006)
- [ ] T029 [AGENT] [US1] Implement the `/v1` create and revoke controllers, the unversioned redirect controller, and the exception handler mapping every failure to a stable error identifier, in `shortener/src/main/java/.../shortener/web/` (FR-007, FR-009, FR-010, FR-012, FR-016, SC-004, R9)
- [ ] T030 [AGENT] [US1] Publish the generated OpenAPI contract and verify it matches `contracts/shortener-api.md` (FR-016, FR-017, R4)

**Checkpoint**: User Story 1 fully functional and testable independently — quickstart scenarios 1 and 3

---

## Phase 4: User Story 2 - Greenfield delivery through the orchestrated workflow (Priority: P1)

**Goal**: An engineering lead submits a requirement; the system records its interpretation, decomposes into a dependency graph, executes with parallelism and synchronisation, halts at gates and approvals, and produces a complete audit trail.

**Independent Test**: Submit the greenfield requirement, inspect the graph before execution, watch parallel branches converge, approve the architecture checkpoint, then trace any produced change back to its requirement and forward to its validating test.

**Six checkpoints, each independently testable and demonstrable.** If time runs short, 2a–2c alone demonstrate stateful orchestration without agent authorship.

### Checkpoint 2a — Persistence + state model

**Demonstrable when**: schema migrates, states are enumerated, audit has no update path.

- [ ] T031 [AGENT] [P] [US2] Integration test asserting migrations apply, states are enumerable, and the store exposes no audit update or delete path in `orchestrator/tests/integration/test_store_shape.py` (FR-025, FR-036, NFR-004)
- [ ] T032 [AGENT] [US2] Write all orchestrator migrations — requirement, workflow_run, task_node, task_dependency, gate, approval_record, decision_record, change_record, audit_event, replan_event, trace_link — in `orchestrator/src/store/migrations/` (FR-020, FR-025, FR-027, FR-033, FR-036, data-model)
- [ ] T033 [AGENT] [P] [US2] Implement the run and node state enumerations in `orchestrator/src/models/states.py` (R7, FR-025)
- [ ] T034 [AGENT] [US2] Implement the store layer with no update or delete path for audit records in `orchestrator/src/store/repository.py` (FR-036, NFR-004)

### Checkpoint 2b — Requirement interpretation + DAG planning

**Demonstrable when**: a requirement becomes a recorded interpretation and an acyclic graph; a cycle is rejected.

- [ ] T035 [AGENT] [P] [US2] Workflow test asserting a written interpretation is recorded before any implementation task exists in `orchestrator/tests/workflow/test_interpretation.py` (FR-020)
- [ ] T036 [AGENT] [P] [US2] Workflow test asserting the plan is a DAG and a cycle is rejected before execution in `orchestrator/tests/workflow/test_graph_validity.py` (FR-022)
- [ ] T037 [AGENT] [US2] Implement requirement intake and interpretation recording in `orchestrator/src/engine/intake.py` (FR-020)
- [ ] T038 [AGENT] [US2] Implement decomposition into task nodes with mandatory requirement references and declared execution mode in `orchestrator/src/engine/decompose.py` (FR-021, FR-035, FR-042)
- [ ] T039 [AGENT] [US2] Implement DAG construction with cycle rejection and readiness computation in `orchestrator/src/graph/builder.py` (FR-022, FR-023)

### Checkpoint 2c — Execution + synchronization + gates

**Demonstrable when**: parallel branches run and converge, gates block, an interrupted run resumes.

- [ ] T040 [AGENT] [P] [US2] Workflow test asserting independent tasks run concurrently and a sync node waits for every inbound branch in `orchestrator/tests/workflow/test_parallel_sync.py` (FR-023, FR-024, SC-008)
- [ ] T041 [AGENT] [P] [US2] Workflow test asserting entry and exit gates block and record outcome and reason in `orchestrator/tests/workflow/test_gates.py` (FR-026)
- [ ] T042 [AGENT] [P] [US2] Workflow test asserting an interrupted run resumes with no completed task re-executed and no lost transition in `orchestrator/tests/workflow/test_resume.py` (FR-025, SC-012)
- [ ] T043 [AGENT] [US2] Implement the concurrent scheduler and synchronisation node semantics in `orchestrator/src/engine/scheduler.py` and `orchestrator/src/graph/sync.py` (FR-023, FR-024)
- [ ] T044 [AGENT] [US2] Implement gate definition, evaluation, and recording in `orchestrator/src/engine/gates.py` (FR-026)
- [ ] T045 [AGENT] [US2] Implement state persistence at every transition and resume-from-persisted-state in `orchestrator/src/engine/state.py` (FR-025, NFR-003, SC-012)

### Checkpoint 2d — Bounded agent runtime (HUMAN)

**Demonstrable when**: an agent completes a bounded task and cannot reach outside its allow-list.

> **All tasks in this checkpoint are `[HUMAN]`.** An agent must not implement, test, or approve its own capability boundary (FR-041, FR-042, Principle II).

- [ ] T046 [HUMAN] [P] [US2] Failure test asserting an agent write outside its declared path allow-list is refused and that the tool set exposes no shell, network, package-install, or git capability, with server-side web search, web fetch, and code execution not declared, in `orchestrator/tests/failure/test_capability_boundary.py` (FR-041, R6, SC-017)
- [ ] T047 [HUMAN] [P] [US2] Failure test asserting execution mode cannot be escalated from human-executed to agent-authored mid-run in `orchestrator/tests/failure/test_mode_escalation.py` (FR-042, SC-019)
- [ ] T048 [HUMAN] [US2] Implement the four bounded tools and per-surface path allow-list derivation in `orchestrator/src/agent/tools.py` and `orchestrator/src/agent/allowlist.py` (FR-041, R6)
- [ ] T049 [HUMAN] [US2] Implement the Claude client with adaptive thinking, per-task-class effort, and a declared task budget, with server-side tools deliberately not declared, in `orchestrator/src/agent/client.py` (FR-030, NFR-009, R6)
- [ ] T050 [HUMAN] [US2] Implement the per-turn approval hook that halts a checkpoint-crossing tool call before it is applied in `orchestrator/src/agent/approval_hook.py` (FR-043, R6)
- [ ] T051 [HUMAN] [US2] Implement bounded-task precondition checking — interface, acceptance criteria, dependencies, and security constraints all approved before dispatch — in `orchestrator/src/agent/dispatch.py` (FR-041, FR-042)

### Checkpoint 2e — Approvals + lineage + audit + governance guardrails

**Demonstrable when**: a checkpoint halts for a role-holding approver, out-of-scope work is refused, and the run is reconstructable from its audit trail.

- [ ] T052 [HUMAN] [P] [US2] Workflow test asserting checkpoints halt for approval, no agent can self-approve, and an approval from an identity lacking the approver role is rejected and audited in `orchestrator/tests/workflow/test_approvals.py` (FR-029, FR-043, FR-050, SC-009)
- [ ] T053 [HUMAN] [P] [US2] Failure test asserting work outside the approved scope of the run is blocked and surfaced for human decision, and that governance artifacts — constitution, approval policy, gate definitions — cannot be modified without explicit human approval, in `orchestrator/tests/failure/test_governance_guardrails.py` (FR-039, FR-040)
- [ ] T054 [AGENT] [P] [US2] Workflow test asserting bidirectional traceability from requirement to tests and from change to requirement in `orchestrator/tests/workflow/test_traceability.py` (FR-034, FR-035, SC-007)
- [ ] T055 [HUMAN] [US2] Implement the approval request and record flow with approver role verification and agent-identity exclusion in `orchestrator/src/engine/approvals.py` (FR-029, FR-050)
- [ ] T056 [HUMAN] [US2] Implement scope-boundary enforcement and governance-artifact protection in `orchestrator/src/engine/guardrails.py` (FR-039, FR-040)
- [ ] T057 [AGENT] [US2] Implement change record capture including prior artifact state before apply, and decision lineage recording, in `orchestrator/src/engine/changes.py` and `orchestrator/src/engine/decisions.py` (FR-027, FR-043, FR-044)
- [ ] T058 [AGENT] [US2] Implement traceability link construction and bidirectional query in `orchestrator/src/audit/trace.py` (FR-034, FR-035)
- [ ] T059 [AGENT] [US2] Implement append-only audit emission for every action, decision, gate, approval, retry, failure, rollback, replan, and transition in `orchestrator/src/audit/events.py` (FR-036, FR-038)

### Checkpoint 2f — API + minimal console

**Demonstrable when**: a reviewer follows and acts on a live run from two console views.

- [ ] T060 [AGENT] [P] [US2] Contract test asserting every field the console renders is present in an orchestrator API response in `console/tests/api-parity.test.ts` (FR-048, R5)
- [ ] T061 [AGENT] [US2] Implement the orchestrator `/v1` routes — requirement, run, graph, gates, pending, approvals, clarifications, decisions, audit, metrics, trace — in `orchestrator/src/api/routes.py` (FR-045, FR-048, contracts/orchestrator-api.md)
- [ ] T062 [AGENT] [US2] Implement the console **Run view** — dependency graph with node state, gates, and audit timeline — in `console/src/views/RunView.tsx` (FR-045, FR-048, R5)
- [ ] T063 [AGENT] [US2] Implement the console **Human action view** — pending approvals and clarification requests, with submission confirmed by re-reading the run rather than optimistic update — in `console/src/views/HumanActionView.tsx` (FR-045, FR-046, FR-048, SC-020, R5)

**Checkpoint**: User Stories 1 AND 2 both work independently

---

## Phase 5: User Story 3 - Ambiguous requirement stops for human clarification (Priority: P2)

**Goal**: A deliberately unclear requirement produces no implementation and no code changes; the system records specific answerable questions and halts until a human answers.

**Independent Test**: Submit the ambiguous requirement, confirm zero implementation tasks and specific recorded questions with the run halted in `WAITING_FOR_HUMAN`, then answer and confirm planning resumes.

### Tests for User Story 3 (REQUIRED - Principle IV) ⚠️

- [ ] T064 [AGENT] [P] [US3] Workflow test asserting an ambiguous requirement produces zero implementation tasks and zero code changes, with ambiguities recorded as specific answerable questions, in `orchestrator/tests/workflow/test_ambiguity_halt.py` (FR-028, SC-010)
- [ ] T065 [AGENT] [P] [US3] Workflow test asserting `WAITING_FOR_HUMAN` survives process restart with its pending request intact in `orchestrator/tests/workflow/test_waiting_persistence.py` (FR-049, SC-021)
- [ ] T066 [AGENT] [P] [US3] Failure test asserting no agent loop, retry timer, or polling cycle remains active while waiting, and the state never expires into autonomous execution, in `orchestrator/tests/failure/test_waiting_quiescence.py` (FR-049, SC-021)
- [ ] T067 [AGENT] [P] [US3] Integration test asserting a clarification answer resumes planning and is recorded in decision lineage attributed to its human actor in `orchestrator/tests/integration/test_clarification_resume.py` (FR-028, FR-046)

### Implementation for User Story 3

- [ ] T068 [AGENT] [US3] Implement ambiguity identification that halts when scope, security posture, or user-visible behaviour is undetermined in `orchestrator/src/engine/ambiguity.py` (FR-028)
- [ ] T069 [AGENT] [US3] Implement the `WAITING_FOR_HUMAN` transition that quiesces all loops and timers for the run in `orchestrator/src/engine/waiting.py` (FR-049, NFR-009)
- [ ] T070 [AGENT] [US3] Implement clarification request creation, answer recording, and resumption of planning in `orchestrator/src/engine/clarifications.py` (FR-028, FR-046)

**Checkpoint**: The safety demonstration — quickstart scenario 5

---

## Phase 6: User Story 4 - Minimum brownfield path for selective replanning (Priority: P2)

**Goal**: The minimum needed to demonstrate selective replanning — blast radius from the dependency closure, staleness that preserves results, and bounded failure handling with rollback.

**Independent Test**: Change an upstream decision partway through a run and confirm the reported blast radius matches the dependency closure, only affected nodes are re-planned, and unaffected completed nodes retain their results.

**Depends on**: US1 (something to enhance) and US2 (the run machinery).

### Tests for User Story 4 (REQUIRED - Principle IV) ⚠️

- [ ] T071 [AGENT] [P] [US4] Workflow test asserting the reported blast radius equals the graph's dependency closure and only affected nodes are re-planned in `orchestrator/tests/workflow/test_selective_replan.py` (FR-033, SC-011)
- [ ] T072 [AGENT] [P] [US4] Failure test asserting rollback restores prior artifact state exactly and records the attempt and outcome in `orchestrator/tests/failure/test_rollback.py` (FR-032, FR-044, SC-018)
- [ ] T073 [AGENT] [P] [US4] Failure test asserting timeout and retry exhaustion terminate in the declared fallback or a safe-stop, never an unbounded loop, in `orchestrator/tests/failure/test_bounded_operations.py` (FR-030, FR-031, SC-016)

### Implementation for User Story 4

- [ ] T074 [AGENT] [US4] Implement blast radius computation from the dependency closure and staleness marking that preserves completed results in `orchestrator/src/graph/blast_radius.py` (FR-033, R7)
- [ ] T075 [AGENT] [US4] Implement selective subgraph replanning with replan event recording, never defaulting to a full restart, in `orchestrator/src/engine/replan.py` (FR-033, FR-036, SC-011)
- [ ] T076 [AGENT] [US4] Implement the rollback executor restoring prior artifact state from the change record in `orchestrator/src/engine/rollback.py` (FR-032, FR-044)
- [ ] T077 [AGENT] [US4] Implement per-operation timeout, bounded retry with backoff, declared fallback, and safe-stop in `orchestrator/src/engine/bounds.py` (FR-030, FR-031, NFR-009)

**Checkpoint**: Selective replanning demonstrable — quickstart scenario 6

---

## Phase 7: User Story 5 - Basic analytics summary (Priority: P3)

**Goal**: The creating client sees total redirects and first/most-recent timestamps. **Summary only** — paginated event history and the retention sweep are deferred.

**Independent Test**: Create a link, follow it several times, request the summary, and confirm the count and timestamps match exactly.

**Depends on**: US1.

- [ ] T078 [AGENT] [P] [US5] Integration test asserting the summary reports total, first, and most recent redirect, and that a non-creating client is refused, in `shortener/src/test/java/integration/AnalyticsSummaryTest.java` (FR-014, SC-006)
- [ ] T079 [AGENT] [US5] Implement the analytics summary with owner scoping in `shortener/src/main/java/.../shortener/service/AnalyticsService.java` (FR-014)
- [ ] T080 [AGENT] [US5] Implement the `/v1` analytics summary controller on the analytics connection pool in `shortener/src/main/java/.../shortener/web/AnalyticsController.java` (FR-014, FR-016, NFR-002)

**Checkpoint**: Analytics summary demonstrable — quickstart scenario 2 (summary portion)

---

## Phase 8: User Story 6 - Reliability metrics and audit, API-level (Priority: P3)

**Goal**: Metrics and audit retrieval available and correct through the API. Console presentation is limited to what the Run view already shows.

**Independent Test**: Execute several runs including a failure and a rollback, request the metrics, and confirm every value matches observed outcomes. Reconstruct a run from its audit trail alone.

**Depends on**: US2.

- [ ] T081 [AGENT] [P] [US6] Test asserting metrics match independently observed run outcomes, with time in `WAITING_FOR_HUMAN` excluded from MTTR and latency and reported separately, in `orchestrator/tests/integration/test_metrics.py` (FR-037, SC-014, R11)
- [ ] T082 [AGENT] [P] [US6] Test asserting a completed run is reconstructable from its audit trail alone and that the orchestrator role cannot `UPDATE` or `DELETE` audit records in `orchestrator/tests/integration/test_audit_reconstruction.py` (FR-036, NFR-004, SC-013)
- [ ] T083 [AGENT] [P] [US6] Test asserting no secrets or personal data appear in audit records, logs, or metrics in `orchestrator/tests/integration/test_no_secrets.py` (FR-038, SC-015)
- [ ] T084 [AGENT] [US6] Implement metric computation per the R11 definitions in `orchestrator/src/audit/metrics.py` (FR-037, FR-047, R11)

**Checkpoint**: Reliability and audit demonstrable — quickstart scenario 7

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Verification and release readiness

- [ ] T085 [AGENT] Build one reproducible load baseline at the NFR-005 operating point, recording uniform and hot-link observations, in `shortener/src/test/java/load/` and `specs/001-agentic-url-shortener/baseline.md` (NFR-001, NFR-005, SC-002, plan § Recorded risks)
- [ ] T086 [AGENT] Verify zero outbound requests to caller-supplied destinations across the corpus in `shortener/src/test/java/failure/EgressTest.java` (FR-018, SC-017)
- [ ] T087 [AGENT] Produce the traceability audit in `specs/001-agentic-url-shortener/traceability.md`, classifying every requirement as exactly one of `COVERED` (task, change, and validating test in both directions), `DEFERRED_APPROVED` (citing plan.md § Delivery Scope and tasks.md § Deferred Capabilities — FR-005 and FR-015 only), or `GAP`. Any `GAP` is a failure condition (FR-034, FR-035, III, SC-007)
- [ ] T088 [AGENT] [P] Document public interfaces, retention behaviour, non-obvious decisions, and the deferred-capability register with re-entry cost, across all three surfaces in `docs/` (NFR-008, III, XI, X)
- [ ] T089 [HUMAN] Run the security review — input validation, secret handling, least privilege, approver identity separation, agent capability boundary — recording findings in `specs/001-agentic-url-shortener/security-review.md` (NFR-006, FR-050, V)
- [ ] T090 [HUMAN] Run the implemented scenarios in `specs/001-agentic-url-shortener/quickstart.md` end to end (quickstart.md)
- [ ] T091 [HUMAN] Re-evaluate all thirteen gates in the Constitution Check of `specs/001-agentic-url-shortener/plan.md` before release readiness (XII, plan § Constitution Check)

---

## Deferred Capabilities

Requirements are **unchanged**; these are deferred at the implementation level for the 2–3 day budget. Each is designed — contract, data model, and rationale exist — but not built. T088 carries this register into `docs/` with re-entry cost.

| Capability | Requirement | Status | Re-entry cost |
|-----------|-------------|--------|---------------|
| Custom aliases | FR-005 | `DEFERRED_APPROVED`. Designed, not built; contract and conflict semantics specified | Low — one validation policy plus a conflict path |
| Creation rate limiting | FR-015 | `DEFERRED_APPROVED`. Designed, not built; R8 fixes 60/min, burst 10 | Low — one table and one filter |
| Paginated event history | FR-014 (history half) | Designed, not built. Summary is built | Low — one query and a cursor |
| Event retention sweep | FR-013 (retention half) | Designed, not built. Behaviour documented in T088 | Low — one scheduled chunked delete |
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
