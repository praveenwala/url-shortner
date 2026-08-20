package com.schwab.shortener.failure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schwab.shortener.persistence.RedirectEventRepository;
import com.schwab.shortener.persistence.ShortLinkRepository;
import com.schwab.shortener.support.PostgresSupport;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * T099 — the server never fetches a caller-supplied destination (FR-018, SC-017).
 *
 * <p>FR-018 is a prohibition, and a prohibition cannot be proved by asserting on a response
 * body: a service that quietly fetched every destination would return exactly the same 201 and
 * the same 302. So this test supplies destinations pointing at a <em>real HTTP server it
 * controls</em> and asserts that server was never contacted — across the whole corpus of
 * operations that see a destination: creation, resolution, repeated resolution, analytics
 * inspection, and revocation.
 *
 * <p>The listener binds loopback on an ephemeral port and records every request it receives.
 * The assertion is on its request log, which is the only evidence that distinguishes "did not
 * fetch" from "fetched and discarded the result".
 */
@SpringBootTest
@AutoConfigureMockMvc
class EgressTest extends PostgresSupport {

    /** Every request this listener receives is a violation of FR-018. */
    private static final List<String> RECEIVED = new CopyOnWriteArrayList<>();

    private static HttpServer listener;
    private static String destinationBase;

    @Autowired private MockMvc mockMvc;
    @Autowired private ShortLinkRepository links;
    @Autowired private RedirectEventRepository events;

    private final ObjectMapper mapper = new ObjectMapper();

    @BeforeAll
    static void startListener() throws IOException {
        listener = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), 0), 0);
        listener.createContext(
                "/",
                exchange -> {
                    RECEIVED.add(exchange.getRequestMethod() + " " + exchange.getRequestURI());
                    byte[] body = "should never be fetched".getBytes();
                    exchange.sendResponseHeaders(200, body.length);
                    exchange.getResponseBody().write(body);
                    exchange.close();
                });
        listener.start();
        destinationBase = "http://127.0.0.1:" + listener.getAddress().getPort();
    }

    @AfterAll
    static void stopListener() {
        listener.stop(0);
    }

    @BeforeEach
    void reset() {
        events.deleteAll();
        links.deleteAll();
        RECEIVED.clear();
    }

    private String createLink(String destination) throws Exception {
        String response =
                mockMvc.perform(
                                post("/v1/links")
                                        .header("X-Client-Id", "egress-test")
                                        .contentType("application/json")
                                        .content("{\"destination\":\"" + destination + "\"}"))
                        .andExpect(status().isCreated())
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        JsonNode node = mapper.readTree(response);
        return node.get("code").asText();
    }

    @Test
    void creatingALinkDoesNotFetchTheDestination() throws Exception {
        createLink(destinationBase + "/create-probe");
        assertThat(RECEIVED)
                .as("the server fetched a caller-supplied destination during creation")
                .isEmpty();
    }

    @Test
    void resolvingALinkDoesNotFetchTheDestination() throws Exception {
        String code = createLink(destinationBase + "/resolve-probe");

        mockMvc.perform(get("/" + code)).andExpect(status().isFound());
        mockMvc.perform(get("/" + code)).andExpect(status().isFound());
        mockMvc.perform(get("/" + code)).andExpect(status().isFound());

        assertThat(RECEIVED)
                .as("the server fetched the destination while issuing a redirect")
                .isEmpty();
    }

    @Test
    void analyticsAndRevocationDoNotFetchTheDestination() throws Exception {
        String code = createLink(destinationBase + "/analytics-probe");
        mockMvc.perform(get("/" + code)).andExpect(status().isFound());

        mockMvc.perform(get("/v1/links/" + code + "/analytics").header("X-Client-Id", "egress-test"))
                .andExpect(status().isOk());
        mockMvc.perform(post("/v1/links/" + code + "/revoke").header("X-Client-Id", "egress-test"))
                .andExpect(status().isOk());

        assertThat(RECEIVED)
                .as("the server fetched the destination during analytics or revocation")
                .isEmpty();
    }

    @Test
    void aRejectedDestinationIsNotFetchedEither() throws Exception {
        // Validation is syntactic. A destination that fails it must fail without a lookup —
        // "check whether it resolves" is the most natural way to accidentally introduce egress.
        mockMvc.perform(
                        post("/v1/links")
                                .header("X-Client-Id", "egress-test")
                                .contentType("application/json")
                                .content(
                                        "{\"destination\":\"" + destinationBase + "/x\","
                                                + "\"expires_at\":\"not-a-timestamp\"}"))
                .andExpect(status().isBadRequest());

        assertThat(RECEIVED).isEmpty();
    }

    @Test
    void theListenerItselfIsReachable() throws Exception {
        // Control. Without this, every assertion above would also pass against a listener that
        // was never started, a wrong port, or a closed socket.
        java.net.HttpURLConnection connection =
                (java.net.HttpURLConnection)
                        java.net.URI.create(destinationBase + "/control").toURL().openConnection();
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(5000);
        assertThat(connection.getResponseCode()).isEqualTo(200);
        connection.disconnect();

        assertThat(RECEIVED).as("the control request was not recorded").hasSize(1);
    }
}
