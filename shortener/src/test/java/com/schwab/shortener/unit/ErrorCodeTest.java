package com.schwab.shortener.unit;

import static org.assertj.core.api.Assertions.assertThat;

import com.schwab.shortener.web.errors.ApiError;
import com.schwab.shortener.web.errors.ErrorCode;
import java.util.Arrays;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;

/** T009 — SC-004: every failure condition is distinguishable without parsing prose. */
class ErrorCodeTest {

    @Test
    void everyIdentifierIsDistinct() {
        var ids = Arrays.stream(ErrorCode.values()).map(ErrorCode::id).collect(Collectors.toSet());
        assertThat(ids).hasSize(ErrorCode.values().length);
    }

    @Test
    void resolutionOutcomesAreSeparateIdentifiers() {
        assertThat(ErrorCode.NOT_FOUND.id()).isEqualTo("not_found");
        assertThat(ErrorCode.EXPIRED.id()).isEqualTo("expired");
        assertThat(ErrorCode.REVOKED.id()).isEqualTo("revoked");
        assertThat(ErrorCode.MALFORMED_URL.id()).isEqualTo("malformed_url");
    }

    @Test
    void errorResponseCarriesTheStableIdentifier() {
        assertThat(ApiError.of(ErrorCode.INVALID_SCHEME, "scheme not allowed").error())
                .isEqualTo("invalid_scheme");
    }
}
