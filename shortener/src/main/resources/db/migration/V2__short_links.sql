-- US1 core: links and redirect events (FR-004, FR-008, FR-012, FR-013).
--
-- A simple indexed event table, not a partitioned one: partitioning was removed
-- from the design as schema ceremony at this scale (research R14). Retention is
-- documented behaviour, and its sweep is deferred.

CREATE TABLE IF NOT EXISTS short_link (
    code                   VARCHAR(32) PRIMARY KEY,
    destination            TEXT        NOT NULL,
    destination_canonical  TEXT        NOT NULL,
    client_id              TEXT        NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL,
    expires_at             TIMESTAMPTZ,
    revoked_at             TIMESTAMPTZ,
    redirect_count         BIGINT      NOT NULL DEFAULT 0,
    first_redirect_at      TIMESTAMPTZ,
    last_redirect_at       TIMESTAMPTZ,
    CONSTRAINT destination_not_blank CHECK (length(btrim(destination)) > 0)
);

-- Owner-scoped analytics and the expiry sweep both filter on these.
CREATE INDEX IF NOT EXISTS short_link_client_idx  ON short_link (client_id);
CREATE INDEX IF NOT EXISTS short_link_expires_idx ON short_link (expires_at)
    WHERE expires_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS redirect_event (
    id           BIGSERIAL PRIMARY KEY,
    code         VARCHAR(32) NOT NULL REFERENCES short_link(code),
    occurred_at  TIMESTAMPTZ NOT NULL
);

-- (code, id) serves stable-ordered reads; occurred_at serves the retention sweep
-- when it is built.
CREATE INDEX IF NOT EXISTS redirect_event_code_idx     ON redirect_event (code, id);
CREATE INDEX IF NOT EXISTS redirect_event_occurred_idx ON redirect_event (occurred_at);
