# Quickstart validation record (T103)

**Date:** 2026-08-20 · **Task:** T103 `[HUMAN]` · **Result: PASS after two invalidated attempts**

> **Attribution.** Every PASS/FAIL/N/A below was **observed and decided by the human reviewer**.
> An agent presented the checklist, extracted commands verbatim from `README.md`, diagnosed
> reported failures, and made documentation edits under direction. **No agent executed a
> validation step on the reviewer's behalf, and no result here is agent-inferred.** Where the
> reviewer's report elided output, it is recorded as elided rather than reconstructed.

**What T103 was for:** proving `README.md` can take a reviewer from a clean local state to a
working system. It did that — and the first attempt failed, which is the more useful outcome. Two
environment faults and two operator faults surfaced, and the two environment faults produced six
documentation corrections that are now part of the README.

---

## 1. Summary

| | |
|---|---|
| Sections validated | A–I, all required checks **PASS** |
| Invalidated attempts | 2 — stale containers, then a stale process |
| README defects found and corrected | **6** |
| Runtime defects found | **0** |
| Runtime or OpenAPI changes made | **none** |
| Performance rerun (H11) | **N/A** — T098 evidence retained |
| Traceability at close | **79 total · 77 COVERED · 2 DEFERRED_APPROVED · 0 GAP** |

---

## 2. Finding 1 — stale database containers with non-README credentials

**Discovered at:** E4, first attempt. **Classification:** environment/setup. **Not** a runtime
defect.

### What was observed

```
curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8000/v1/runs/no-such-run
Internal Server Error
HTTP 500
```

Expected `HTTP 404` with `{"error":"not_found","message":"..."}`.

### Investigation

Every database-backed endpoint returned 500 while `/health` returned 200:

```
/v1/runs                        -> 500      /v1/runs/no-such-run/audit      -> 500
/v1/runs/no-such-run            -> 500      /v1/runs/no-such-run/decisions  -> 500
/v1/runs/no-such-run/graph      -> 500      /v1/runs/no-such-run/pending    -> 500
/v1/runs/no-such-run/gates      -> 500      /health                         -> 200
```

Root cause, from the server-side traceback:

```
psycopg.OperationalError: connection failed: connection to server at "127.0.0.1", port 55433 failed:
FATAL:  password authentication failed for user "orchestrator"
```

Both containers predated the session and carried credentials the README does not specify:

| Container | Created (UTC) | Password on container | README §6a specifies |
|---|---|---|---|
| `shortener-local` | 14:38:52 | `perf-local-only` | `local-dev-only` |
| `orchestrator-local` | 14:50:30 | `orch-local-only` | `local-dev-only` |

Session time at investigation was 20:01 UTC — both roughly five hours old. `docker run --name`
does not replace an existing container; it fails with a name conflict, and that error had scrolled
past.

### Proof it was not a code defect

The identical code path against a **reachable** database returned exactly what the README promises:

```
/v1/runs             -> 200  []
/v1/runs/no-such-run -> 404  {"error":"not_found","message":"unknown run no-such-run"}
```

`routes.py:115` already raises `HTTPException(404, {"error":"not_found", ...})`, and the handler in
`app.py` flattens it to the documented envelope. **No runtime change was made.**

### Why the earlier steps could not catch it

- `pg_isready` proves the **server** is up, not that a password authenticates.
- `psql` run **inside** the container succeeds whatever the password is — the official image's
  `pg_hba.conf` uses `trust` for in-container loopback.
- `/health` touches no database and returns 200 regardless.

So B3, B4, B5 and E2 all passed against a database the application could not authenticate to.

### Evidence reclassified

The reviewer ruled that because T103 is explicitly clean-state validation, observations made
against non-README containers cannot stand:

| Steps | Reclassified to |
|---|---|
| B1, B2, B4, B5, B6 | **INVALID** — observed against stale containers |
| D1–D9 | **INVALID as clean-state evidence** (honest observations, wrong database) |
| E1–E4 | **INVALID**; E4 retained as **FAIL** |
| A3, A4, B3 | Re-observation required |
| C1, C2, C3 | **VALID** — independently verified, no rerun |

---

## 3. README corrections produced by Finding 1

Six, all documentation-only. No runtime or OpenAPI change.

| # | Correction | Where |
|---|---|---|
| 1 | **Explicit disposable-container reset** — `docker rm -f shortener-local orchestrator-local 2>/dev/null \|\| true`, explaining that `docker run --name` does not replace an existing container and that an old one may carry different credentials and stale data. Scoped explicitly to disposable quickstart containers, with a warning not to force-remove a database that matters | §6a |
| 2 | **Credential-aware host-side verification** — a `psycopg` check over TCP with the documented password, using the project virtualenv so a host `psql` stays optional. Verifies the orchestrator DSN character-for-character as §8 uses it | §6 Step 2 |
| 3 | **Liveness vs readiness** — a table stating `/health` proves the process is live and *nothing about the database*, while `GET /v1/runs` → `[]` 200 is the readiness check, with an explicit instruction not to declare readiness on `/health` alone | §8 |
| 4 | **Deterministic readiness loop** — `until … pg_isready … done` replacing a single-shot call | §6 Step 1 |
| 5 | **Unknown-run 404 negative control** — the `curl` for `/v1/runs/no-such-run` with its expected flat envelope | §11 |
| 6 | **Documented unknown-parent collection limitation** — see §7 below | §20 |

Correction 2 was verified to fail on a wrong password (`FATAL: password authentication failed`)
before being relied upon, so a PASS on it is meaningful rather than vacuous.

---

## 4. Finding 2 — stale process holding :8000

**Discovered at:** E1–E4, second attempt. **Classification:** environment. **Not** a product
failure.

PID 54311 still occupied port 8000, so the freshly started orchestrator could not bind, and every
request in that attempt reached the stale process instead. Those E2–E4 observations are **INVALID**
— they measured a process the reviewer had not configured. The clean retry, after removing the
stale PID, passed.

---

## 5. Finding 3 — D1 paste / line-continuation

**Classification:** operator/shell. **Implementation and configuration were correct.**

The runtime attempted `localhost:5432` — the default — rather than the documented `55432`.
Investigation of `shortener/src/main/resources/application.yaml` (the only configuration file; no
`.yml`, no `.properties`, no `DataSource` class) found:

```yaml
url:      ${SHORTENER_DB_URL:jdbc:postgresql://localhost:5432/shortener_db}   # line 8
username: ${SHORTENER_DB_USER:shortener}                                       # line 9
password: ${SHORTENER_DB_PASSWORD:}                                            # line 10
```

`5432` is the **default**; `55432` comes only from the variable. `spring-boot-maven-plugin` is
declared with no configuration block, so the forked JVM inherits Maven's environment normally.

An agent ran the README command verbatim and observed the correct behaviour:

```
FlywayExecutor: Database: jdbc:postgresql://localhost:55432/shortener_db (PostgreSQL 16.14)
Started ShortenerApplication in 5.134 seconds
```

**The README command is correct.** The variables did not reach the JVM in the reviewer's shell —
consistent with broken line continuation on paste, which leaves the `VAR=value \` lines as no-ops
and runs a bare `mvn`, falling through to the default. A paste-proof single-line form was supplied
and worked. **No README correction was made for this item**, because the documented command is not
wrong.

> **Agent-caused side effect, disclosed.** That diagnostic run booted the application, so Flyway
> migrated the then-fresh `shortener_db`. This would have made the reviewer's D1 show migrations
> being *skipped* rather than applied. The reviewer recreated `shortener-local` before D1, so the
> D1–D9 results below are genuine clean-state observations. `orchestrator-local` was untouched, so
> B4/B5 were unaffected.

---

## 6. Finding 4 — D4 unset `$CODE`

**Classification:** user-shell error, **not** a product defect, as ruled by the reviewer.

The first D4 attempt returned 404 because `$CODE` was unset in that shell, producing a request for
an empty code. The retry with the literal generated code **`Gxm1TAa`** returned the correct 302
with the full cache-header set. No change made.

---

## 7. Architecture decision recorded — unknown-parent collection endpoints

**Human decision: keep current behaviour. No runtime or OpenAPI change.**

`GET /v1/runs/{id}` distinguishes an unknown run with **404**. The five collection endpoints —
`/graph`, `/gates`, `/audit`, `/decisions`, `/pending` — return **200 with empty results**, so
"this run has zero gates" and "this run does not exist" are indistinguishable on those paths.

Recorded as a known API semantic limitation:

> *Collection inspection endpoints do not currently distinguish an unknown parent run from an
> existing run with zero corresponding records. Consistent parent-existence validation is
> recommended for a future API revision.*

Reviewer's reasoning: no current requirement mandates 404 there; changing it would reshape an
already published, CI-gated public contract during T103; and this is API semantic debt, not a
blocker and not a security defect. Documented in README §20.

---

## 8. Final clean-state results

All HUMAN-observed. **A**, **B**, **D**, **E**, **F**, **G**, **H**, **I** below are the clean
rerun; **C** was independently valid and not repeated.

### A — clean-state preparation
| | |
|---|---|
| A1 | **PASS** — stale orchestrator stopped; `:8000` health returned 000 |
| A2 | **PASS** — nothing listening on `:8080` or `:5173` |
| A3 | **PASS** *(attempt 2)* — disposable containers absent after cleanup |
| A4 | **PASS** *(attempt 2)* — verification returned exactly `clean` |
| A5 | **NOT CAPTURED** — `java -version` / `JAVA_HOME` output was not supplied; the reviewer's report left the placeholder unfilled |
| A6 | **PASS** — environment variables set explicitly from the README, not shell history |

### B — database setup
| | |
|---|---|
| B1 | **PASS** — `shortener-local` created (id elided in report; freshness corroborated: created 20:11:09Z, `pw=local-dev-only`) |
| B2 | **PASS** — `orchestrator-local` created (same corroboration) |
| B3 | **PASS** — readiness loop completed; both servers accepting connections |
| B3a | **PASS** — *(new check, correction 2)* host-side TCP credential verification: `orchestrator credentials OK` / `shortener credentials OK` |
| B4 | **PASS** — all six migrations applied and named in full: `001_init`, `002_declared_io`, `003_approvals_and_lineage`, `004_clarifications`, `005_clarification_requirement`, `006_replanning` |
| B5 | **PASS** — `orchestrator_db` shows exactly 15 tables |
| B6 | **PASS** — `shortener_db`: *"Did not find any relations."* — expected before Flyway |
| B7 | **N/A** — optional four-role provisioning (§6b) skipped |

### C — sandbox *(valid from the first attempt; not repeated)*
| | |
|---|---|
| C1 | **PASS** — `ops/sandbox/build-images.sh all` completed |
| C2 | **PASS** — three images: `agent-sandbox/{orchestrator,shortener,console}:latest` |
| C3 | **PASS** — HUMAN-executed `test_fail_closed_real.py` → **5 passed in 2.22s** (real unreachable daemon; no host fallback) |

### D — shortener
| | |
|---|---|
| D1 | **PASS** — started from the README command against the clean database |
| D2 | **PASS** — `/actuator/health` → `{"status":"UP"}` |
| D3 | **PASS** — `POST /v1/links` → 201; code **`Gxm1TAa`** |
| D4 | **PASS** — 302 to `https://www.google.com` with the full required cache headers |
| D5 | **PASS** — **HUMAN browser observation**: destination loaded |
| D6 | **PASS** — owner analytics 200, `total_redirects=2` |
| D7 | **PASS** — different client → 403 |
| D8 | **PASS** — revoke succeeded; resolve after revoke → 410 `revoked` |
| D9 | **PASS** — fresh `shortener_db` has the Flyway, schema, link and event tables |

### E — orchestrator
| | |
|---|---|
| E1 | **PASS** — fresh orchestrator started after the stale PID was removed |
| E2 | **PASS** — `/health` → `{"status":"up","service":"orchestrator"}` *(liveness only)* |
| E3 | **PASS** — `/v1/runs` → `[]` HTTP 200 *(readiness)* |
| E4 | **PASS** — `/v1/runs/no-such-run` → `{"error":"not_found","message":"unknown run no-such-run"}` HTTP 404 |
| E5 | **PASS** — environment table clear; `ANTHROPIC_API_KEY` not required for API, console or tests |
| E6 | **PASS** — demo-identity warning explicit; satisfies T102 condition 1 |

### F — console
| | |
|---|---|
| F1 | **PASS** — Vite started on `:5173` |
| F2 | **PASS** — console returned HTTP 200 |
| F3 | **PASS** — **HUMAN browser observation**: empty-state message and both tabs visible |
| F4 | **PASS** — **HUMAN DevTools observation**: zero `/v1` calls in the empty state |
| F5 | **PASS** — `/v1/runs` through the Vite proxy → 200 `application/json` |
| F6 | **PASS** — orchestrator stopped → visible `ApiClientError`; recovered after restart |

### G — demo scenarios
| | |
|---|---|
| G1 | **PASS** — the README honestly states there is no run-creation endpoint; the route inventory matches the documented nine-read / two-write surface |
| G2 | **PASS** — greenfield scenario suite: **28 passed** |
| G3 | **PASS** — brownfield / selective replan: **18 passed** |
| G4 | **PASS** — ambiguous requirement: **22 passed**; `"make links smarter"` genuinely recognised by the implemented detector |
| G5 | **PASS** — inspection endpoints exist and return the documented responses; unknown-parent behaviour matches the §20 limitation |

### H — tests

**Counts elided in the reviewer's report are recorded as not captured. None has been invented.**

| | |
|---|---|
| H1 | **PASS** — Java unit tests · *count not captured* |
| H2 | **PASS** — Java contract tests · *count not captured* |
| H3 | **PASS** — `mvn verify` completed successfully |
| H4 | **PASS** — full orchestrator suite completed successfully |
| H5 | **PASS** — failure marker · *count not captured* |
| H6 | **PASS** — contract marker · *count not captured* |
| H7 | **PASS** — traceability: **11 passed; 79 / 77 / 2 / 0** |
| H8 | **PASS** — all seven security/sandbox suites passed |
| H9 | **PASS** — console vitest · *count not captured* |
| H10 | **PASS** — TypeScript typecheck completed with no errors |
| H11 | **N/A** — performance benchmark not rerun; T098 baseline retained (`perf/baseline-2026-08-20.md`) |

### I — documentation integrity
| | |
|---|---|
| I1 | **PASS** — every referenced path exists (28 markdown links, 0 broken — agent-verified, reviewer-confirmed) |
| I2 | **PASS** — four bare filenames accepted as prose references; no change required |
| I3 | **PASS** — copy/paste-safe; 36 shell blocks, 0 containing markdown URLs |
| I4 | **PASS** — no secret presented as a production credential; `local-dev-only` labelled |
| I5 | **PASS** — HUMAN-only validation clearly separated from automated verification |
| I6 | **PASS** — the corrected README no longer depends on undocumented hidden state on the clean rerun |

---

## 9. Evidence classification

| Class | What it covers here |
|---|---|
| **HUMAN observation / decision** | Every PASS/FAIL/N/A above; D5, F3, F4 browser and DevTools observations; the I2 and §7 rulings; the reclassification of Finding 1 evidence; the T103 completion decision |
| **Automated test evidence** | C3 (5), G2 (28), G3 (18), G4 (22), H7 (11 · 79/77/2/0), H1–H10 suites — all executed by the reviewer |
| **Agent diagnostics** | Endpoint sweep across the six run-scoped paths; the psycopg traceback; container creation-time and credential inspection; the §7 code-path proof; the `application.yaml` / plugin analysis and the verbatim-command run; read-only container-freshness corroboration at B1/B2 |
| **Agent documentation edits** | The six README corrections in §3; this record |

---

## 10. Accepted limitations at close

1. **A5 not captured** — the `java -version` / `JAVA_HOME` output was never supplied. Recorded as not captured rather than assumed. The README's Java 8 warning stands on independent evidence.
2. **Five H counts not captured** — H1, H2, H5, H6, H9 reported PASS without figures.
3. **B7 skipped** — four-role provisioning (§6b) not exercised in this session. It was verified live during T102 against a throwaway cluster.
4. **H11 not rerun** — T098 baseline retained. Rerunning requires stopping `shortener-local`, which would destroy the Section D database.
5. **Unknown-parent collection endpoints** — §7 above; deliberate, recorded, unchanged.
6. **Four bare filenames** in prose — accepted at I2.

---

## 11. Conclusion

`README.md` takes a reviewer from a clean clone to a working system: two databases, three services,
health and readiness verified, a short link created, resolved, scoped, revoked, and the three demo
scenarios executable through their test suites.

**T103 initially exposed environment and documentation weaknesses rather than passing on the first
attempt.** A stale-container credential mismatch and a stale process both produced failures that
looked like product defects and were not. Investigation showed the runtime correct in every case,
and the quickstart was corrected in six places so the same traps are detected rather than
encountered. The revalidation then passed cleanly end to end.

**No runtime defect was found. No runtime or contract change was made.**
