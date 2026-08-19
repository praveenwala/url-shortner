package com.schwab.shortener.support;

import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * Testcontainers PostgreSQL harness (T010, R3, R10).
 *
 * <p>Integration tests run against real PostgreSQL, never H2 or an in-memory substitute: the
 * store was chosen for its concurrency and locking semantics, and testing against a different
 * engine is how concurrency bugs survive to release.
 */
public abstract class PostgresSupport {

    protected static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("postgres:16-alpine");

    static {
        POSTGRES.start();
    }

    @DynamicPropertySource
    static void datasourceProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }
}
