package com.schwab.shortener.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.schwab.shortener.domain.CodeGenerator;
import com.schwab.shortener.domain.CodeGenerator.CollisionExhausted;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

/** T021 — code shape and bounded collision retry (FR-004, R12, Principle VII). */
class CodeGeneratorTest {

    private static final String ALPHABET =
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

    @Test
    void generatesSevenCharactersFromTheSixtyTwoSymbolAlphabet() {
        CodeGenerator generator = new CodeGenerator(code -> false);
        for (int i = 0; i < 500; i++) {
            String code = generator.generate();
            assertThat(code).hasSize(7);
            assertThat(code.chars()).allMatch(c -> ALPHABET.indexOf(c) >= 0);
        }
    }

    @Test
    void isCaseSensitiveAcrossTheFullAlphabet() {
        CodeGenerator generator = new CodeGenerator(code -> false);
        Set<Character> seen = new HashSet<>();
        for (int i = 0; i < 4000; i++) {
            for (char c : generator.generate().toCharArray()) {
                seen.add(c);
            }
        }
        assertThat(seen).contains('a', 'A', 'z', 'Z', '0', '9');
    }

    @Test
    void producesDistinctCodes() {
        CodeGenerator generator = new CodeGenerator(code -> false);
        Set<String> codes = new HashSet<>();
        for (int i = 0; i < 5000; i++) {
            codes.add(generator.generate());
        }
        // 62^7 is ~3.5e12; 5000 draws colliding is vanishingly unlikely.
        assertThat(codes).hasSize(5000);
    }

    @Test
    void retriesOnCollisionThenSucceeds() {
        AtomicInteger attempts = new AtomicInteger();
        CodeGenerator generator = new CodeGenerator(code -> attempts.incrementAndGet() <= 2);

        assertThat(generator.generate()).hasSize(7);
        assertThat(attempts.get()).isEqualTo(3);
    }

    @Test
    void retryIsBoundedRatherThanLooping() {
        AtomicInteger attempts = new AtomicInteger();
        CodeGenerator generator = new CodeGenerator(code -> {
            attempts.incrementAndGet();
            return true; // every code collides
        });

        assertThatThrownBy(generator::generate).isInstanceOf(CollisionExhausted.class);
        assertThat(attempts.get()).isEqualTo(CodeGenerator.MAX_ATTEMPTS);
    }
}
