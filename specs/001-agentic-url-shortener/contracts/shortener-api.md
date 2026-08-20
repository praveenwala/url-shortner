# Contract: Shortener API

**Service**: `shortener` | **Version**: v1 | **Feature**: 001-agentic-url-shortener

**Implementation**: Java 21 + Spring Boot 3, one persistence model (Spring Data JPA) for every
query. This contract is generated from the same annotated types that validate requests
(`springdoc-openapi`), so the published contract and the running service cannot silently
diverge (R4).

Programmatic operations live under `/v1`. The redirect route is **unversioned and
permanent** — short links are handed to third parties and must never change shape (R9).
Entity fields are defined in [data-model.md](../data-model.md) and not repeated here.

## Error shape

Every non-redirect failure returns a stable machine-readable identifier (FR-016). Identifiers
are additive-only within a major version.

`invalid_scheme` · `malformed_url` · `url_too_long` · `alias_conflict` · `alias_reserved`
· `alias_malformed` · `not_found` · `expired` · `revoked` · `rate_limited` · `forbidden`
· `redirect_not_recorded`

`redirect_not_recorded` (503) was added during US1 implementation: it is the caller-visible
consequence of rule 9 below — a redirect that cannot be durably counted is not served, and the
caller is told so in a stable identifier rather than receiving an unhandled 500. Additive
within v1, so a client that does not know it still sees a 5xx.

**Status mapping**: `not_found` → 404 · `expired`, `revoked` → **410 Gone** (the link existed;
a 404 would hide why it stopped resolving) · `forbidden` → 403 when the caller is identified
but is not the creator, **401** when no `X-Client-Id` is supplied at all · `redirect_not_recorded`
→ 503 · everything else → 400.

The distinctness of `not_found` / `expired` / `revoked` / `alias_malformed` is required by
FR-009 and verified by SC-004 — a client must never have to parse prose to tell them apart.

## Operations

| Operation | Route | Purpose | Key outcomes |
|-----------|-------|---------|--------------|
| Create link | `POST /v1/links` | Destination, optional alias, optional absolute expiry | Created; or `invalid_scheme`, `malformed_url`, `url_too_long`, `alias_conflict`, `alias_reserved`, `alias_malformed`, `rate_limited` (FR-001–FR-005, FR-015) |
| Resolve | `GET /{code}` | The redirect itself | **Temporary, explicitly non-cacheable** redirect (FR-007); or `not_found`, `expired`, `revoked` (FR-009) |
| Revoke link | `POST /v1/links/{code}/revoke` | Creator disables a link | Revoked; or `forbidden`, `not_found` (FR-012) |
| Analytics summary | `GET /v1/links/{code}/analytics` | Total count, first and most recent redirect timestamps | Summary; or `forbidden` for a non-creating client (FR-014) |
| Event history | `GET /v1/links/{code}/events` | Paginated redirect events | Bounded page, stable ordering, next-page cursor, and the retention window so an empty page is distinguishable from an aged-out one (FR-014) |

## Reconciliation with the generated OpenAPI (T030, 2026-08-20)

The document generated from the running Spring Boot application is
[`docs/contracts/shortener-openapi.json`](../../../docs/contracts/shortener-openapi.json),
produced by `OpenApiGeneratorTest` from springdoc's `/v3/api-docs`. Every difference found
against this contract is recorded below.

| Difference | Category | Resolution |
|-----------|----------|-----------|
| Generated document advertised `200` for link creation; the service returns `201` | **implementation bug** (documentation) | **Fixed.** springdoc's default was never corrected. Annotated, so the published document states 201 |
| Generated document advertised `200` for the redirect; the service returns `302` with three non-cacheable headers | **implementation bug** (documentation) | **Fixed.** Documented as 302 with `Location`, `Cache-Control`, `Pragma`, `Expires`. A published 200 would hide the single property clients most need to respect — a cached redirect never reaches the service, so counts drift and revoked links keep resolving |
| No error responses documented at all — no 400/401/403/404/410/503, no `ApiError` schema | **implementation bug** (documentation) | **Fixed.** `ApiError` is now published and referenced by every documented failure, so a client reading the contract can see the stable `error` identifiers exist to branch on (FR-016, SC-004) |
| `X-Client-Id` undocumented on owner-scoped operations | **implementation bug** (documentation) | **Fixed.** Documented as a required header on create, revoke, and analytics. Runtime stays lenient so the service can return its own `401` rather than Spring's generic `400` |
| `GET /v1/links/{code}/events` declared, not implemented | **intentionally deferred** | Paginated event history remains deferred. Pinned in the parity test's `DEFERRED` set so a deferral is an entry someone must edit, not a silent absence |
| `alias_conflict`, `alias_reserved`, `alias_malformed`, `rate_limited` identifiers declared, unreachable | **intentionally deferred** | Custom aliases and rate limiting are deferred. The identifiers stay in the enum for when the capability lands; a test asserts no route can produce them today |
| springdoc's own `/v3/api-docs` and `/swagger-ui` routes are served | **additive compatible** | Documentation infrastructure, not product surface. Excluded from the undeclared-route check by name |
| Path parameter spelling and ordering | **cosmetic** | Not changed; the checker normalises parameter names and compares structure |

**No runtime behaviour changed.** Every fix above is an annotation that makes the published
document describe what the service already did.

**Parity is enforced automatically.** `OpenApiParityTest` (24 tests) fails the build when an
undeclared endpoint is served, a non-deferred declared endpoint is absent, the committed
artifact is stale, a request or response shape drifts, an error status or identifier drifts, or
a required redirect header disappears. All three failure modes were verified by deliberately
introducing drift and confirming the suite failed.

## Contract rules

1. **Redirect caching**: the redirect response must be marked non-cacheable. This is not a
   performance preference — a cached redirect silently undercounts (SC-006) and lets revoked
   and expired links keep resolving (FR-008, FR-012).
2. **No dereferencing**: no operation in this contract fetches the destination. There is
   deliberately no liveness check, no preview, and no reputation lookup (FR-018). Adding one
   re-triggers Constitution gate V-a.
3. **Redirect target**: only the destination stored at creation. No request parameter at
   resolution time can influence it (FR-010).
4. **Ownership**: analytics and revoke require the creating client credential; any other
   client receives `forbidden` rather than a 404 that would leak existence (FR-014).
5. **Rate limiting**: 60 creations per minute per credential, burst 10 (R8), counted in
   PostgreSQL — there is no cache tier in the greenfield architecture (R13). The redirect
   route is never rate limited: throttling it would damage NFR-001 and NFR-002, and it never
   touches the rate-limit table.
8. **No cache tier**: the redirect path reads and writes PostgreSQL only. Any future caching
   must preserve FR-008 (expiry), FR-012 (revocation), and SC-006 (exact counts), and is a
   brownfield decision requiring measurement and an approval checkpoint (R13).
9. **Redirect/analytics consistency** (R14): the count is committed before the redirect is
   issued, in the same transaction. A redirect that cannot be counted is not served — clients
   see a failure rather than an uncounted redirect. This is what makes SC-006 exact without
   reconciliation.
10. **Analytics serving cannot degrade redirects**: the summary and history endpoints use a
    separate connection pool from the redirect path, so a heavy query cannot starve redirects.
    Event retention runs as a chunked, off-peak delete against a simple indexed table; its
    residual lock risk is documented rather than removed by partitioning (NFR-002, R14).
6. **Browser compatibility**: the redirect must work in a standard browser with no
   client-side scripting (FR-016).
7. **Frontend readiness**: no frontend ships with this feature, but this contract must be
   sufficient to build one against later without changing it (FR-017).
