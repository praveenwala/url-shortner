package com.schwab.shortener.validation;

import com.schwab.shortener.web.errors.ApiException;
import com.schwab.shortener.web.errors.ErrorCode;
import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Boundary validation for destinations (FR-001, FR-002, FR-003, FR-011, NFR-006).
 *
 * <p>The service never fetches a destination (FR-018), so validation is syntactic by design:
 * scheme allow-list, absoluteness, length. There is deliberately no reachability check, and
 * adding one would re-trigger Constitution gate V-a.
 */
@Component
public class DestinationValidator {

    public static final int MAX_LENGTH = 2048;
    private static final Set<String> ALLOWED_SCHEMES = Set.of("http", "https");

    /** Returns the destination unchanged — validation must not rewrite what will be served. */
    public String validate(String raw) {
        if (raw == null || raw.isBlank()) {
            throw new ApiException(ErrorCode.MALFORMED_URL, "destination must not be empty");
        }
        if (raw.length() > MAX_LENGTH) {
            throw new ApiException(ErrorCode.URL_TOO_LONG,
                    "destination exceeds " + MAX_LENGTH + " characters");
        }

        // The scheme is checked before the URI is parsed, on purpose. A payload like
        // `data:text/html,<script>` is not syntactically a URI, but reporting it as
        // "malformed" would hide the fact that the scheme was the problem — and the
        // scheme allow-list is the security control (FR-002, NFR-006).
        String declaredScheme = declaredScheme(raw.trim());
        if (declaredScheme != null && !ALLOWED_SCHEMES.contains(declaredScheme)) {
            throw new ApiException(ErrorCode.INVALID_SCHEME,
                    "only http and https destinations are accepted");
        }

        URI uri;
        try {
            uri = new URI(raw.trim());
        } catch (URISyntaxException e) {
            throw new ApiException(ErrorCode.MALFORMED_URL, "destination is not a valid URL");
        }

        String scheme = uri.getScheme();
        if (scheme == null) {
            // Covers "/path" and "//host/path": relative and scheme-relative are not
            // destinations, they are ambiguity.
            throw new ApiException(ErrorCode.MALFORMED_URL, "destination must be absolute");
        }
        if (!ALLOWED_SCHEMES.contains(scheme.toLowerCase(Locale.ROOT))) {
            throw new ApiException(ErrorCode.INVALID_SCHEME,
                    "only http and https destinations are accepted");
        }
        if (uri.getHost() == null || uri.getHost().isBlank()) {
            throw new ApiException(ErrorCode.MALFORMED_URL, "destination has no host");
        }
        return raw;
    }

    /** RFC 3986 scheme prefix, if the input declares one at all. */
    private static String declaredScheme(String raw) {
        int colon = raw.indexOf(':');
        if (colon <= 0) {
            return null;
        }
        String candidate = raw.substring(0, colon);
        if (!candidate.chars().allMatch(c -> Character.isLetterOrDigit(c)
                || c == '+' || c == '-' || c == '.')) {
            return null;
        }
        if (!Character.isLetter(candidate.charAt(0))) {
            return null;
        }
        return candidate.toLowerCase(Locale.ROOT);
    }

    /**
     * A comparison form only. The redirect always uses the stored original (FR-011), so this
     * lowercases the scheme and host and drops a default port, and touches nothing else —
     * path case and query order are significant to the target server.
     */
    public String canonicalise(String raw) {
        try {
            URI uri = new URI(raw.trim());
            String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
            int port = uri.getPort();
            boolean defaultPort = ("http".equals(scheme) && port == 80)
                    || ("https".equals(scheme) && port == 443);
            URI normalised = new URI(
                    scheme,
                    uri.getUserInfo(),
                    uri.getHost().toLowerCase(Locale.ROOT),
                    defaultPort ? -1 : port,
                    uri.getPath(),
                    uri.getQuery(),
                    uri.getFragment());
            return normalised.toString();
        } catch (URISyntaxException e) {
            throw new ApiException(ErrorCode.MALFORMED_URL, "destination is not a valid URL");
        }
    }
}
