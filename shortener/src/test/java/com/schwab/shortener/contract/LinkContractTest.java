package com.schwab.shortener.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.schwab.shortener.persistence.RedirectEventRepository;
import com.schwab.shortener.persistence.ShortLinkRepository;
import com.schwab.shortener.support.PostgresSupport;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * T016 — link creation and the distinct resolution outcomes (FR-001, FR-003, FR-009, SC-004).
 */
@SpringBootTest
@AutoConfigureMockMvc
class LinkContractTest extends PostgresSupport {

    @Autowired MockMvc mvc;
    @Autowired ShortLinkRepository links;
    @Autowired RedirectEventRepository events;

    @BeforeEach
    void clean() {
        events.deleteAll();
        links.deleteAll();
    }

    private String create(String destination) throws Exception {
        String body = mvc.perform(post("/v1/links")
                        .header("X-Client-Id", "client-a")
                        .contentType("application/json")
                        .content("{\"destination\":\"" + destination + "\"}"))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return body.replaceAll(".*\"code\"\\s*:\\s*\"([^\"]+)\".*", "$1");
    }

    @Test
    void createsAShortLinkForAValidHttpsDestination() throws Exception {
        mvc.perform(post("/v1/links")
                        .header("X-Client-Id", "client-a")
                        .contentType("application/json")
                        .content("{\"destination\":\"https://example.com/a\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.code").isString())
                .andExpect(jsonPath("$.destination").value("https://example.com/a"))
                .andExpect(jsonPath("$.created_at").isString())
                .andExpect(jsonPath("$.expires_at").doesNotExist());
    }

    @Test
    void acceptsAnOptionalExpiry() throws Exception {
        String expiry = Instant.now().plus(1, ChronoUnit.DAYS).toString();
        mvc.perform(post("/v1/links")
                        .header("X-Client-Id", "client-a")
                        .contentType("application/json")
                        .content("{\"destination\":\"https://example.com\",\"expires_at\":\""
                                + expiry + "\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.expires_at").isString());
    }

    @Test
    void creationRequiresAClientIdentity() throws Exception {
        mvc.perform(post("/v1/links")
                        .contentType("application/json")
                        .content("{\"destination\":\"https://example.com\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("forbidden"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"javascript:alert(1)", "data:text/html,x", "file:///etc/passwd",
                            "ftp://example.com"})
    void refusesNonHttpSchemesWithADistinctIdentifier(String destination) throws Exception {
        mvc.perform(post("/v1/links")
                        .header("X-Client-Id", "client-a")
                        .contentType("application/json")
                        .content("{\"destination\":\"" + destination + "\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("invalid_scheme"));
        assertThat(links.count()).isZero();
    }

    @Test
    void refusesAMalformedUrl() throws Exception {
        mvc.perform(post("/v1/links")
                        .header("X-Client-Id", "client-a")
                        .contentType("application/json")
                        .content("{\"destination\":\"not a url\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("malformed_url"));
        assertThat(links.count()).isZero();
    }

    @Test
    void unknownCodeIsDistinctFromEverythingElse() throws Exception {
        mvc.perform(get("/zzzzzzz"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("not_found"));
    }

    @Test
    void malformedCodeIsItsOwnOutcome() throws Exception {
        mvc.perform(get("/not-a-valid-code!"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("malformed_url"));
    }

    @Test
    void expiredLinkIsDistinctFromUnknown() throws Exception {
        String code = create("https://example.com/expired");
        links.findById(code).ifPresent(link -> {
            link.setExpiresAt(Instant.now().minusSeconds(60));
            links.save(link);
        });

        mvc.perform(get("/" + code))
                .andExpect(status().isGone())
                .andExpect(jsonPath("$.error").value("expired"));
    }

    @Test
    void revokedLinkIsDistinctFromExpiredAndUnknown() throws Exception {
        String code = create("https://example.com/revoked");
        mvc.perform(post("/v1/links/" + code + "/revoke").header("X-Client-Id", "client-a"))
                .andExpect(status().isOk());

        mvc.perform(get("/" + code))
                .andExpect(status().isGone())
                .andExpect(jsonPath("$.error").value("revoked"));
    }

    @Test
    void reservedPathsAreNeverIssuedOrResolved() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isNotFound());
    }

    @Test
    void everyFailureIdentifierIsDistinct() throws Exception {
        String code = create("https://example.com/x");
        links.findById(code).ifPresent(link -> {
            link.setExpiresAt(Instant.now().minusSeconds(1));
            links.save(link);
        });
        String expired = mvc.perform(get("/" + code)).andReturn().getResponse().getContentAsString();
        String unknown = mvc.perform(get("/zzzzzzz")).andReturn().getResponse().getContentAsString();
        String malformed = mvc.perform(get("/!!")).andReturn().getResponse().getContentAsString();

        assertThat(expired).contains("expired");
        assertThat(unknown).contains("not_found");
        assertThat(malformed).contains("malformed_url");
        assertThat(expired).isNotEqualTo(unknown).isNotEqualTo(malformed);
    }
}
