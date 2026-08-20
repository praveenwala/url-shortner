# Requirements traceability audit (T100)

**Date:** 2026-08-20 · **Feature:** `specs/001-agentic-url-shortener` · **Status: FINAL SUBMISSION AUDIT (T100), closed after T022, T102, T103 and T104**
**Method:** every row verified against the current codebase, not against the task list's own claims

This document is the FR-034 report turned on the delivery itself: for each requirement it names
the tasks, the implementation, the validating tests, the approval where one applies, and the
runtime evidence. Nothing is marked covered on the strength of a task checkbox — several tasks
turned out to name files that do not exist, and those are reported in §5 rather than smoothed
over.

## 1. Summary

| | Count |
|---|---|
| Total requirements (FR 49 · NFR 9 · SC 21) | **79** |
| `COVERED` | **77** |
| `DEFERRED_APPROVED` | **2** |
| `GAP` | **0** |

**No gaps remain.** Every requirement is either covered by implementation and test, or carries an
approved deferral with a register entry.

*Closed since the first issue of this document:* **SC-001** — T022 was executed and timed by a
human participant on 2026-08-20 and recorded in `specs/001-agentic-url-shortener/baseline.md`
(unaided, approximately 0.5 seconds against a 30-second budget). The participant's link
`Ii2L2v2` was then independently verified end to end. The timing is human-provided; no part of
it was measured or performed by an agent.

Both gaps identified by the original audit have since been closed by the tasks that owned them —
SC-001 by human-executed T022, NFR-008 by T101 — and the automated check in §7 fails the build if
a new one appears.

*Numbering note:* FR-019 does not exist. Shortener requirements end at FR-018 and orchestration
requirements begin at FR-020; the skip is a section boundary, not a lost requirement.

## 2. Requirement coverage matrix

| ID | Requirement | Status | Task(s) | Implementation | Test(s) | Decision / approval | Evidence |
|---|---|---|---|---|---|---|---|
| **FR-001** | System MUST create a short link when given a syntactically valid absolute destination… | COVERED | T016,T027 | shortener .../service/LinkService.java, web/LinkController.java | contract/LinkContractTest#createsAShortLinkForAValidHttpsDestination | — | 201 + code returned in perf seed and contract runs |
| **FR-002** | System MUST refuse any destination that is not http/https — including javascript:,… | COVERED | T018,T025 | validation/DestinationValidator.java | unit/DestinationValidatorTest#rejectsEverySchemeOutsideTheAllowList (parameterised) | — | invalid_scheme returned for javascript:/data:/file:/ftp: |
| **FR-003** | System MUST refuse malformed destinations and destinations exceeding a published… | COVERED | T016,T025 | validation/DestinationValidator.java, web/errors/ErrorCode.java | unit/DestinationValidatorTest#rejectsRelativeAndMalformedInput, #rejectsAnOverlongDestination; contract/LinkContractTest#refusesAMalformedUrl | — | malformed_url and url_too_long are distinct identifiers |
| **FR-004** | System MUST assign every new link a short code of 7 characters drawn from a… | COVERED | T019,T021,T023,T024,T026 | domain/CodeGenerator.java, persistence/ShortLinkRepository.java | unit/CodeGeneratorTest (5); integration/CodeUniquenessTest#concurrentCreationNeverOverwritesAnExistingLink | — | 100,000 distinct codes seeded in the T098 baseline |
| **FR-005** | System MUST allow a caller to request a custom alias. An alias MUST use the same… | **DEFERRED_APPROVED** | — | not built | — | tasks.md § Deferred Capabilities; plan.md § Delivery Scope | ALIAS_* identifiers declared but unreachable — contract/OpenApiParityTest#deferredIdentifiersAreDeclaredButUnreachableThroughTheApi |
| **FR-006** | System MUST maintain a documented set of reserved paths (health, API, administrative… | COVERED | T025 | validation/ReservedPaths.java | contract/LinkContractTest#reservedPathsAreNeverIssuedOrResolved | — | reserved paths never issued as codes |
| **FR-007** | On resolution of a known, unexpired, unrevoked code, the system MUST redirect the… | COVERED | T017,T024,T027,T029 | service/LinkService.java#resolveAndCount, web/RedirectController.java | contract/RedirectContractTest#redirectsToTheExactStoredDestination, #redirectIsTemporaryNotPermanent, #redirectIsExplicitlyNonCacheable | — | 302 + exact Location verified across 24,000 baseline redirects |
| **FR-008** | System MUST accept an optional expiry at creation. After expiry, resolution MUST NOT… | COVERED | T023,T027 | domain/ShortLink.java, service/LinkService.java | contract/LinkContractTest#acceptsAnOptionalExpiry, #expiredLinkIsDistinctFromUnknown | — | expired resolution does not redirect |
| **FR-009** | System MUST return distinct machine-readable outcomes for each of: unknown code,… | COVERED | T009,T016,T027,T029 | web/errors/ErrorCode.java, ApiExceptionHandler.java | contract/LinkContractTest#everyFailureIdentifierIsDistinct; unit/ErrorCodeTest#resolutionOutcomesAreSeparateIdentifiers | — | four distinct machine-readable outcomes |
| **FR-010** | System MUST NOT redirect to any destination supplied at resolution time (for example… | COVERED | T018,T029 | web/RedirectController.java | contract/RedirectContractTest#aQueryParameterCannotRedirectSomewhereElse | — | open-redirect probe refused |
| **FR-011** | System MUST canonicalise destinations for storage and comparison without altering the… | COVERED | T025 | validation/DestinationValidator.java | unit/DestinationValidatorTest#canonicalisesForComparisonWithoutAlteringTheRedirectTarget, #canonicalisationDropsDefaultPortsAndLowercasesTheHostOnly | — | stored destination byte-identical to the redirect target |
| **FR-012** | System MUST allow the creating client to revoke a link, after which resolution MUST NOT… | COVERED | T023,T027,T029 | service/LinkService.java, web/LinkController.java#revoke | integration/AnalyticsAndRevokeTest#onlyTheCreatorMayRevoke, #revokedLinkNoLongerRedirects | — | revoked link stops redirecting |
| **FR-013** | System MUST record a timestamp for every successful redirect and maintain a cumulative… | COVERED | T023,T024,T028 | domain/ShortLink.java (counter), domain/RedirectEvent.java, db/migration/V2__short_links.sql | contract/RedirectContractTest#everySuccessfulRedirectIsCountedBeforeTheResponse; integration/AnalyticsAndRevokeTest#lifetimeCountersAreIndependentOfEventRetention | — | T098 baseline: 26,801 events == 26,801 counted redirects. **Retention sweep deferred** (register) |
| **FR-014** | System MUST expose per-link analytics to the client that created the link, and MUST… | COVERED | T091,T092,T093 | service/LinkService.java, web/LinkController.java#analytics | integration/AnalyticsAndRevokeTest#analyticsAreOwnerScoped, #summaryReportsTotalFirstAndMostRecent, #summaryIsZeroRatherThanAnErrorForAnUnfollowedLink | — | owner-scoped 200/403. **Paginated history half deferred** (register) |
| **FR-015** | System MUST rate-limit link creation per identified client and MUST return a distinct… | **DEFERRED_APPROVED** | — | not built | — | tasks.md § Deferred Capabilities; plan.md § Delivery Scope | RATE_LIMITED declared but unreachable — contract/OpenApiParityTest#deferredIdentifiersAreDeclaredButUnreachableThroughTheApi |
| **FR-016** | All shortener operations other than the redirect itself MUST be available to automated… | COVERED | T009,T016,T029,T030,T093 | web/LinkController.java, springdoc; docs/contracts/shortener-openapi.json | contract/OpenApiParityTest (12): #everyDeclaredOperationIsImplemented, #everyImplementedOperationIsDeclared, #theCommittedDocumentMatchesTheRunningApplication | — | CI-gated parity; drift proven to fail the build (T030) |
| **FR-017** | The shortener MUST NOT include a web frontend as a deliverable. Link creators interact… | COVERED | T030 | no static/, no templates/ under shortener/src/main/resources | contract/OpenApiParityTest#redirectSemanticsArePublished, #redirectHeadersAreActuallyServed | — | no frontend asset ships with the shortener; redirect works scriptless |
| **FR-018** | The system MUST NOT issue any outbound network request to a caller-supplied destination… | COVERED | T099 | validation/DestinationValidator.java (syntactic only — no reachability check) | failure/EgressTest (5): creation, resolution, analytics+revocation, rejected destination, plus a reachability control | — | T099: a real HTTP listener recorded **zero** requests across the corpus — docs/security/egress-verification.md |
| **FR-020** | System MUST accept a natural-language requirement and record a written interpretation —… | COVERED | T032,T035,T037 | engine/intake.py, engine/decompose.py | workflow/test_interpretation.py#test_interpretation_records_scope_actors_constraints, #test_decomposition_refused_before_interpretation | — | interpretation persisted before any task exists |
| **FR-021** | System MUST decompose an accepted requirement into discrete tasks, each with declared… | COVERED | T038 | engine/decompose.py (TaskNode) | workflow/test_declared_io.py (16) | — | every agent task carries declared inputs/outputs, actor and dependencies |
| **FR-022** | System MUST represent the plan as a directed acyclic graph, and MUST detect and reject… | COVERED | T036,T039 | graph/builder.py | workflow/test_graph_validity.py#test_direct_cycle_is_rejected, #test_longer_cycle_is_rejected, #test_self_dependency_is_a_cycle | — | cycles rejected before execution begins |
| **FR-023** | System MUST execute tasks whose dependencies are satisfied concurrently, and MUST NOT… | COVERED | T039,T040,T043 | engine/scheduler.py | workflow/test_parallel_sync.py#test_independent_tasks_execute_concurrently, #test_dependent_task_never_starts_before_predecessor_finishes | — | observed concurrency + ordering |
| **FR-024** | System MUST support synchronisation nodes where parallel branches rejoin. A… | COVERED | T040,T043 | graph/sync.py (task_node.is_sync) | workflow/test_parallel_sync.py#test_sync_node_waits_for_every_inbound_branch, #test_sync_node_records_each_branch_outcome_when_one_fails | — | sync releases only on all-terminal |
| **FR-025** | System MUST persist workflow state — graph, node states, decisions, approvals,… | COVERED | T031,T032,T033,T042,T045 | store/repository.py, store/migrations/001..006 | workflow/test_resume.py (5); workflow/test_selective_replan.py#test_restart_preserves_stale_and_replacement_lineage | — | interrupted run inspectable and resumable from the store alone |
| **FR-026** | Every stage MUST declare an entry gate and an exit gate with evaluable criteria. A… | COVERED | T041,T044 | engine/gates.py | workflow/test_gates.py (5): entry/exit blocking, passing evaluations recorded, kind enforced | — | every evaluation recorded pass or fail. **Regression exit-gate scenario deferred** (register) |
| **FR-027** | System MUST record decision lineage for every material decision: alternatives… | COVERED | T032,T066,T070 | engine/decisions.py, store/migrations/003_approvals_and_lineage.sql | failure/test_lineage_and_rollback.py#test_decision_lineage_persists_every_required_field | — | alternatives, selection, rationale, actor, timestamp persisted |
| **FR-028** | System MUST identify ambiguities in a submitted requirement and record each explicitly.… | COVERED | T076,T077,T080,T081,T083 | engine/ambiguity.py, engine/clarifications.py | workflow/test_ambiguity_halt.py (18) | — | ambiguous requirement → 0 tasks, specific questions, WAITING_FOR_HUMAN |
| **FR-029** | System MUST pause and obtain recorded human approval before high-impact architecture… | COVERED | T061,T064,T070 | engine/approvals.py, engine/identity.py, api/approvals_api.py | failure/test_approval_integrity.py (9); integration/test_console_api.py approval group | plan.md § Gate II APPROVED (2026-08-18) | no checkpoint proceeds without a recorded approver decision |
| **FR-030** | Every automated operation MUST declare a timeout, a maximum retry count, and a backoff… | COVERED | T049,T053,T055,T086,T090 | engine/bounds.py (OperationPolicy) | failure/test_bounds.py#test_a_policy_must_declare_positive_bounds, #test_backoff_is_bounded_and_never_unbounded, #test_an_executing_operation_cannot_widen_its_own_budget | — | policy frozen and never handed to the operation |
| **FR-031** | On timeout or retry exhaustion, the system MUST take the operation's declared fallback… | COVERED | T055,T057,T086,T090 | engine/bounds.py, agent/dispatch.py | failure/test_bounds.py#test_declared_safe_stop_preserves_state_and_is_audited; failure/test_fail_closed_real.py#test_real_unreachable_daemon_safe_stops_and_preserves_state | — | T099: real safe-stop with state preserved and reason audited |
| **FR-032** | Reversible operations MUST declare a rollback that restores the prior state; rollback… | COVERED | T052,T069,T085,T089 | agent/changes.py, engine/rollback.py | failure/test_rollback.py (6); failure/test_lineage_and_rollback.py#test_successful_rollback_links_to_the_original_change, #test_failed_rollback_safe_stops_and_is_audited | — | byte-identical restore; rollback outcomes recorded |
| **FR-033** | When an upstream requirement or decision changes, the system MUST compute the affected… | COVERED | T032,T084,T087,T088 | engine/replan.py, graph/builder.py (descendants) | workflow/test_selective_replan.py (18) | — | blast radius = dependency closure. **Plan-against-existing scenario deferred** (register) |
| **FR-034** | System MUST maintain bidirectional traceability: for any requirement it MUST report the… | COVERED | T063,T067,T070 | audit/trace.py (TraceStore) | failure/test_lineage_and_rollback.py#test_requirement_to_task_to_change_to_test_round_trip | — | this document is the FR-034 report for the delivery itself |
| **FR-035** | System MUST refuse or flag any task that has no traceable originating requirement. | COVERED | T038,T063,T067 | audit/trace.py#untraceable_changes, engine/decompose.py | workflow/test_interpretation.py#test_task_without_requirement_reference_is_refused; failure/test_lineage_and_rollback.py#test_a_change_with_no_requirement_is_reported_as_untraceable | — | requirement_ref cannot be blank (DB constraint + construction check) |
| **FR-036** | System MUST append an audit record for every agent action, decision, gate evaluation,… | COVERED | T007,T031,T032,T034,T068,T070,T088,T095 | store/repository.py (AuditRepository, append-only) | integration/test_store_shape.py#test_audit_repository_exposes_no_mutation_path; failure/test_lineage_and_rollback.py#test_runtime_role_cannot_update_delete_or_truncate_audit | T006/T007 HUMAN-provisioned privilege model | append-only enforced by code *and* by database privilege |
| **FR-037** | System MUST compute and report, per run and across runs: success rate, retry frequency,… | COVERED | T094,T097 | audit/metrics.py | integration/test_metrics.py (15) | — | success rate, retry/rollback frequency, MTTR, latency; human wait excluded |
| **FR-038** | Audit records, logs, and metrics MUST exclude secrets and personal data. | COVERED | T068,T096 | store/repository.py#_reject_secrets (key- and value-side) | integration/test_metrics.py#test_metrics_carry_no_secrets_or_personal_data; failure/test_audit_secret_safety.py (5) | — | T099 hardened this: value-side detection added after a real gap was demonstrated |
| **FR-039** | System MUST block work that falls outside the approved scope of the current run and… | COVERED | T062,T065 | engine/guardrails.py | failure/test_guardrails.py#test_out_of_scope_task_halts_and_surfaces_for_a_human, #test_out_of_scope_work_is_not_silently_absorbed | HUMAN task T062/T065 | out-of-scope work surfaces rather than being absorbed |
| **FR-040** | System MUST NOT modify governance artifacts — the constitution, approval policy, or… | COVERED | T062,T065 | engine/guardrails.py, agent/allowlist.py DENIED_PREFIXES | failure/test_governance_protection.py (3); failure/test_guardrails.py#test_governance_write_permitted_only_after_explicit_approval | HUMAN task T062/T065 | `.specify/`, `ops/`, `.git/` unreadable and unwritable by an agent |
| **FR-041** | An agent MAY implement a bounded task — one whose interface, acceptance criteria,… | COVERED | T038,T046,T047,T048,T051,T055,T059 | agent/tools.py (4 tools), agent/client.py, agent/allowlist.py | failure/test_capability_boundary.py (14); failure/test_sandbox_escape.py (15) | tasks.md § Checkpoint 2d — capability boundary HUMAN-APPROVED 2026-08-18 | T099 re-verified: exactly 4 tools, no MCP/server-side tool in the real request payload |
| **FR-042** | Every task node MUST declare its execution mode — agent-authored or human-executed — at… | COVERED | T038,T047,T055 | engine/decompose.py (frozen planning fields) | failure/test_mode_escalation.py (6) | HUMAN task T047 | mode frozen at planning time; escalation impossible |
| **FR-043** | An agent-authored change that would cross an approval checkpoint (architecture,… | COVERED | T054,T061,T066 | agent/approval_hook.py | failure/test_halt_before_apply.py (5) | HUMAN task T054 | halt happens *before* mutation; artifact unchanged on rejection |
| **FR-044** | Every agent-authored change MUST be revertible: the system records the prior state of… | COVERED | T052,T066,T069,T085,T089 | agent/changes.py (prior-state capture, atomic write) | failure/test_rollback.py#test_modified_file_is_restored_byte_identical, #test_write_is_atomic_and_leaves_no_temp_files | — | every agent write is revertible |
| **FR-045** | The orchestration system MUST provide a human-facing console that displays, for any… | COVERED | T012,T072,T073,T074 | console/src/views/RunView.tsx, components/Dag.tsx | console/tests/console.test.tsx#renders run state, requirement, graph, node states, gates, lineage and audit | — | **Four separate screens deferred**; content surfaced in the Run view (register) |
| **FR-046** | The console MUST let a human record an approval or rejection with rationale and submit… | COVERED | T074,T076,T080,T083 | console/src/views/HumanActionView.tsx, api/approvals_api.py | console.test.tsx#requires a rationale before approve or reject, #binds the decision to the request id; integration/test_console_api.py | — | every console action attributed to a named human with rationale |
| **FR-047** | The console MUST display the reliability metrics required by FR-037, per run and across… | COVERED | T097 | console/src/views/RunView.tsx (metrics block) | console.test.tsx#renders the reliability metrics inside the run view, #shows unavailable metrics as em dash rather than zero | — | null (unknown) rendered distinctly from 0 (measured zero) |
| **FR-048** | The console MUST be a view over recorded state, never the sole location of it.… | COVERED | T012,T071,T072,T073,T074,T075 | console/src/api/client.ts (transport only) | console/tests/api-parity.test.tsx#client exposes no state store or cache; console.test.tsx#keeps no authoritative state | — | console reconstructs every value from the API on reload |
| **FR-049** | When a run requires human clarification (FR-028) or human approval (FR-029, FR-043),… | COVERED | T076,T078,T079,T082 | engine/state.py (WAITING_FOR_HUMAN), engine/clarifications.py | failure/test_waiting_quiescence.py (5); workflow/test_ambiguity_halt.py#test_run_is_waiting_for_human | — | no thread, timer or background worker while waiting |
| **FR-050** | The approver identity MUST be one that no agent can act under. The system MUST reject… | COVERED | T061,T064,T076 | engine/identity.py (APPROVER_ROLE), api/deps.py (server-side directory) | failure/test_approval_integrity.py#test_agent_identity_can_never_hold_the_approver_role; integration/test_console_api.py#test_client_cannot_grant_itself_the_approver_role | HUMAN task T061/T064 | roles come from a server-side directory, never from the request |
| **NFR-001** | At the nominal operating point defined in NFR-005 — 100 redirects per second sustained… | COVERED | T098 | service/LinkService.java, db/migration/V2 (indexed lookup) | perf/loadgen.py profiles A and B (T098) | — | p95 6.82/6.62 ms vs 150 ms budget; p99 10.84/11.64 ms vs 400 ms — perf/baseline-2026-08-20.md |
| **NFR-002** | The redirect path remains available independently of the analytics and orchestration… | COVERED | T014,T093 | application.yaml — separate redirect-pool and analytics-pool | failure/RedirectRecordingFailureTest (3) | plan.md:186 **authoritative approver ruling on NFR-002** | separate services, separate databases, separate pools |
| **NFR-003** | No acknowledged link creation and no recorded workflow transition is lost across… | COVERED | T013,T045 | Flyway migrations; store/repository.py transactional writes | workflow/test_resume.py#test_every_transition_is_persisted, #test_resume_does_not_re_execute_completed_work | — | no acknowledged creation or transition lost across restart |
| **NFR-004** | Audit records are append-only and retained for the life of the deliverable; any run can… | COVERED | T031,T034,T095 | store/repository.py (no update/delete path), ops/db/02-apply-runtime-grants.sql | integration/test_store_shape.py#test_audit_repository_exposes_no_mutation_path; failure/test_lineage_and_rollback.py#test_runtime_role_cannot_update_delete_or_truncate_audit | T006/T007 HUMAN-executed | INSERT/SELECT only for the runtime role, verified against a live cluster |
| **NFR-005** | The shortener sustains at least 100 redirects per second against at least 100,000… | COVERED | T098 | V2__short_links.sql (simple indexed table) | perf/run_baseline.sh (100k links, 100 rps, 120 s x 2 profiles) | — | 100.0 rps sustained, 0 errors across 24,000 redirects |
| **NFR-006** | All external input is validated and normalised at the boundary; secrets never appear in… | COVERED | T006,T025 | DestinationValidator.java, agent/config.py, ops/db/*.sql | unit/DestinationValidatorTest; failure/test_egress_boundary.py; failure/test_audit_secret_safety.py | T006/T007 HUMAN-executed four-role model | least privilege verified live; T102 human security review still to run |
| **NFR-007** | Every orchestration action and every shortener error path emits a structured,… | COVERED | T008,T011 | trace/correlation.py, shortener trace/Correlation.java | unit/CorrelationTest#fieldNamesMatchTheContract, #childKeepsTheTraceAndStartsANewSpan | contracts/correlation.md | run_id/trace_id/span_id on every audited action |
| **NFR-008** | Components are independently testable with injectable dependencies and no hidden global… | COVERED | T101 | injectable dependencies throughout; no module-level state (console asserted by test) | console/tests/api-parity.test.tsx#client exposes no state store or cache; console.test.tsx#keeps no authoritative state | — | docs/HLD.md, docs/LLD.md (§17 documents rationale for all six public interfaces), README.md |
| **NFR-009** | Every orchestration run declares a ceiling on wall-clock duration and on retry… | COVERED | T049,T053,T082,T090 | engine/bounds.py, agent/sandbox.py (SandboxLimits.wall_clock_seconds) | failure/test_bounds.py#test_max_attempts_exhausted_raises_and_stops; failure/test_sandbox_escape.py#test_wall_clock_timeout_terminates_execution | — | wall-clock and attempt ceilings enforced, safe-stop on exceed |
| **SC-001** | A person can turn a long destination into a working short link and follow it to that… | COVERED | T022 | shortener create + resolve path (LinkController, RedirectController) | ops/smoke/t022-path-check.sh (pre-flight); six post-session database and resolve checks | **T022 HUMAN-executed 2026-08-20** | baseline.md — untrained participant, unaided, approximately 0.5 s against a 30 s budget; link `Ii2L2v2` verified end to end (human-provided timing) |
| **SC-002** | With 100,000 links stored and 100 follows per second sustained, 95% of link follows… | COVERED | T098 | — | perf/loadgen.py profiles A and B | — | PASS with ~22x headroom on p95, ~34x on p99 — perf/baseline-2026-08-20.md |
| **SC-003** | 100% of submitted destinations using a non-HTTP(S) scheme are refused, with zero such… | COVERED | T018 | validation/DestinationValidator.java | unit/DestinationValidatorTest#rejectsEverySchemeOutsideTheAllowList | — | 100% of non-HTTP(S) schemes refused; zero created |
| **SC-004** | Every distinct failure condition — unknown, expired, malformed, revoked, conflicting… | COVERED | T009,T016,T029 | web/errors/ErrorCode.java | unit/ErrorCodeTest#everyIdentifierIsDistinct; contract/OpenApiParityTest#everyNonDeferredErrorIdentifierIsReachable | — | every failure distinguishable without parsing prose |
| **SC-005** | Across 10,000 link creations, zero code collisions result in an existing link being… | COVERED | T019 | domain/CodeGenerator.java (bounded collision retry) | integration/CodeUniquenessTest#concurrentCreationNeverOverwritesAnExistingLink | — | zero overwrite/reassignment under concurrent creation |
| **SC-006** | Reported click counts match the number of successful redirects exactly, with no over-… | COVERED | T028,T091 | service/LinkService.java#resolveAndCount (single durable transaction) | contract/RedirectContractTest#everySuccessfulRedirectIsCountedBeforeTheResponse; failure/RedirectRecordingFailureTest#theCounterAndTheEventStayConsistentAfterAFailure | — | T098: 26,801 events == 26,801 counted, across 24,000+ redirects including skew |
| **SC-007** | The greenfield requirement is delivered end to end by the orchestration system, and… | COVERED | T063 | audit/trace.py | failure/test_lineage_and_rollback.py#test_requirement_to_task_to_change_to_test_round_trip, #test_a_change_with_no_requirement_is_reported_as_untraceable | — | this document; plus the automated matrix check |
| **SC-008** | A run containing at least two independent tasks demonstrably executes them… | COVERED | T040 | engine/scheduler.py, graph/sync.py | workflow/test_parallel_sync.py#test_independent_tasks_execute_concurrently, #test_sync_node_waits_for_every_inbound_branch | — | observed concurrency then synchronised release |
| **SC-009** | 100% of architecture, security, destructive, and release checkpoints in a run halt for… | COVERED | T061 | engine/approvals.py | failure/test_approval_integrity.py#test_agent_cannot_self_approve, #test_approval_permits_only_the_pending_action | plan.md § Gate II | zero checkpoints proceed without a recorded approver decision |
| **SC-010** | The deliberately ambiguous requirement produces zero implementation tasks and zero code… | COVERED | T077 | engine/ambiguity.py | workflow/test_ambiguity_halt.py#test_ambiguous_requirement_halts_and_creates_no_tasks, #test_questions_are_specific_rather_than_a_general_complaint | — | 0 tasks, 0 changes, >=1 specific answerable question |
| **SC-011** | On an upstream change during the brownfield run, the system re-plans strictly the… | COVERED | T084,T088 | engine/replan.py | workflow/test_selective_replan.py#test_one_change_invalidates_only_its_dependency_closure, #test_unaffected_successful_nodes_remain_succeeded, #test_the_whole_dag_is_not_rebuilt | — | only the affected subgraph is replanned |
| **SC-012** | An interrupted run resumes with zero completed tasks re-executed and zero lost state… | COVERED | T042,T045 | engine/state.py, store/repository.py | workflow/test_resume.py#test_resume_does_not_re_execute_completed_work, #test_every_transition_is_persisted | — | zero re-execution, zero lost transitions |
| **SC-013** | Any completed run can be fully reconstructed from its audit trail alone — actions,… | COVERED | T095 | store/repository.py, audit/trace.py | failure/test_lineage_and_rollback.py; integration/test_store_shape.py#test_audit_append_and_read_back | — | run reconstructable from the trail alone |
| **SC-014** | Success rate, retry frequency, rollback frequency, MTTR, and end-to-end latency are… | COVERED | T094 | audit/metrics.py | integration/test_metrics.py#test_metrics_agree_with_independently_observed_outcomes | — | metrics cross-checked against independently observed outcomes |
| **SC-015** | Zero secrets or personal data appear in audit records, logs, or metrics across all… | COVERED | T096 | store/repository.py#_reject_secrets | integration/test_metrics.py#test_metrics_carry_no_secrets_or_personal_data; failure/test_audit_secret_safety.py | — | T099 planted sentinel credentials; none reached any record |
| **SC-016** | No automated operation in any demonstration run retries unboundedly; every failure… | COVERED | T086 | engine/bounds.py | failure/test_bounds.py#test_backoff_is_bounded_and_never_unbounded, #test_no_attempt_occurs_after_exhaustion | — | every failure ends in fallback, rollback or safe-stop |
| **SC-017** | Zero outbound requests to caller-supplied destinations occur across all demonstration… | COVERED | T015,T046,T048,T056,T099 | agent/config.py (guard), agent/sandbox.py (--network none) | failure/EgressTest.java; failure/test_egress_boundary.py (14); failure/test_sandbox_escape.py; failure/test_integration_sandbox_topology.py (8) | T015 HUMAN network-boundary review | T099: real listener saw zero requests; real DNS/connect denials — docs/security/egress-verification.md |
| **SC-018** | 100% of agent-authored changes are revertible, demonstrated by reverting at least one… | COVERED | T085 | engine/rollback.py, agent/changes.py | failure/test_rollback.py#test_modified_file_is_restored_byte_identical | — | revert demonstrated, prior state restored exactly |
| **SC-019** | Zero task nodes change execution mode from human-executed to agent-authored during… | COVERED | T047 | engine/decompose.py (frozen fields) | failure/test_mode_escalation.py#test_mode_cannot_be_escalated_after_planning | HUMAN task T047 | zero mode escalations possible by construction |
| **SC-020** | A reviewer who did not observe a run can, from the console alone, identify its current… | COVERED | T074 | console/src/views/RunView.tsx, HumanActionView.tsx | console.test.tsx#displays pending approvals and clarifications with their context, #submits a clarification answer and re-reads the run | — | state identifiable, checkpoint approvable, clarification answerable from the console alone |
| **SC-021** | A run left in WAITING_FOR_HUMAN consumes zero compute attributable to it, survives a… | COVERED | T078,T079 | engine/state.py (WAITING_FOR_HUMAN) | failure/test_waiting_quiescence.py (5): no thread, no timer, no background worker, never expires into autonomous execution | — | zero compute while waiting; survives restart |

## 3. Representative lineage chains

Eight chains, one per behaviour class T100 names. Each is `requirement → interpretation → task →
decision → change → test → result → audit`.

### 3.1 Greenfield shortener — FR-007 (redirect to the exact stored destination)

`FR-007` → clarified in spec § Clarifications (redirect is temporary and non-cacheable) →
`T017` (test first), `T027` (implementation) → no approval required, a bounded task inside
approved scope → `service/LinkService.java#resolveAndCount` + `web/RedirectController.java` →
`contract/RedirectContractTest` (5 tests) → **302 with exact `Location`, `Cache-Control:
no-store`** → verified again under load in `perf/baseline-2026-08-20.md` (24,000 redirects, zero
errors).

### 3.2 Ambiguous requirement — FR-028 / SC-010

`FR-028` → `T076`–`T083` → `engine/ambiguity.py` detects, `engine/clarifications.py` persists
the question against the requirement → run transitions to `WAITING_FOR_HUMAN`, **zero tasks and
zero code changes created** → the human answer is persisted *before* resume, carrying actor and
timestamp → re-interpretation uses the answer → `workflow/test_ambiguity_halt.py` (18 tests),
including `test_answer_is_persisted_before_the_run_resumes` and
`test_clarification_rounds_are_bounded_and_end_in_safe_stop` → every transition audited
(`test_every_transition_is_audited`).

### 3.3 Brownfield selective replan — FR-033 / SC-011

`change_request` persisted and linked to the prior run → `graph/builder.py` computes the
dependency closure → only that closure is marked stale; unaffected `SUCCEEDED` nodes keep their
state and are not re-executed → replacement nodes link to what they supersede, and prior results
stay queryable → execution mode is recalculated but **never silently escalated** →
`replan_event` + `decision_record` capture the whole decision →
`workflow/test_selective_replan.py` (18 tests), including
`test_the_whole_dag_is_not_rebuilt` and `test_restart_preserves_stale_and_replacement_lineage`.

### 3.4 Architecture approval — FR-029 / FR-050 / SC-009

The governing instance is the delivery's own: **plan.md § Gate II, APPROVED 2026-08-18 by the
requirement owner** with seven recorded rationale points, after two rejected revisions. No agent
recorded it. In the runtime the same rule is mechanical: `engine/identity.py` refuses the
approver role to any `agent:` identity, `api/deps.py` sources roles from a server-side directory
so a client cannot assert its own, and an approval authorises only the exact pending action.
Evidence: `failure/test_approval_integrity.py` (9) and the approval group of
`integration/test_console_api.py`.

### 3.5 Safe-stop — FR-031 / NFR-009

Declared `OperationPolicy` (frozen, never handed to the operation) → attempts exhausted or the
sandbox is unavailable → declared fallback `SAFE_STOP` → run halts, **state preserved**, reason
audited, and it is explicitly *not* counted as a retryable violation. Proven against real
runtime conditions in T099:
`failure/test_fail_closed_real.py#test_real_unreachable_daemon_safe_stops_and_preserves_state`
with `DOCKER_HOST` pointed at a socket that does not exist.

### 3.6 Rollback — FR-032 / FR-044 / SC-018

`agent/changes.py` captures prior state before an atomic write, producing a `ChangeRecord` →
`engine/rollback.py` restores it → `rollback_event` records the attempt and its outcome, linked
to the original change → a failed rollback safe-stops rather than continuing →
`failure/test_rollback.py` (6) and
`failure/test_lineage_and_rollback.py#test_successful_rollback_links_to_the_original_change`.
Refusal to clobber a later edit is tested, so "revertible" does not degrade into "overwrite".

### 3.7 Bounded retry — FR-030 / SC-016

Timeout, max attempts and backoff declared *before* the operation runs; the policy is immutable
and the executing operation cannot widen its own budget; backoff is capped rather than doubling
forever; no attempt occurs after exhaustion; attempts survive restart.
`failure/test_bounds.py` (16).

### 3.8 Sandbox and egress denial — FR-041 / SC-017

Model-visible surface is exactly four tools, with no MCP connector and no server-side tool —
re-verified in T099 against the real request payload. Agent-authored code runs in an ephemeral
container: `--network none`, non-root, `cap-drop ALL`, no Docker socket, disposable surface copy.
The orchestrator process additionally enforces an egress allow-list. Evidence:
`failure/test_capability_boundary.py` (14), `failure/test_sandbox_escape.py` (15),
`failure/test_egress_boundary.py` (14), `failure/test_integration_sandbox_topology.py` (8), and
`docs/security/egress-verification.md`.

## 4. Deferred register — verified absent

Every deferral was checked against the code, not against the register.

| Capability | Requirement | Where approved | Verified absent by | Not a blocker because |
|---|---|---|---|---|
| Custom aliases | **FR-005** | tasks.md § Deferred Capabilities; plan.md § Delivery Scope | `OpenApiParityTest#approvedDeferralsRemainAbsent` — the document contains no `alias`; `#deferredIdentifiersAreDeclaredButUnreachableThroughTheApi` | Generated codes fully satisfy creation and resolution; the conflict semantics are specified, so re-entry is one validation policy plus a conflict path |
| Creation rate limiting | **FR-015** | same | document contains no `rate_limit`; `RATE_LIMITED` unreachable through the API | No multi-tenant exposure in this submission; R8 already fixes the policy (60/min, burst 10) |
| Paginated event history | FR-014 (history half) | tasks.md § Deferred Capabilities | only four paths exist in the OpenAPI document; no history route | The analytics **summary** — the owner-scoped half the requirement leads with — is built and tested |
| Event retention sweep | FR-013 (retention half) | same | no `@Scheduled`, no `EnableScheduling` anywhere in `shortener/src/main` | Lifetime counters are independent of event retention, and that independence is tested |
| Monthly range partitioning | R14 mechanism | **removed** from the plan | `V2__short_links.sql` is a simple indexed table | T098 measured p95 6.8 ms with 100k links — partitioning would be complexity without a demonstrated requirement (Principle XI) |
| Regression exit-gate test | FR-026 (US4 scenario 5) | tasks.md § Deferred Capabilities | — | Gates themselves are built and tested (`workflow/test_gates.py`) |
| Brownfield plan-against-existing test | FR-033 (US4 scenario 1) | same | — | Selective replanning itself is built and tested (18 tests) |
| Console gates/replan/metrics/audit screens | FR-045, FR-047 | same | — | Every value is API-visible and surfaced in the Run view; FR-048 guarantees nothing lives only in the console |
| Redis | R13 | plan.md § Gate II (no Redis in greenfield) | no dependency in `pom.xml`, `pyproject.toml`, or `package.json`; appears only in `engine/replan.py` as the rung that must **not** be chosen without evidence, and in a test asserting the OpenAPI document never mentions it | T098 measured ~22× headroom on p95 — R13's first condition, a measured budget breach, is not met |

## 5. Task consistency findings

**104 tasks · 98 complete · 6 open** (T022, T100, T101, T102, T103, T104). No duplicate IDs.
Every one of the 79 requirements is cited by at least one task.

### 5.1 Ten completed tasks cite no requirement identifier

`T001`, `T002`, `T003`, `T004`, `T005`, `T010`, `T020`, `T050`, `T058`, `T060` reference research
decisions (`R4`, `R15`), Constitution principles (`IV`, `X`), or plan sections instead of an
FR/NFR/SC id. tasks.md's own format rule calls `(REQ)` **mandatory** under Principle III and says
"a task with no requirement is out of scope (FR-035)". These are setup, toolchain and sandbox
tasks that plainly serve the delivery, so this is a **bookkeeping violation of the project's own
rule, not out-of-scope work** — but by the letter of FR-035 they should carry a requirement id.

### 5.2 Twenty-nine completed tasks name files that do not exist at the path given

Three classes, in increasing severity:

* **Shorthand (benign, 14 references).** Java paths omit the `com/schwab/shortener` package
  segment (`shortener/src/test/java/contract/LinkContractTest.java`) or elide it as `.../`;
  contract paths omit the `specs/001-agentic-url-shortener/` prefix. Every one resolves.
* **Consolidated during implementation (real drift, 12 references).** The behaviour exists and is
  tested, in a different file than the task names:

  | Task | Names | Actually lives in |
  |---|---|---|
  | T063 | `tests/workflow/test_traceability.py` | `tests/failure/test_lineage_and_rollback.py` |
  | T095 | `tests/integration/test_audit_reconstruction.py` | `test_lineage_and_rollback.py`, `test_store_shape.py` |
  | T096 | `tests/integration/test_no_secrets.py` | `test_metrics.py`, `test_audit_secret_safety.py` |
  | T061 | `tests/workflow/test_approvals.py` | `tests/failure/test_approval_integrity.py` |
  | T062 | `tests/failure/test_governance_guardrails.py` | `test_guardrails.py`, `test_governance_protection.py` |
  | T078 | `tests/workflow/test_waiting_persistence.py` | `tests/failure/test_waiting_quiescence.py` |
  | T080 | `tests/integration/test_clarification_resume.py` | `tests/workflow/test_ambiguity_halt.py` |
  | T086 | `tests/failure/test_bounded_operations.py` | `tests/failure/test_bounds.py` |
  | T066 | `src/engine/changes.py` | `src/agent/changes.py` |
  | T068 | `src/audit/events.py` | `src/store/repository.py` (`AuditRepository`) |
  | T082 | `src/engine/waiting.py` | `src/engine/state.py`, `engine/clarifications.py` |
  | T087 | `src/graph/blast_radius.py` | `src/graph/builder.py` (closure), `engine/replan.py` |
  | T091/T092/T093 | `AnalyticsSummaryTest`, `AnalyticsService`, `AnalyticsController` | `AnalyticsAndRevokeTest`, `LinkService`, `LinkController#analytics` |
  | T018 | `SchemeRejectionTest` | `DestinationValidatorTest#rejectsEverySchemeOutsideTheAllowList` |
  | T006/T007 | `ops/db/provision.sql` | `ops/db/provision.sh` + `01-provision-cluster.sql` + `02-apply-runtime-grants.sql` (an approved change) |

* **Genuinely absent (1).** `specs/001-agentic-url-shortener/baseline.md`, referenced by both
  T098 and T022, was never created — T098's results went to `perf/baseline-2026-08-20.md`
  instead. This is the artifact SC-001's gap turns on.

**No completed task was found whose behaviour is unimplemented or untested.** In every case the
work exists; the task text points at the wrong filename.

### 5.3 HUMAN attribution is correct

22 completed `[HUMAN]` tasks. T006/T007 (database provisioning) were explicitly authorised and
executed with the owner in the loop. Checkpoint 2d (T046–T062) carries an explicit block:
*"Capability-boundary decisions are HUMAN-APPROVED (2026-08-18) … implementation below is
agent-assisted under that approved boundary. No architecture approval was recorded by an agent;
Gate II is untouched."* **No agent is recorded anywhere as approving architecture, security or
governance** — checked in tasks.md, plan.md, and enforced at runtime by
`test_agent_identity_can_never_hold_the_approver_role`.

## 6. Documentation drift

Reporting only drift confirmed by execution or by file inspection.

### 6.1 Two of three shortener CI steps fail — **fixed**

`.github/workflows/ci.yml` selected tests with `-Dtest='com.schwab.shortener.unit.*'` and
`-Dtest='com.schwab.shortener.contract.*'`. Both were run and both fail:

```
No tests matching pattern "com.schwab.shortener.unit.*" were executed!
No tests matching pattern "com.schwab.shortener.contract.*" were executed!
```

Surefire treats an empty selector as an error, so the shortener job could never have gone green —
which means **the Java OpenAPI contract-parity gate built in T030 was not actually running in
CI**. Corrected to `'**/unit/*Test'` (27 tests) and `'**/contract/*Test'` (44 tests), both
verified locally.

### 6.2 The orchestrator's `unit` test layer is effectively empty — **reported, not fixed**

`pytest orchestrator/tests -m unit` collects **one** test: `test_health_endpoint`, which lives in
`tests/integration/` and exercises an HTTP endpoint. Of 316 orchestrator tests, the marker
distribution is `failure` 17 files, `integration` 16, `workflow` 8, `contract` 1, `unit` 1.

Two consequences: the CI "Unit" step passes vacuously, and the sandbox's
`(ORCHESTRATOR, UNIT)` command — which
`test_run_tests_end_to_end.py#test_orchestrator_unit_tests_run_in_the_real_sandbox` asserts
"passed" on — is a one-test run. The orchestrator's logic *is* covered, at the workflow and
failure layers; what is missing is the layer Principle IV names separately. Not fixed here:
adding tests is implementation, which T100 excludes.

### 6.3 Checked and consistent

* **data-model.md ↔ migrations.** All 19 declared entities reconcile: 18 tables exist,
  `sync_node` is correctly documented as "a `task_node` with `is_sync = true`" and matches
  `001_init.sql`, and `rate_limit_window` is correctly absent and marked `DEFERRED_APPROVED`.
* **contracts ↔ implementation ↔ OpenAPI.** Both parity suites pass, both are CI-gated, and both
  were previously proven to fail on injected drift. Shortener paths are exactly the four
  declared; the orchestrator's declared and implemented operation sets match.
* **`app.py` docstring** still says "Health only. The `/v1` routes land in checkpoint 2f, which
  is out of scope for this run" while the file includes the full router. Cosmetic; noted for
  T101 rather than changed here.

## 7. Automated consistency check

`orchestrator/tests/contract/test_traceability_matrix.py` (marker `contract`, so it runs in the
existing CI parity step) fails the build when:

1. a requirement in spec.md is **missing from the matrix**, or appears more than once;
2. a matrix row carries anything other than exactly one of the three classifications;
3. a **task id** referenced by the matrix does not exist in tasks.md;
4. a requirement classified `GAP` is not in the declared gap list — a *new* silent gap breaks the
   build, while the two known gaps are pinned and must be removed from the list when closed;
5. a `DEFERRED_APPROVED` requirement **becomes implemented** without the register being updated —
   checked by probing for the capability itself (alias and rate-limit surfaces), not by trusting
   the register;
6. a `DEFERRED_APPROVED` requirement loses its citation in tasks.md § Deferred Capabilities.

## 8. Final submission audit (T100 close)

T100 was deliberately held open until the three human gates and the human Constitution
re-evaluation had landed, so that the audit closes against the released state rather than a
mid-flight one. All four are now complete.

### 8.1 Human gates

| Task | Mode | Outcome |
|---|---|---|
| **T022** | `[HUMAN]` | Time-to-first-success. Untrained participant, unaided, **approximately 0.5 seconds** against SC-001's 30-second budget. Timing human-provided; link `Ii2L2v2` independently verified end to end. `specs/…/baseline.md` |
| **T102** | `[HUMAN]` | Security review. **APPROVED WITH CONDITIONS.** 51 controls: 47 PASS, 4 ACCEPT-RISK, 0 FAIL; ten accepted risks; six binding conditions. `docs/security/security-review.md` |
| **T103** | `[HUMAN]` | Quickstart validation. **PASS after two invalidated attempts.** Six README corrections; no runtime defect found. `docs/validation/quickstart-validation.md` |
| **T104** | `[HUMAN]` | Constitution re-evaluation. **PASS — release-ready for the take-home prototype.** 13 gates: 12 PASS, 1 N-A, 0 FAIL. Gate II valid, no re-approval. `docs/validation/constitution-review.md` |

### 8.2 Final verification, re-executed at close

| Check | Result |
|---|---|
| Spec requirements vs matrix rows | **79 vs 79**, none unclassified |
| Classification | **77 COVERED · 2 DEFERRED_APPROVED · 0 GAP** |
| Tasks complete | **104 / 104** |
| HUMAN tasks complete | **26**, all human-attributed |
| Records of an agent approving anything | **0** |
| Deferred capabilities absent from the shortener OpenAPI (`alias`, `rate_limit`, `retention`, `redis`) | **0 occurrences** |
| Redis in any dependency manifest | **0** |
| Orchestrator — unit/workflow/failure/contract | **280 passed** |
| Orchestrator — integration (real PostgreSQL) | **176 passed** |
| Console — vitest / typecheck | **49 passed** / *No errors found* |
| Shortener — unit layer | **27 tests, 0 errors** |

### 8.3 Findings carried into submission

Three accepted by the human reviewer at T104, recorded here so they remain visible:

1. **Ten completed tasks cite research decisions rather than `(REQ)` ids** — ACCEPTED as supporting
   and architecture tasks. Requirement ids must **not** be back-fitted for cosmetic traceability.
2. **The orchestrator `unit` marker selects one test, itself misfiled** — ACCEPTED as a
   test-organization limitation, not a validation gap. Unit-test counts must **not** be
   manufactured for appearance.
3. **T102 remains APPROVED WITH CONDITIONS** — all ten accepted risks and six binding conditions
   in force, for the **local take-home prototype only**, not for shared or production deployment.

Plus one observation from this audit, disclosed rather than dismissed:

4. **One intermittent test failure was observed once and did not reproduce.** The first execution of
   the orchestrator unit/workflow/failure/contract selection reported `1 failed, 279 passed`; four
   subsequent full runs of the same selection each reported **280 passed**. **The failing test's
   identity was not captured** — the output was not retained before re-running — so it cannot be
   named here. The layer contains container- and timing-sensitive tests (real Docker sandboxes,
   wall-clock timeouts), which is the most likely source. Recorded as **known intermittency of
   unknown identity**, not as a passing result.

### 8.4 Audit conclusion

Every requirement is either implemented and tested, or formally deferred with an approved register
entry. **There is no GAP.** Bidirectional traceability holds in both directions and is enforced on
every build by `test_traceability_matrix.py`, which fails if a requirement leaves the matrix, a
cited task id stops existing, a new gap appears, or a deferred capability ships without the
register being updated.

**T100 closes: 79 requirements, 77 COVERED, 2 DEFERRED_APPROVED, 0 GAP.**

---

## 9. Outstanding items

**None.** T102, T103 and T104 are complete, and T100 closes with this revision. The two findings
that were awaiting a decision — the ten tasks missing a `(REQ)` identifier (§5.1) and the thin
orchestrator `unit` layer (§6.2) — were **accepted by the human reviewer at T104** and are recorded
in §8.3 as standing constraints rather than open work.

Release readiness was a human judgement and was exercised as one: **PASS, release-ready for the
take-home prototype**, `docs/validation/constitution-review.md` §5.
