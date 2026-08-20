package com.schwab.shortener.web.errors;

import com.schwab.shortener.domain.CodeGenerator.CollisionExhausted;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/** Maps every failure to a stable, machine-readable identifier (FR-009, FR-016, SC-004). */
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(UnauthenticatedException.class)
    public ResponseEntity<ApiError> handleUnauthenticated(UnauthenticatedException exception) {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                .body(ApiError.of(exception.code(), exception.getMessage()));
    }

    /**
     * A redirect that cannot be durably counted is not served (R14, approval item 7).
     *
     * <p>Without this the exception would escape as an unhandled 500 and a stack trace. The
     * caller is told, in a stable identifier, that the redirect did not happen — which is the
     * honest answer, and the one that keeps the counter and the response consistent.
     */
    @ExceptionHandler(DataAccessException.class)
    public ResponseEntity<ApiError> handleStorageFailure(DataAccessException exception) {
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(ApiError.of(ErrorCode.REDIRECT_NOT_RECORDED,
                        "the redirect could not be durably recorded, so it was not served"));
    }

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ApiError> handle(ApiException exception) {
        return ResponseEntity.status(statusFor(exception.code()))
                .body(ApiError.of(exception.code(), exception.getMessage()));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiError> handleUnreadableBody(HttpMessageNotReadableException e) {
        return ResponseEntity.badRequest()
                .body(ApiError.of(ErrorCode.MALFORMED_URL, "request body could not be read"));
    }

    @ExceptionHandler(CollisionExhausted.class)
    public ResponseEntity<ApiError> handleCollision(CollisionExhausted e) {
        // Bounded retry exhausted. Reported, never looped (Principle VII).
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                .body(ApiError.of(ErrorCode.ALIAS_CONFLICT, e.getMessage()));
    }

    private static HttpStatus statusFor(ErrorCode code) {
        return switch (code) {
            case NOT_FOUND -> HttpStatus.NOT_FOUND;
            // Gone, not 404: an expired or revoked link existed, and the caller is entitled
            // to know that is why it no longer resolves.
            case EXPIRED, REVOKED -> HttpStatus.GONE;
            case FORBIDDEN -> HttpStatus.FORBIDDEN;
            case RATE_LIMITED -> HttpStatus.TOO_MANY_REQUESTS;
            case ALIAS_CONFLICT -> HttpStatus.CONFLICT;
            default -> HttpStatus.BAD_REQUEST;
        };
    }
}
