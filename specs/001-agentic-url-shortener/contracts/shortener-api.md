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
