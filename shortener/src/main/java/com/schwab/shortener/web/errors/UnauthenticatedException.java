package com.schwab.shortener.web.errors;

/**
 * No caller identity at all — distinct from a caller who is identified but does not own the
 * link. HTTP separates these (401 vs 403) while the contract's error identifier stays
 * {@code forbidden}, so a client branching on the identifier is unaffected.
 */
public class UnauthenticatedException extends ApiException {
    public UnauthenticatedException(String message) {
        super(ErrorCode.FORBIDDEN, message);
    }
}
