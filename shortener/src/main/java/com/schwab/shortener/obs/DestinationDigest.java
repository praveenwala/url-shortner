package com.schwab.shortener.obs;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * Safe log representations of a caller-supplied destination.
 *
 * <p>The raw URL is never logged. A destination can carry a bearer token in its query string,
 * credentials in its userinfo, or a customer identifier in its path — and operational logs go to
 * stdout, where they are collected, shipped and retained.
 *
 * <p>Two derivations are offered instead. The <em>host</em> is taken from {@link URI#getHost()},
 * which structurally cannot include userinfo, path, query or fragment — this is parsing, not
 * string trimming, so there is no regex to get wrong. The <em>hash</em> is a full SHA-256 of the
 * complete destination, which correlates repeated submissions of the same URL across requests
 * without disclosing it.
 */
public final class DestinationDigest {

    private static final String UNKNOWN_HOST = "unparseable";

    private DestinationDigest() {}

    /**
     * Host only, or {@code "unparseable"}.
     *
     * <p>Deliberately returns the host and nothing else: {@code URI.getHost()} excludes userinfo by
     * definition, so a destination like {@code https://user:pw@example.com/p?t=secret} yields
     * exactly {@code example.com}.
     */
    public static String host(String destination) {
        try {
            String host = URI.create(destination).getHost();
            return (host == null || host.isBlank()) ? UNKNOWN_HOST : host;
        } catch (RuntimeException e) {
            return UNKNOWN_HOST;
        }
    }

    /** SHA-256 of the whole destination, hex encoded. Correlates without disclosing. */
    public static String hash(String destination) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(
                    digest.digest(destination.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            // SHA-256 is mandated by the platform; unreachable in practice.
            return "unavailable";
        }
    }
}
