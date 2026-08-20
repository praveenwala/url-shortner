package com.schwab.shortener.web.errors;

/** Carries a stable error identifier from the point of failure to the response (FR-009). */
public class ApiException extends RuntimeException {

    private final ErrorCode code;

    public ApiException(ErrorCode code, String message) {
        super(message);
        this.code = code;
    }

    public ErrorCode code() {
        return code;
    }
}

