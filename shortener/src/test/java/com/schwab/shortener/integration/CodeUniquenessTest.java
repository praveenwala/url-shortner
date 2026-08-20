package com.schwab.shortener.integration;

import static org.assertj.core.api.Assertions.assertThat;

import com.schwab.shortener.persistence.RedirectEventRepository;
import com.schwab.shortener.persistence.ShortLinkRepository;
import com.schwab.shortener.service.LinkService;
import com.schwab.shortener.support.PostgresSupport;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * T019 — no code collision ever overwrites an existing link (FR-004, SC-005).
 *
 * <p>Uniqueness is a property of the store — a primary key — not of application logic under
 * concurrency. This drives concurrent creators at the same table to prove it.
 */
@SpringBootTest
class CodeUniquenessTest extends PostgresSupport {

    @Autowired LinkService links;
    @Autowired ShortLinkRepository repository;
    @Autowired RedirectEventRepository events;

    @BeforeEach
    void clean() {
        events.deleteAll();
        repository.deleteAll();
    }

    @Test
    void concurrentCreationNeverOverwritesAnExistingLink() throws Exception {
        int threads = 8;
        int perThread = 125; // 1000 links
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        Set<String> codes = Collections.synchronizedSet(new HashSet<>());
        AtomicInteger failures = new AtomicInteger();

        for (int t = 0; t < threads; t++) {
            final int worker = t;
            pool.submit(() -> {
                for (int i = 0; i < perThread; i++) {
                    try {
                        codes.add(links.create(
                                "https://example.com/" + worker + "/" + i, null, "client-a").code());
                    } catch (Exception e) {
                        failures.incrementAndGet();
                    }
                }
            });
        }
        pool.shutdown();
        assertThat(pool.awaitTermination(120, TimeUnit.SECONDS)).isTrue();

        assertThat(failures.get()).isZero();
        assertThat(codes).hasSize(threads * perThread);
        assertThat(repository.count()).isEqualTo(threads * perThread);
    }

    @Test
    void everyStoredDestinationSurvivesIntact() {
        String first = links.create("https://example.com/one", null, "client-a").code();
        String second = links.create("https://example.com/two", null, "client-a").code();

        assertThat(first).isNotEqualTo(second);
        assertThat(repository.findById(first).orElseThrow().getDestination())
                .isEqualTo("https://example.com/one");
        assertThat(repository.findById(second).orElseThrow().getDestination())
                .isEqualTo("https://example.com/two");
    }

    @Test
    void theSameDestinationTwiceYieldsTwoIndependentLinks() {
        String first = links.create("https://example.com/same", null, "client-a").code();
        String second = links.create("https://example.com/same", null, "client-a").code();
        assertThat(first).isNotEqualTo(second);
    }
}
