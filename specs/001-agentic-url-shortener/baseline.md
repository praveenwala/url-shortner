# Time-to-first-success baseline (T022 / SC-001)

**Date:** 2026-08-20 · **Task:** T022 `[HUMAN]` · **Requirement:** SC-001

> **Execution and attribution.** This session was performed and timed by a human
> participant. The elapsed time below is **human-provided**; it was not measured, inferred, or
> recomputed by an agent, and no part of the participant's task — creating the link, reading the
> code, or following it — was performed by an agent. The agent's role was limited to verifying
> the environment beforehand and the technical evidence afterwards.

## Criterion

**SC-001**: A person can turn a long destination into a working short link and follow it to that
destination in **under 30 seconds**, with no prior training.

## Observation

| | |
|---|---|
| Participant | Untrained human |
| Task given | "Create a short link for https://www.google.com and then use that short link to reach Google." |
| Destination | `https://www.google.com` |
| Client id | `t022-human-final` |
| **Elapsed time** | **approximately 0.5 seconds** (human-observed) |
| Assistance required | None |
| Result against SC-001 | **PASS** — under the 30-second threshold |

Elapsed time is recorded as the participant reported it. It is deliberately *not* restated with
millisecond precision: a stopwatch observation does not carry that resolution, and writing
`0.500 s` would manufacture confidence the measurement does not have.

## Independent technical verification

Run by an agent **after** the human session, against the live stack — confirming the flow the
participant exercised actually occurred, not that it could occur.

| # | Check | Result |
|---|---|---|
| 1 | A `short_link` exists for `t022-human-final` | **PASS** — code `Ii2L2v2`, created `2026-08-20 18:19:15.076432+00` |
| 2 | Destination is `https://www.google.com` | **PASS** — stored and canonical forms both match |
| 3 | `redirect_count >= 1` | **PASS** — 1 at time of verification |
| 4 | `first_redirect_at` populated | **PASS** — `2026-08-20 18:19:33.009977+00` |
| 5 | A matching `redirect_event` exists | **PASS** — event id 12, timestamp identical to `first_redirect_at` |
| 6 | Resolving the code returns 302 to the destination | **PASS** — `HTTP/1.1 302`, `Location: https://www.google.com` |

The 302 also carried the full non-cacheable header set required by FR-007: `Cache-Control:
no-store, no-cache, must-revalidate`, `Pragma: no-cache`, `Expires: 0`.

**Verification side effect, recorded for honesty.** Check 6 issued a real request, so it added
`redirect_event` id 13 at `18:20:45.622181+00` and moved `redirect_count` to 2. The participant's
own redirect is **event id 12**; event 13 is the agent's verification request. Counter and event
count remain exactly consistent (2 and 2), which is the SC-006 property.

## Environment

| | |
|---|---|
| Shortener | Spring Boot on `http://localhost:8080`, `/actuator/health` → `{"status":"UP"}` |
| Database | PostgreSQL 16 (`shortener-local`), database `shortener_db` |
| Pre-flight | `ops/smoke/t022-path-check.sh` — create → 302 → header contract → followed redirect → unissued code 404 |

## Scope of this record

This establishes SC-001 only: a first-time user can complete create-and-follow well within the
30-second budget, unaided. It says nothing about sustained throughput or latency under load,
which are NFR-001, NFR-005 and SC-002 and are recorded separately in
`perf/baseline-2026-08-20.md`.

A single participant is a single observation. The criterion asks whether the flow is learnable
without training rather than for a distribution across users, so one unaided success satisfies
it as written; a larger sample would be needed before making any claim about typical time.
