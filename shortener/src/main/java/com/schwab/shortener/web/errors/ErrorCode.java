package com.schwab.shortener.web.errors;

/**
 * Stable, machine-readable error identifiers (FR-009, FR-016, SC-004).
 *
 * <p>These strings are part of the published contract: additive-only within a major version.
 * A client must be able to tell these apart without parsing prose.
 */
public enum ErrorCode {
    INVALID_SCHEME("invalid_scheme"),
    MALFORMED_URL("malformed_url"),
    URL_TOO_LONG("url_too_long"),
    ALIAS_CONFLICT("alias_conflict"),
    ALIAS_RESERVED("alias_reserved"),
    ALIAS_MALFORMED("alias_malformed"),
    NOT_FOUND("not_found"),
    EXPIRED("expired"),
    REVOKED("revoked"),
    RATE_LIMITED("rate_limited"),
    FORBIDDEN("forbidden");

    private final String id;

    ErrorCode(String id) {
        this.id = id;
    }

    public String id() {
        return id;
    }
}
