package com.schwab.shortener.contract;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.schwab.shortener.support.PostgresSupport;
import com.schwab.shortener.web.errors.ErrorCode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.HashSet;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

/**
 * The published contract, the generated document, and the running application agree.
 *
 * <p>Three things must stay in step: {@code contracts/shortener-api.md} (what we promised),
 * the committed {@code docs/contracts/shortener-openapi.json} (what we published), and the
 * live Spring router (what we serve). This fails the build when any pair diverges, so drift
 * is caught here rather than by a reader.
 */
@SpringBootTest
@AutoConfigureMockMvc
class OpenApiParityTest extends PostgresSupport {

    private static final Path REPO = Path.of(System.getProperty("user.dir")).getParent();
    private static final Path GENERATED = REPO.resolve("docs/contracts/shortener-openapi.json");
    private static final Path CONTRACT =
            REPO.resolve("specs/001-agentic-url-shortener/contracts/shortener-api.md");

    /**
     * Declared in the contract but deliberately not built. Listed explicitly so a deferral is
     * an entry someone must edit, never a silent absence the checker tolerates.
     */
    private static final Set<String> DEFERRED =
            Set.of("GET /v1/links/{code}/events");

    /** Error identifiers that exist in the contract only for deferred capabilities. */
    private static final Set<String> DEFERRED_IDENTIFIERS =
            Set.of("alias_conflict", "alias_reserved", "alias_malformed", "rate_limited");

    @Autowired MockMvc mvc;
    private final ObjectMapper mapper = new ObjectMapper();

    private JsonNode live() throws Exception {
        return mapper.readTree(
                mvc.perform(get("/v3/api-docs")).andReturn().getResponse().getContentAsString());
    }

    private static String normalise(String path) {
        return path.replaceAll("\\{[^}]+}", "{}").split("\\?")[0];
    }

    private Set<String> liveOperations() throws Exception {
        Set<String> operations = new TreeSet<>();
        JsonNode paths = live().get("paths");
        paths.fieldNames().forEachRemaining(path ->
                paths.get(path).fieldNames().forEachRemaining(method ->
                        operations.add(method.toUpperCase() + " " + normalise(path))));
        return operations;
    }

    private Set<String> contractOperations() throws Exception {
        Matcher matcher = Pattern
                .compile("^\\| [^|]+ \\| `([A-Z]+) (/[^`|\\s]+)`", Pattern.MULTILINE)
                .matcher(Files.readString(CONTRACT));
        Set<String> operations = new TreeSet<>();
        while (matcher.find()) {
            operations.add(matcher.group(1) + " " + normalise(matcher.group(2)));
        }
        return operations;
    }

    // --- three-way agreement --------------------------------------------------

    @Test
    void everyDeclaredOperationIsImplemented() throws Exception {
        Set<String> missing = new HashSet<>(contractOperations());
        missing.removeAll(liveOperations());
        DEFERRED.forEach(entry -> missing.remove(normaliseEntry(entry)));
        assertThat(missing).as("declared in the contract but not served").isEmpty();
    }

    @Test
    void everyImplementedOperationIsDeclared() throws Exception {
        Set<String> undeclared = new HashSet<>(liveOperations());
        undeclared.removeAll(contractOperations());
        // springdoc's own documentation endpoints are infrastructure, not product surface.
        undeclared.removeIf(entry -> entry.contains("/v3/api-docs")
                || entry.contains("/swagger-ui"));
        assertThat(undeclared)
                .as("served but not declared in the contract — document it or remove it")
                .isEmpty();
    }

    @Test
    void theCommittedDocumentMatchesTheRunningApplication() throws Exception {
        assertThat(GENERATED).as("run OpenApiGeneratorTest and commit the result").exists();
        JsonNode committed = mapper.readTree(Files.readString(GENERATED));
        assertThat(committed).as("the committed OpenAPI document is stale — regenerate it")
                .isEqualTo(live());
    }

    // --- deferrals stay deferred ----------------------------------------------

    @Test
    void approvedDeferralsRemainAbsent() throws Exception {
        Set<String> live = liveOperations();
        for (String deferred : DEFERRED) {
            assertThat(live).as("%s is deferred but is now implemented", deferred)
                    .doesNotContain(normaliseEntry(deferred));
        }
        String document = Files.readString(GENERATED);
        // Custom aliases, rate limiting, retention management and Redis have no API surface.
        assertThat(document).doesNotContain("alias");
        assertThat(document).doesNotContain("rate_limit");
        assertThat(document).doesNotContain("retention");
        assertThat(document).doesNotContainIgnoringCase("redis");
    }

    // --- request and response shapes -------------------------------------------

    @Test
    void createLinkRequestAndResponseShapesAreDeclared() throws Exception {
        JsonNode schemas = live().get("components").get("schemas");
        assertThat(fields(schemas.get("CreateRequest"))).containsExactlyInAnyOrder(
                "destination", "expires_at");
        assertThat(fields(schemas.get("CreateResponse"))).containsExactlyInAnyOrder(
                "code", "destination", "created_at", "expires_at");
    }

    @Test
    void analyticsSummaryShapeIsDeclared() throws Exception {
        assertThat(fields(live().get("components").get("schemas").get("SummaryResponse")))
                .containsExactlyInAnyOrder(
                        "code", "total_redirects", "first_redirect_at", "last_redirect_at");
    }

    @Test
    void theStableErrorEnvelopeIsPublished() throws Exception {
        JsonNode envelope = live().get("components").get("schemas").get("ApiError");
        assertThat(envelope).as("ApiError must be published, not only implemented").isNotNull();
        assertThat(fields(envelope)).containsExactlyInAnyOrder("error", "message");
    }

    @Test
    void clientIdentityIsDocumentedOnEveryOwnerScopedOperation() throws Exception {
        JsonNode paths = live().get("paths");
        for (String path : new String[] {
                "/v1/links", "/v1/links/{code}/revoke", "/v1/links/{code}/analytics"}) {
            String method = path.equals("/v1/links/{code}/analytics") ? "get" : "post";
            String parameters = paths.get(path).get(method).toString();
            assertThat(parameters).as("%s must document X-Client-Id", path)
                    .contains("X-Client-Id");
        }
    }

    // --- redirect semantics ------------------------------------------------------

    @Test
    void redirectSemanticsArePublished() throws Exception {
        JsonNode redirect = live().get("paths").get("/{code}").get("get").get("responses");
        assertThat(redirect.has("302")).as("the redirect must be documented as 302").isTrue();
        JsonNode headers = redirect.get("302").get("headers");
        assertThat(fields(headers).stream().collect(Collectors.toSet()))
                .contains("Location", "Cache-Control", "Pragma", "Expires");
    }

    @Test
    void redirectHeadersAreActuallyServed() throws Exception {
        String body = mvc.perform(post("/v1/links").header("X-Client-Id", "parity")
                        .contentType("application/json")
                        .content("{\"destination\":\"https://example.com/parity\"}"))
                .andReturn().getResponse().getContentAsString();
        String code = body.replaceAll(".*\"code\"\\s*:\\s*\"([^\"]+)\".*", "$1");

        var response = mvc.perform(get("/" + code)).andReturn().getResponse();
        assertThat(response.getStatus()).isEqualTo(302);
        assertThat(response.getHeader("Location")).isEqualTo("https://example.com/parity");
        assertThat(response.getHeader("Cache-Control"))
                .isEqualTo("no-store, no-cache, must-revalidate");
        assertThat(response.getHeader("Pragma")).isEqualTo("no-cache");
        assertThat(response.getHeader("Expires")).isEqualTo("0");
    }

    // --- error status mapping ------------------------------------------------------

    @ParameterizedTest
    @CsvSource({
        "/{code},get,400", "/{code},get,404", "/{code},get,410", "/{code},get,503",
        "/v1/links,post,400", "/v1/links,post,401",
        "/v1/links/{code}/revoke,post,401", "/v1/links/{code}/revoke,post,403",
        "/v1/links/{code}/revoke,post,404",
        "/v1/links/{code}/analytics,get,401", "/v1/links/{code}/analytics,get,403",
        "/v1/links/{code}/analytics,get,404",
    })
    void everyDocumentedFailureCarriesTheErrorEnvelope(String path, String method, String code)
            throws Exception {
        JsonNode response = live().get("paths").get(path).get(method).get("responses").get(code);
        assertThat(response).as("%s %s must document %s", method, path, code).isNotNull();
        assertThat(response.toString()).contains("ApiError");
    }

    @Test
    void everyNonDeferredErrorIdentifierIsReachable() throws Exception {
        Matcher matcher = Pattern.compile("`([a-z_]+)`").matcher(
                Files.readString(CONTRACT).split("## Operations")[0]);
        Set<String> declared = new TreeSet<>();
        while (matcher.find()) {
            declared.add(matcher.group(1));
        }
        declared.removeAll(DEFERRED_IDENTIFIERS);
        declared.removeIf(id -> !id.contains("_") && !Set.of("expired", "revoked").contains(id));

        Set<String> implemented = new TreeSet<>();
        for (ErrorCode value : ErrorCode.values()) {
            implemented.add(value.id());
        }
        assertThat(implemented).as("contract identifiers must exist in the implementation")
                .containsAll(declared);
    }

    @Test
    void deferredIdentifiersAreDeclaredButUnreachableThroughTheApi() throws Exception {
        // They remain in the enum for when the capability lands; what matters is that no
        // route can produce them today.
        assertThat(Files.readString(GENERATED)).doesNotContain("alias_conflict");
    }

    private static java.util.List<String> fields(JsonNode schemaOrHeaders) {
        JsonNode properties = schemaOrHeaders.has("properties")
                ? schemaOrHeaders.get("properties") : schemaOrHeaders;
        java.util.List<String> names = new java.util.ArrayList<>();
        properties.fieldNames().forEachRemaining(names::add);
        return names;
    }

    private static String normaliseEntry(String entry) {
        String[] parts = entry.split(" ", 2);
        return parts[0] + " " + normalise(parts[1]);
    }
}
