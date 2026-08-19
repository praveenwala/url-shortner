package com.schwab.shortener.web.errors;

/** Error response shape (FR-016). */
public record ApiError(String error, String message) {
    public static ApiError of(ErrorCode code, String message) {
        return new ApiError(code.id(), message);
    }
}
