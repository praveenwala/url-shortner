package com.schwab.shortener.domain;

import java.security.SecureRandom;
import java.util.function.Predicate;

/**
 * Short code generation (FR-004, R12, Constitution Principle VII).
 *
 * <p>Seven characters over a 62-symbol case-sensitive alphabet — roughly 3.5e12 codes, so
 * collisions are vanishingly rare at the scale in NFR-005. Random rather than sequential so a
 * code is not enumerable and one client's volume is not visible to another.
 *
 * <p>The retry is <em>bounded</em>: Principle VII prohibits unbounded retry anywhere, and that
 * includes here. Uniqueness itself is enforced by the primary key, not by this check — the
 * collision predicate is an optimisation that keeps the common path free of exception handling.
 */
public class CodeGenerator {

    public static final int LENGTH = 7;
    public static final int MAX_ATTEMPTS = 3;
    private static final char[] ALPHABET =
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789".toCharArray();

    private final SecureRandom random = new SecureRandom();
    private final Predicate<String> alreadyTaken;

    public CodeGenerator(Predicate<String> alreadyTaken) {
        this.alreadyTaken = alreadyTaken;
    }

    public String generate() {
        for (int attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
            String candidate = draw();
            if (!alreadyTaken.test(candidate)) {
                return candidate;
            }
        }
        throw new CollisionExhausted(
                "could not find an unused short code in " + MAX_ATTEMPTS + " attempts");
    }

    private String draw() {
        char[] buffer = new char[LENGTH];
        for (int i = 0; i < LENGTH; i++) {
            buffer[i] = ALPHABET[random.nextInt(ALPHABET.length)];
        }
        return new String(buffer);
    }

    public static boolean isWellFormed(String code) {
        if (code == null || code.length() != LENGTH) {
            return false;
        }
        return code.chars().allMatch(c ->
                (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9'));
    }

    /** Bounded retry exhausted — a failure to report, never a loop to continue. */
    public static class CollisionExhausted extends RuntimeException {
        public CollisionExhausted(String message) {
            super(message);
        }
    }
}
