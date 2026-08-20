package com.schwab.shortener.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.schwab.shortener.persistence.RedirectEventRepository;
import com.schwab.shortener.persistence.ShortLinkRepository;
import com.schwab.shortener.support.PostgresSupport;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * T017 — the redirect is temporary and explicitly non-cacheable.
 *
 * <p>This is not a performance preference. A cached redirect never reaches the service, so it
 * would silently undercount (SC-006) and let revoked and expired links keep resolving.
 */
@SpringBootTest
@AutoConfigureMockMvc
class RedirectContractTest extends PostgresSupport {

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
                .andReturn().getResponse().getContentAsString();
        return body.replaceAll(".*\"code\"\\s*:\\s*\"([^\"]+)\".*", "$1");
    }

    @Test
    void redirectsToTheExactStoredDestination() throws Exception {
        String destination = "https://example.com/a/b?q=1&r=2";
        String code = create(destination);

        mvc.perform(get("/" + code))
                .andExpect(status().isFound())
                .andExpect(header().string("Location", destination));
    }

    @Test
    void redirectIsTemporaryNotPermanent() throws Exception {
        String code = create("https://example.com");
        mvc.perform(get("/" + code)).andExpect(status().isFound()); // 302, never 301/308
    }

    @Test
    void redirectIsExplicitlyNonCacheable() throws Exception {
        String code = create("https://example.com");
        mvc.perform(get("/" + code))
                .andExpect(header().string("Cache-Control", "no-store, no-cache, must-revalidate"))
                .andExpect(header().string("Pragma", "no-cache"))
                .andExpect(header().string("Expires", "0"));
    }

    @Test
    void aQueryParameterCannotRedirectSomewhereElse() throws Exception {
        String code = create("https://example.com/real");
        mvc.perform(get("/" + code + "?url=https://evil.example/&next=https://evil.example/"))
                .andExpect(header().string("Location", "https://example.com/real"));
    }

    @Test
    void everySuccessfulRedirectIsCountedBeforeTheResponse() throws Exception {
        String code = create("https://example.com");
        for (int i = 0; i < 5; i++) {
            mvc.perform(get("/" + code)).andExpect(status().isFound());
        }
        assertThat(links.findById(code).orElseThrow().getRedirectCount()).isEqualTo(5L);
        assertThat(events.countByCode(code)).isEqualTo(5L);
    }
}
