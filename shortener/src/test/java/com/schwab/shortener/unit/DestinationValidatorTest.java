package com.schwab.shortener.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.schwab.shortener.validation.DestinationValidator;
import com.schwab.shortener.web.errors.ApiException;
import com.schwab.shortener.web.errors.ErrorCode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

/** T018/T025 — scheme allow-list, malformed rejection, canonicalisation (FR-001–FR-003, FR-011). */
class DestinationValidatorTest {

    private final DestinationValidator validator = new DestinationValidator();

    @ParameterizedTest
    @ValueSource(strings = {
        "https://example.com/path?q=1",
        "http://example.com",
        "https://example.com:8443/a/b",
    })
    void acceptsAbsoluteHttpAndHttpsUrls(String url) {
        assertThat(validator.validate(url)).isEqualTo(url);
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "mailto:someone@example.com",
    })
    void rejectsEverySchemeOutsideTheAllowList(String url) {
        assertThatThrownBy(() -> validator.validate(url))
                .isInstanceOf(ApiException.class)
                .extracting(e -> ((ApiException) e).code())
                .isEqualTo(ErrorCode.INVALID_SCHEME);
    }

    @ParameterizedTest
    @ValueSource(strings = {
        "//example.com/protocol-relative",
        "/just/a/path",
        "not a url at all",
        "http://",
        "https://   ",
    })
    void rejectsRelativeAndMalformedInput(String url) {
        assertThatThrownBy(() -> validator.validate(url)).isInstanceOf(ApiException.class);
    }

    @Test
    void rejectsAnOverlongDestination() {
        String url = "https://example.com/" + "x".repeat(DestinationValidator.MAX_LENGTH);
        assertThatThrownBy(() -> validator.validate(url))
                .isInstanceOf(ApiException.class)
                .extracting(e -> ((ApiException) e).code())
                .isEqualTo(ErrorCode.URL_TOO_LONG);
    }

    @Test
    void canonicalisesForComparisonWithoutAlteringTheRedirectTarget() {
        String supplied = "HTTPS://Example.COM:443/Path";
        assertThat(validator.validate(supplied)).isEqualTo(supplied);
        assertThat(validator.canonicalise(supplied)).isEqualTo("https://example.com/Path");
    }

    @Test
    void canonicalisationDropsDefaultPortsAndLowercasesTheHostOnly() {
        assertThat(validator.canonicalise("http://EXAMPLE.com:80/A")).isEqualTo("http://example.com/A");
        assertThat(validator.canonicalise("https://example.com:8443/A"))
                .isEqualTo("https://example.com:8443/A");
    }
}
