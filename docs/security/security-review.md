# Security review — evidence package (T102)

**Prepared:** 2026-08-20 · **Task:** T102 `[HUMAN]` · **Status: REVIEWED AND APPROVED WITH CONDITIONS by the human reviewer, 2026-08-20** — see §7

> **Evidence assembled by an agent; reviewed and decided by a human.** §1–§6 were prepared by an
> agent to make the review efficient. The decision in §7 — including the acceptance of every risk
> in §5 and the six conditions attached to it — was made by the human reviewer on 2026-08-20.
> **No agent made, influenced, or recorded that decision on the reviewer's behalf.**

Findings below were **verified by execution**, not read from source, wherever execution was
possible. Where a control is asserted only by inspection or by test, that is stated.

---

## 1. Review scope

**In scope:** the implemented system on this branch — Java shortener, Python orchestrator, React
console, PostgreSQL provisioning, the bounded agent runtime and its sandbox, and the egress
boundary. Reviewed against the approved security requirements (FR-018, FR-029, FR-039–FR-044,
FR-050, NFR-004, NFR-006) and Constitution Principles II, V, VII and XII.

**Out of scope:** production deployment topology, TLS termination, secret-manager integration,
identity-provider integration, host hardening, network appliances, and supply-chain review of
third-party dependencies. None of these is part of the deliverable; §5 records what that means.

**Method:** a throwaway PostgreSQL cluster was provisioned with the real `ops/db/provision.sh`,
migrated as the owner roles, granted with `provision.sh grants`, and then attacked — cross-database
connection attempts, audit mutation attempts, and a privilege-escalation attempt. The shortener was
exercised live on `:8080`. The agent tool payload and egress policy were built in-process and
inspected. 153 security-relevant automated tests were run.

## 2. Threat model

| # | Threat | Primary control | Residual |
|---|---|---|---|
| T1 | Agent exceeds its mandate — installs a datastore, deploys, rewrites history | Four-tool surface; no shell/git/package tool exists | §5.3 |
| T2 | Agent-authored code escapes at test time — exfiltrates, reaches the host, mutates the repo | Ephemeral container, `--network none`, disposable copy | Low |
| T3 | Agent self-approves, or an approval is reused for a different action | Server-side role directory; `agent:` refused; fingerprint binding | Low |
| T4 | Audit trail altered to conceal an action | `INSERT`/`SELECT` only for the runtime role, at the database | Low |
| T5 | Orchestrator exfiltrates data to an arbitrary host | Egress allow-list | §5.2 — raw-socket bypass |
| T6 | Shortener becomes an open redirect or an SSRF pivot | Scheme allow-list; stored-destination-only redirect; no server-side fetch | Low |
| T7 | Credentials leak into logs, audit records, or errors | Key- **and** value-side secret rejection; URL redaction | Low |
| T8 | Analytics or orchestration outage takes the redirect path down | Separate services, databases, pools | Low |
| T9 | Caller impersonates another client or an approver | Owner scoping enforced; roles server-side | **§5.1 — accepted** |
| T10 | Unbounded agent loop consumes budget or blocks indefinitely | Declared bounds; frozen policy; safe-stop | §5.3 |

**Trust boundaries.** Untrusted: the model's output, agent-authored code, all HTTP request bodies
and headers. Semi-trusted: operator-supplied configuration (`ANTHROPIC_BASE_URL`,
`ORCHESTRATOR_DB_URL`). Trusted: the provisioned database roles, the sandbox images, this repository.

## 3. Control checklist

Legend: **VERIFIED** = executed this review · **TESTED** = automated test, run and passing ·
**INSPECTED** = source/config read · **ACCEPTED RISK** = §5.

### 3.1 Service and database isolation

| Control | Result | Evidence |
|---|---|---|
| `shortener_app` cannot reach `orchestrator_db` | **VERIFIED** | `FATAL: … User does not have CONNECT privilege` |
| `orchestrator_app` cannot reach `shortener_db` | **VERIFIED** | same, reciprocally |
| Each app role reaches its own database | **VERIFIED** | positive control — both returned OK |
| Runtime roles hold no DDL | **VERIFIED** | `CREATE TABLE` and `DROP TABLE` both refused |
| `audit_event` UPDATE denied | **VERIFIED** | `ERROR: permission denied for table audit_event` |
| `audit_event` DELETE denied | **VERIFIED** | same |
| `audit_event` TRUNCATE denied | **VERIFIED** | same |
| `audit_event` INSERT/SELECT permitted | **VERIFIED** | `INSERT 0 1`; append-only, not read-only |
| Runtime role cannot grant itself UPDATE | **VERIFIED** | see the note below |
| Code path exposes no audit mutation method | **TESTED** | `test_audit_repository_exposes_no_mutation_path` |

> **Note for the reviewer — a result that looks alarming and is not.** Issuing
> `GRANT UPDATE ON audit_event TO orchestrator_app` **as `orchestrator_app`** returns the string
> `GRANT` rather than an error. PostgreSQL reports success while granting nothing when the role
> lacks `GRANT OPTION`. The privilege matrix immediately afterwards is unchanged —
> `select=t insert=t update=f delete=f truncate=f` — and a subsequent `UPDATE` on a row the role
> had just inserted was refused. **No privilege escalation.** It is recorded because a reviewer
> running the same command would otherwise reasonably read `GRANT` as success.

Four roles, two databases, no credential spanning both. Audit immutability is therefore a
**database privilege**; `AuditRepository` exposing no mutation method is the second layer.

### 3.2 Authentication and authorization

| Control | Result | Evidence |
|---|---|---|
| `X-Actor-Roles` is not trusted | **TESTED** | `test_client_cannot_grant_itself_the_approver_role` |
| Approver role is server-side configured | **INSPECTED** | `api/deps.py#role_directory` reads `ORCHESTRATOR_APPROVERS`; identity from the header, roles never |
| No agent identity can hold the approver role | **TESTED** | `test_agent_identity_can_never_hold_the_approver_role`; ids prefixed `agent:` are filtered out of the directory itself |
| Agent cannot approve its own action | **TESTED** | `test_agent_cannot_self_approve` |
| Approval is `action_fingerprint`-bound | **TESTED** | `test_approval_permits_only_the_pending_action`, `test_approval_authorises_only_its_own_fingerprint` — SHA-256 over canonical JSON |
| Rationale mandatory | **TESTED** | `test_approval_requires_a_rationale` |
| Double-decision refused | **TESTED** | `test_a_request_cannot_be_decided_twice` |
| Rejection authorises nothing | **TESTED** | `test_rejected_approval_authorises_nothing` |
| Unauthenticated caller refused | **VERIFIED** | shortener create without `X-Client-Id` → **401** (not 403 — absent identity and insufficient permission are distinct) |
| Demo-identity limitation documented | **INSPECTED** | `api/deps.py` module docstring; HLD §17; §5.1 below |

**9/9 approval-integrity tests pass.**

### 3.3 Agent tool boundary

Built in-process and inspected:

```
TOOL_NAMES         : ('read_file', 'write_file', 'run_tests', 'report')
declared in request: ['read_file', 'write_file', 'run_tests', 'report']
top-level keys     : ['betas','max_tokens','messages','model','output_config','system','thinking','tools']
mcp_servers present: False
run_tests schema   : {"layer": {"enum": ["unit","integration","workflow","failure"]}},
                      "additionalProperties": false
```

| Control | Result |
|---|---|
| Exactly four model-visible tools | **VERIFIED** |
| No shell / exec tool | **VERIFIED** — no such token anywhere in the serialised payload |
| No git tool | **VERIFIED** |
| No package-installation tool | **VERIFIED** — and writing a manifest raises `CheckpointCrossing`, not a violation |
| No network/HTTP tool | **VERIFIED** |
| No MCP connector | **VERIFIED** — `mcp_servers` absent |
| No server-side tool (`web_search`, `web_fetch`, `code_execution`) | **VERIFIED** — never declared |
| `run_tests` takes an enum, never a command | **VERIFIED** — `additionalProperties: false` |
| Test commands are argv tuples, never strings | **TESTED** | `test_test_commands_are_argv_tuples_never_strings` — no shell in the path |
| No unrestricted filesystem access | **TESTED** — 14 `test_capability_boundary` tests |

### 3.4 Sandbox controls

| Control | Result | Evidence |
|---|---|---|
| Ephemeral container, discarded every path | **TESTED** | `test_the_copy_is_discarded_after_the_run` |
| `--network none` for normal execution | **TESTED** | `test_agent_test_code_cannot_reach_arbitrary_internet_hosts`, `test_dns_resolution_is_unavailable` |
| Disposable copy; authoritative repo never mounted | **TESTED** | `test_mutations_do_not_propagate_to_the_authoritative_repository` — host file byte-identical after tampering |
| `assert_disposable` refuses the real tree | **TESTED** | `test_running_against_the_authoritative_repository_is_refused` |
| No Docker socket | **TESTED** | `test_docker_socket_is_not_mounted`; also from the integration runner |
| No host home or secrets | **TESTED** | `test_host_home_and_secrets_are_not_reachable` — asserts on key *material*, not paths |
| No other surface, no `ops/`, no `.git/` | **TESTED** | three separate tests |
| Non-root, `no-new-privileges` | **TESTED** | `test_container_is_not_privileged_and_cannot_gain_privileges` — `NoNewPrivs: 1` |
| Resource limits (cpu/mem/pids/wall-clock/output) | **TESTED** | four tests incl. real timeout kill |
| Integration DB on an `--internal` network, no internet | **TESTED** | 8 topology tests, with a bridge-network control proving the probes work |
| Fails closed when Docker or image unavailable | **TESTED** | `test_fail_closed_real` — real unreachable daemon |
| Never falls back to host execution | **TESTED** | a `subprocess.run` interceptor confirms no non-`docker` process ran |
| Runtime cannot build or pull an image | **TESTED** | AST test over the runtime's docker argv |

**43 sandbox tests pass**, 23 of them against real containers.

### 3.5 Egress controls

Live policy, built in-process with a sentinel password in the DSN:

```
allow-list           : ['api.anthropic.com', 'db.internal']
permits example.com  : False
permits 192.168.1.50 : False        # LAN denied
password in repr     : False
```

| Control | Result |
|---|---|
| Claude host permitted | **VERIFIED** (this review) and **VERIFIED** live in T099 |
| Configured PostgreSQL host permitted | **VERIFIED** — derived from `ORCHESTRATOR_DB_URL`, so the guard and the app cannot disagree |
| Arbitrary DNS/hosts denied | **VERIFIED** — `EgressDenied(forbidden)` |
| LAN address denied | **VERIFIED** |
| Guard active in the real process | **TESTED** | `test_the_real_application_process_installs_the_guard` |
| No packet reaches a denied destination | **TESTED** | listener bound on a real address accepted nothing; with the guard removed the same connection succeeded |
| Credential-bearing URLs redacted | **TESTED** | `test_a_base_url_carrying_credentials_does_not_echo_them` |
| Value-side secret detection | **TESTED** | 5 `test_audit_secret_safety` tests |

> **The boundary that actually contains agent code is the container, not this guard.** The Python
> egress guard is **defense in depth for the orchestrator process only** — an accidental or injected
> outbound call from orchestrator code. It cannot bound a child process, and a raw
> `socket.socket().connect()` bypasses it by construction (§5.2). Agent-authored code is contained
> by `--network none` and, for integration tests, an `--internal` Docker network. A reviewer should
> read the guard as hygiene, and container networking as the control.

### 3.6 Input and output scope

| Control | Result | Evidence |
|---|---|---|
| `declared_inputs`/`declared_outputs` frozen after planning | **TESTED** | `test_planning_time_fields_are_frozen`, `test_outputs_cannot_be_widened_during_execution` |
| Declared sets are tuples, not appendable | **TESTED** | `test_declared_sets_are_tuples_and_cannot_be_appended_to` |
| Write allow-list is outputs only | **TESTED** | `test_write_allowlist_is_outputs_only_never_inputs_or_surface` |
| Traversal and symlink escape rejected | **TESTED** | `test_symlink_escape_is_resolved_and_refused` — containment checked on the **resolved** path |
| Cross-surface write rejected | **TESTED** | `test_write_to_another_surface_is_refused` |
| Governance trees unreadable and unwritable | **TESTED** | 15 `test_governance_protection` tests |
| Scope widening requires an approved SCOPE decision | **TESTED** | `test_scope_can_be_widened_only_by_an_approved_decision`, `test_rejected_scope_request_does_not_widen_scope` |
| Manifest write is a checkpoint, not a violation | **TESTED** | `test_write_to_build_manifest_is_a_checkpoint_not_a_violation` |

### 3.7 Workflow safety

| Control | Result |
|---|---|
| Bounds declared before the operation runs; policy frozen and never handed to it | **TESTED** — 16 `test_bounds` |
| Timeout enforced per attempt | **TESTED** |
| Backoff capped, never doubling forever | **TESTED** |
| Undeclared fallback cannot be invented after failure | **TESTED** |
| Attempts persisted per attempt; restart preserves the spent budget | **TESTED** |
| Safe-stop preserves state and is audited | **TESTED** — and verified against a real unreachable daemon |
| `WAITING_FOR_HUMAN` consumes no compute — no thread, timer or worker | **TESTED** — 5 tests |
| Never expires into autonomous execution | **TESTED** |
| Rollback restores byte-identically; refuses to clobber a later edit | **TESTED** — 6 tests |
| Failed rollback safe-stops rather than retrying blind | **TESTED** |
| Selective replan preserves unaffected work | **TESTED** — 18 tests |

### 3.8 URL shortener security behaviour — live on `:8080`

```
javascript:alert(1)      -> {"error":"invalid_scheme"}
data:text/html,<script>  -> {"error":"invalid_scheme"}
file:///etc/passwd       -> {"error":"invalid_scheme"}
ftp://x.com/a            -> {"error":"invalid_scheme"}
/relative                -> {"error":"malformed_url","message":"destination must be absolute"}
//scheme-relative        -> {"error":"malformed_url","message":"destination must be absolute"}
http://                  -> {"error":"malformed_url"}
2100-char URL            -> {"error":"url_too_long","message":"destination exceeds 2048 characters"}
```

| Control | Result |
|---|---|
| Invalid schemes rejected | **VERIFIED** — scheme checked *before* URI parsing, so `data:` reports `invalid_scheme`, not `malformed_url` |
| Malformed and oversize rejected with distinct identifiers | **VERIFIED** |
| **No open redirect** | **VERIFIED** — `GET /{code}?url=https://evil.example` → `Location: https://www.google.com` (the stored destination; the parameter is ignored) |
| Owner checks enforced | **VERIFIED** — analytics and revoke as a different client → **403**; as owner → **200** |
| Revoke effective immediately | **VERIFIED** — after revoke, resolve → **410** `{"error":"revoked"}` |
| Expiry distinct from unknown | **TESTED** | `expiredLinkIsDistinctFromUnknown` |
| **No server-side fetch of destinations — SSRF not introduced** | **VERIFIED** | `EgressTest` (5) — a real HTTP listener recorded **zero** requests across creation, resolution, analytics, revocation and rejection. `DestinationValidator` performs no reachability check by design |
| Redirect event persisted before the 302 | **TESTED** | `everySuccessfulRedirectIsCountedBeforeTheResponse`; commit precedes the response |
| Unrecordable redirect → 503 `redirect_not_recorded` | **TESTED** | `aRedirectWhoseAnalyticsWriteFailsIsNotServed` |

Because the server never dereferences a destination, **Constitution gate V-a (SSRF / private-address
controls) is correctly N-A for this feature**. Introducing any server-side fetch would reverse that
and require a new requirement, not an implementation decision.

### 3.9 Secrets and configuration

| Control | Result | Evidence |
|---|---|---|
| No committed secrets | **VERIFIED** | pattern scan over all tracked files — no API keys, AWS keys, private keys, or inline passwords in shipped source/config |
| No `.env`, `.pem`, `.key`, `.p12`, `id_rsa`, `.netrc` tracked | **VERIFIED** | `git ls-files` — none |
| Runtime config takes secrets from the environment | **INSPECTED** | `application.yaml`: `password: ${SHORTENER_DB_PASSWORD:}` — no default value |
| `.gitignore` present | **VERIFIED** | 33 lines |
| Secrets not printed in normal logs | **INSPECTED / TESTED** | provisioning passes passwords base64 over **stdin**, never argv; `_redacted()` strips URL userinfo before any error formatting |
| Audit refuses secret-bearing payloads | **TESTED** | key- and value-side; raises rather than redacting quietly |
| Metrics carry no secrets or personal data | **TESTED** | `test_metrics_carry_no_secrets_or_personal_data` |
| Sandbox environment carries no secrets | **TESTED** | `test_environment_carries_no_secrets` |
| Disposable passwords clearly non-production | **VERIFIED** | this review used `RevSO-notprod-1` … `RevOA-notprod-4` on a throwaway cluster, destroyed afterwards; the integration sandbox generates a per-run `secrets.token_urlsafe(24)` that lives only as long as its container |

## 4. Evidence index

| Source | Use |
|---|---|
| `docs/security/egress-verification.md` | T099 — live egress proof; four defects found and fixed |
| `docs/HLD.md` §7–§10, §16–§18 | Autonomy model, approval model, sandbox boundary, limitations |
| `docs/LLD.md` §5, §10, §11, §17 | Fingerprint flow, sandbox lifecycle, egress internals, interface rationale |
| `README.md` | Run/test instructions used to reproduce this review |
| `ops/db/provision.sh`, `01-provision-cluster.sql`, `02-apply-runtime-grants.sql` | Four-role model, executed live for this review |
| `ops/sandbox/Dockerfile.*`, `build-images.sh` | Non-root, secret-free images; build is provisioning, not runtime |
| `orchestrator/src/agent/{tools,client,allowlist,sandbox,testrunner,config,approval_hook}.py` | The capability boundary |
| `orchestrator/src/engine/{approvals,identity,guardrails,bounds,rollback}.py` | Approval and safety machinery |
| `orchestrator/src/store/repository.py` | Append-only audit, secret rejection |
| `shortener/.../validation/DestinationValidator.java`, `service/LinkService.java` | Input validation, redirect transaction |

**Automated security-relevant tests run for this review — 153 passed, 0 failed:**

| Suite | Tests | Suite | Tests |
|---|---|---|---|
| `test_capability_boundary` | 14 | `test_governance_protection` | 15 |
| `test_sandbox_escape` | 15 | `test_guardrails` | 14 |
| `test_sandbox_unavailable` | 5 | `test_halt_before_apply` | 5 |
| `test_fail_closed_real` | 5 | `test_mode_escalation` | 9 |
| `test_egress_boundary` | 14 | `test_rollback` | 6 |
| `test_integration_sandbox_topology` | 8 | `test_bounds` | 16 |
| `test_audit_secret_safety` | 5 | `test_waiting_quiescence` | 5 |
| `test_approval_integrity` | 9 | `test_lineage_and_rollback` | 8 |

## 5. Known limitations and accepted risks

Each needs an explicit reviewer decision in §6.

### 5.1 `X-Actor-Id` / `X-Client-Id` are demo identity, not authentication — **material**

Both headers stand in for an authenticated session. A caller may assert any value. **Authorization
is real** — roles come from a server-side directory, ownership is enforced, and no `agent:` identity
can approve — but **authentication is not**: anyone who can reach the API can claim to be
`human:lead` and approve their own change, or claim another client's id and read its analytics.

*Why accepted:* wiring an identity provider is deployment work, and the authorization decision does
not depend on it — swapping the header for a verified session changes one function. *Compensating:*
neither service is intended to be network-exposed in this submission. **This is the single most
important item for the reviewer**, and it should not ship to any shared environment as-is.

### 5.2 Raw-socket bypass of the Python egress guard — **by design**

The guard wraps `getaddrinfo` and `create_connection`, the entry points every stdlib and
third-party HTTP client uses. It cannot wrap the syscall those wrappers themselves call, so a raw
`socket.socket().connect()` bypasses it. Asserted by a test
(`test_a_raw_socket_connect_bypasses_the_guard_by_design`) so the property stays recorded.

*Why accepted:* the guard is hygiene for orchestrator code, not the containment boundary. Agent
code is contained by `--network none` and an `--internal` network. A determined attacker with code
execution inside the orchestrator process has already defeated a larger boundary.

### 5.3 Thread-based timeout bounds the caller's wait, not the runaway work

`BoundedExecutor` enforces per-attempt timeouts with a worker thread and `shutdown(wait=False)`.
Python cannot forcibly kill a thread, so an operation that ignores its deadline keeps running in
the background until it finishes; what the timeout guarantees is that the *caller* stops waiting
and the declared fallback fires.

*Why accepted:* the operations this bounds are orchestrator-authored. **Untrusted work — anything
the agent wrote — runs in a container whose wall-clock limit is enforced by `docker kill`**, which
is a real kill, and that is tested.

### 5.4 Plaintext password reaches the server during role creation

Documented at length in `ops/db/provision.sh`. Base64 keeps values out of argv and out of the
repository, but `CREATE ROLE … PASSWORD '<plaintext>'` is what PostgreSQL executes, so statement
logging that captures DDL would capture it.

*Why accepted:* deliberately not fixed for a take-home; the durable fix is never transmitting
plaintext (SCRAM verifier computed client-side, or a secrets-manager integration). *Operator
requirement:* run provisioning with `log_statement` not set to `all`/`ddl`, and rotate anything that
may have been captured.

### 5.5 Redis deliberately not introduced

Not a gap. Research R13 permits a cache tier only on a **measured** budget breach with cheaper rungs
exhausted. T098 measured p95 6.82 ms against a 150 ms budget — the first condition is not met.
Security-relevant because a second datastore would add credentials to provision, a cache-invalidation
path on revoke and expiry, and a new failure mode on the availability path NFR-002 protects.
Enforced, not merely documented: `CACHE_TIER` sits in `NEW_COMPONENT_OPTIONS`, so proposing it halts
for architecture approval.

### 5.6 Other material limitations

- **No TLS.** Both services speak plain HTTP; `X-Client-Id` and any future token would cross the
  network in clear. Termination is deployment work.
- **No rate limiting** (FR-015, DEFERRED_APPROVED). Link creation is unthrottled — a resource-
  exhaustion avenue if exposed.
- **No dependency/supply-chain review.** Third-party libraries were not audited for known CVEs.
- **Docker daemon access is a privilege.** The orchestrator process can run containers; anyone who
  can execute code in it inherits that. Scoped to `run_tests` by a Gate II addendum, and the runtime
  can only *check* for images, never build or pull.
- **Console has no authentication.** It sends whatever `X-Actor-Id` it is configured with.
- **Single observation for SC-001**, and a single-host performance baseline. Neither is a security
  control, but both bound how far the evidence generalises.

## 6. Defects found in this review

**None.** No new security defect was discovered. The `GRANT` result in §3.1 was investigated and
confirmed to be a PostgreSQL reporting artifact with no privilege change; it is recorded so the
reviewer is not misled by reproducing it.

Four defects were found and fixed during the **preceding** T099 egress verification, and are listed
here for completeness — all now covered by regression tests confirmed to fail when the fix is
reverted:

1. The egress allow-list was implemented but **never installed** in the running orchestrator.
2. The allow-list read `ORCHESTRATOR_DB_HOST` while the application connected via
   `ORCHESTRATOR_DB_URL`, so the guard would have denied the application's own database.
3. `EgressDenied` echoed credentials embedded in a configuration URL.
4. The audit secret check inspected key names but not values, so a DSN in a free-text `detail`
   field passed unexamined.

## 7. Human sign-off

**Completed by the human reviewer on 2026-08-20. Recorded verbatim in substance; no agent
participated in this decision.**

| Field | |
|---|---|
| Role / authority | **Principal Engineer / Architecture Reviewer** |
| Date | **2026-08-20** |
| Scope reviewed | The evidence package §1–§6: service and database isolation, authentication and authorization boundaries, agent tool boundary, sandbox controls, egress controls, input/output scope, workflow safety, shortener security behaviour, secrets and configuration, and the accepted risks in §5 |
| Findings raised | None beyond the limitations already recorded in §5. No new security defect identified |
| **Decision** | ☑ **APPROVED WITH CONDITIONS** ☐ Approved ☐ Rejected |

### 7.1 Control decisions

Fifty-one controls reviewed: **47 PASS**, **4 ACCEPT-RISK**, **0 FAIL**.

| Group | Result |
|---|---|
| **A. Service and database isolation** | A1–A6 **PASS** (6/6) |
| **B. Authentication and authorization** | B1–B6 **PASS**; **B7 ACCEPT-RISK** — `X-Actor-Id` is demo identity, not authentication |
| **C. Agent tool boundary** | C1–C6 **PASS** (6/6) |
| **D. Sandbox controls** | D1–D9 **PASS** (9/9) |
| **E. Egress controls** | E1–E6 **PASS**; **E7 ACCEPT-RISK** — guard is defense-in-depth, the container is the real boundary |
| **F. Input/output scope** | F1–F5 **PASS** (5/5) |
| **G. Workflow safety** | G1–G6 **PASS**; **G7 ACCEPT-RISK** — thread timeout bounds the caller, not the runaway thread |
| **H. Shortener security** | H1–H7 **PASS** (7/7) |
| **I. Secrets and configuration** | I1–I5 **PASS**; **I6 ACCEPT-RISK** — plaintext password at `CREATE ROLE` |

### 7.2 Accepted risks — reviewer's stated basis

All ten accepted. The reviewer's reasoning is recorded because an accepted risk without its
basis cannot be re-evaluated later.

| # | § | Risk | Reviewer's basis for acceptance |
|---|---|---|---|
| **J1** | 5.1 | `X-Actor-Id` is demo identity, not authentication | Acceptable **only** for this take-home/demo environment |
| **J2** | 5.2 | Raw-socket bypass of the Python egress guard | The Python egress guard is defense-in-depth; Docker/container networking is the **primary untrusted-code boundary** |
| **J3** | 5.3 | Thread timeout cannot kill a host thread | Accepted because untrusted agent-authored execution occurs inside the bounded Docker sandbox |
| **J4** | 5.4 | Plaintext password at `CREATE ROLE` | Acceptable for **local provisioning only**; production would use a stronger secret-management/provisioning mechanism |
| **J5** | 5.5 | Redis deliberately not introduced | Intentionally omitted because measured load does not justify the added datastore |
| **J6** | 5.6 | No TLS | Acceptable for **localhost/demo use only** |
| **J7** | 5.6 | No rate limiting | An explicitly **approved deferred requirement** (FR-015), not a missing control |
| **J8** | 5.6 | No dependency / supply-chain review | Outside the take-home scope |
| **J9** | 5.6 | Docker daemon access is a privilege | Accepted as an **infrastructure trust boundary** for this prototype |
| **J10** | 5.6 | Console has no authentication | Not implemented because this is a **local demonstration console** |

### 7.3 Conditions of approval

**Binding.** The approval in §7 holds only while all six are satisfied.

1. `X-Actor-Id` **MUST** continue to be documented as demo identity only and **MUST NOT** be
   described as production authentication.
2. This implementation **must not be deployed to a shared or production environment** without real
   authentication, transport security, and appropriate console access controls.
3. The Python egress guard **must continue to be described as defense-in-depth**; Docker/container
   network isolation is the security boundary for untrusted agent-authored execution.
4. **Rate limiting remains an explicitly approved deferral**, not an accidentally missing security
   control.
5. Local database credentials and provisioning techniques **must not be represented as production
   secret-management practices**.
6. **No accepted risk above may be silently removed** from the final documentation.

> **Standing instruction to anyone editing this repository, human or agent.** Condition 6 makes the
> §5 register append-only in spirit: a risk may be *closed* by fixing it, with the fix and its
> evidence recorded — never by deleting the entry. Conditions 1, 3 and 5 constrain the wording of
> `README.md`, `docs/HLD.md`, `docs/LLD.md` and this file; a documentation change that weakens any
> of them invalidates this approval and requires a fresh human review.

### 7.4 Condition compliance at time of sign-off

Checked against the current documentation:

| Condition | Where it is honoured today |
|---|---|
| 1 | `README.md` §8 and §20, `docs/HLD.md` §17/§18, `docs/LLD.md` §17.2, this file §5.1 — all describe the header as demo identity |
| 2 | `README.md` §20, this file §5.1 — deployment restriction stated |
| 3 | `docs/security/egress-verification.md` §7, `docs/HLD.md` §9/§18, this file §3.5/§5.2 — all name the container as the real boundary |
| 4 | `tasks.md § Deferred Capabilities`, traceability matrix FR-015 `DEFERRED_APPROVED`, this file §5.6 |
| 5 | `ops/db/provision.sh` header, `README.md` §6, this file §3.9/§5.4 — local credentials labelled local-development-only |
| 6 | §5 retained in full; this section records the decision rather than replacing the register |

