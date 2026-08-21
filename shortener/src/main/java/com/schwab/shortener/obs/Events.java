package com.schwab.shortener.obs;

/**
 * The operational log vocabulary.
 *
 * <p>A closed set of names so dashboards and alerts can rely on them, and so a typo is a compile
 * error rather than a silently unqueryable log line.
 */
public final class Events {

    public static final String APPLICATION_STARTED = "application_started";
    public static final String APPLICATION_STOPPING = "application_stopping";
    public static final String LINK_CREATED = "link_created";
    public static final String SHORT_LINK_CREATED = "short_link_created";
    public static final String SHORT_LINK_CREATION_FAILED = "short_link_creation_failed";
    public static final String HTTP_REQUEST_COMPLETED = "http_request_completed";
    public static final String LINK_CREATE_REJECTED = "link_create_rejected";
    public static final String LINK_REVOKED = "link_revoked";
    public static final String REDIRECT_FAILED = "redirect_failed";
    public static final String AUTHORIZATION_DENIED = "authorization_denied";
    public static final String DATABASE_ERROR = "database_error";
    public static final String UNEXPECTED_ERROR = "unexpected_error";

    private Events() {}
}
