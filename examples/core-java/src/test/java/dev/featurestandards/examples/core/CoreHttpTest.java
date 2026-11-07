package dev.featurestandards.examples.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.featurestandards.auth.AuthService;
import dev.featurestandards.core.authorization.AuthorizationPolicy;
import dev.featurestandards.core.authorization.Principal;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import static org.assertj.core.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    classes = {CoreApplication.class, CoreHttpTest.Providers.class}, properties = {
        "AUTH_DEMO=true", "AUTH_STORE=memory", "AUTH_ACCOUNT_LIFECYCLE=false", "AUTH_COOKIE_SECURE=false",
        "AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173", "AUTH_RATE_LIMIT_MAX=1000"
    })
class CoreHttpTest {
    static final ObjectMapper JSON = new ObjectMapper();
    static final String ORIGIN = "http://127.0.0.1:5173";
    static final String LOGIN = "{\"email\":\"demo@example.com\",\"password\":\"correct-horse-battery-staple\"}";
    @LocalServerPort int port;
    @Autowired MutableMembership membership;
    @Autowired MutableDocuments documents;
    final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();

    @BeforeEach void resetProviders() {
        membership.roles = List.of("viewer"); membership.mode = "ok";
        documents.rows = CoreApplication.demoDocuments();
    }

    @Test void anonymousAndForgedSessions() throws Exception {
        for (var path : List.of("/api/documents", "/api/documents/own-a")) {
            error(request("GET", path, null, null), 401, "UNAUTHENTICATED");
            error(request("GET", path, null, "fs_session=forged"), 401, "UNAUTHENTICATED");
        }
    }

    @Test void dependencyUsesExternalLibraryJars() {
        assertThat(AuthService.class.getProtectionDomain().getCodeSource().getLocation().toString()).endsWith("java-spring-auth-1.0.0-library.jar");
        assertThat(AuthorizationPolicy.class.getProtectionDomain().getCodeSource().getLocation().toString()).endsWith("feature-standards-core-0.1.0.jar");
    }

    @Test void productRoutesAcceptGetOnly() throws Exception {
        var response = request("POST", "/api/documents", "", null);
        error(response, 405, "METHOD_NOT_ALLOWED");
        assertThat(response.headers().firstValue("Allow")).contains("GET");
    }

    @Test void ownerTenantAndMissingResources() throws Exception {
        var session = login();
        var own = request("GET", "/api/documents/own-a", null, session.cookie());
        assertThat(own.statusCode()).isEqualTo(200);
        assertThat(tree(own).path("id").asText()).isEqualTo("own-a");
        headers(own);
        assertThat(tree(own).has("ownerId")).isFalse();
        for (var id : List.of("other-owner", "other-tenant", "missing"))
            error(request("GET", "/api/documents/" + id, null, session.cookie()), 403, "FORBIDDEN");
    }

    @Test void visibilityPrecedesTotalsAndStablePagination() throws Exception {
        var session = login();
        var first = request("GET", "/api/documents?sort=-score&limit=1", null, session.cookie());
        assertThat(first.statusCode()).isEqualTo(200);
        var page = tree(first); headers(first);
        assertThat(page.path("total").asInt()).isEqualTo(2);
        assertThat(page.path("items").get(0).path("id").asText()).isEqualTo("own-a");
        assertThat(page.path("nextOffset").asInt()).isEqualTo(1);
        var second = tree(request("GET", "/api/documents?sort=-score&limit=1&offset=1", null, session.cookie()));
        assertThat(second.path("items").get(0).path("id").asText()).isEqualTo("own-b");
        assertThat(second.path("nextOffset").isNull()).isTrue();
        var past = tree(request("GET", "/api/documents?offset=10000", null, session.cookie()));
        assertThat(past.path("total").asInt()).isEqualTo(2);
        assertThat(past.path("items").size()).isZero();
        assertThat(past.path("nextOffset").isNull()).isTrue();
    }

    @Test void typedFiltersAndStrictRawQueries() throws Exception {
        var session = login();
        for (var query : List.of("filter.active=true", "filter.score=2&filter.name=Alpha")) {
            var response = request("GET", "/api/documents?" + query, null, session.cookie());
            assertThat(response.statusCode()).isEqualTo(200);
            assertThat(tree(response).path("total").asInt()).isEqualTo(1);
            assertThat(tree(response).path("items").get(0).path("id").asText()).isEqualTo("own-a");
        }
        for (var query : List.of("limit=1&%6cimit=2", "sort=ownerId", "filter.active=1", "offset=01", "role=admin", "filter.name=%FF", "filter.name=%00"))
            error(request("GET", "/api/documents?" + query, null, session.cookie()), 400, "INVALID_LIST_QUERY");
    }

    @Test void currentMembershipRevocationFailureAndSpoofing() throws Exception {
        var session = login();
        error(request("GET", "/api/documents/other-tenant", null, session.cookie(), "X-Role", "admin", "X-Tenant-Id", "tenant-b"), 403, "FORBIDDEN");
        membership.roles = List.of();
        error(request("GET", "/api/documents", null, session.cookie(), "X-Roles", "viewer", "X-Subject-Id", "other-user"), 403, "FORBIDDEN");
        membership.roles = List.of("viewer"); membership.mode = "unavailable";
        error(request("GET", "/api/documents", null, session.cookie()), 503, "AUTHORIZATION_UNAVAILABLE");
        membership.mode = "mismatch";
        error(request("GET", "/api/documents/own-a", null, session.cookie()), 403, "FORBIDDEN");
        membership.mode = "missing";
        error(request("GET", "/api/documents", null, session.cookie()), 403, "FORBIDDEN");
    }

    @Test void trustedMissingDataFailsGenerically() throws Exception {
        var session = login();
        documents.rows = List.of(Map.of("id", "own-a", "score", 2, "active", true, "tenantId", "tenant-a", "ownerId", "demo-user"));
        error(request("GET", "/api/documents", null, session.cookie()), 500, "INVALID_LIST_DATA");
        error(request("GET", "/api/documents/own-a", null, session.cookie()), 500, "INVALID_LIST_DATA");
        documents.rows = List.of(Map.of("id", "own-a", "name", "Alpha", "score", "private-invalid-number", "active", true, "tenantId", "tenant-a", "ownerId", "demo-user"));
        error(request("GET", "/api/documents?sort=score", null, session.cookie()), 500, "INVALID_LIST_DATA");
    }

    @Test void realLogoutRevokesBothProductRoutes() throws Exception {
        var session = login();
        error(request("POST", "/auth/logout", null, session.cookie(), "Origin", ORIGIN, "X-CSRF-Token", "wrong"), 403, "CSRF_INVALID");
        assertThat(request("GET", "/api/documents", null, session.cookie()).statusCode()).isEqualTo(200);
        var logout = request("POST", "/auth/logout", null, session.cookie(), "Origin", ORIGIN, "X-CSRF-Token", session.csrf());
        assertThat(logout.statusCode()).isEqualTo(204); assertThat(logout.body()).isEmpty();
        for (var path : List.of("/api/documents", "/api/documents/own-a"))
            error(request("GET", path, null, session.cookie()), 401, "UNAUTHENTICATED");
    }

    record Login(String cookie, String csrf) {}
    Login login() throws Exception {
        var response = request("POST", "/auth/login", LOGIN, null, "Origin", ORIGIN, "Content-Type", "application/json");
        assertThat(response.statusCode()).isEqualTo(200);
        return new Login(response.headers().firstValue("Set-Cookie").orElseThrow().split(";", 2)[0], tree(response).path("csrfToken").asText());
    }
    HttpResponse<String> request(String method, String path, String body, String cookie, String... headers) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path)).timeout(Duration.ofSeconds(5))
            .method(method, HttpRequest.BodyPublishers.ofString(body == null ? "" : body));
        if (cookie != null) request.header("Cookie", cookie);
        if (headers.length > 0) request.headers(headers);
        return client.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }
    static JsonNode tree(HttpResponse<String> response) throws Exception { return JSON.readTree(response.body()); }
    static void headers(HttpResponse<String> response) {
        assertThat(response.headers().allValues("Cache-Control")).containsExactly("no-store");
        assertThat(response.headers().allValues("X-Content-Type-Options")).containsExactly("nosniff");
    }
    static void error(HttpResponse<String> response, int status, String code) throws Exception {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(tree(response).path("error").path("code").asText()).isEqualTo(code);
        headers(response);
        assertThat(response.body()).doesNotContain("private-provider-detail", "private-invalid-number");
    }

    static final class MutableMembership implements MembershipProvider {
        volatile List<String> roles = List.of("viewer"); volatile String mode = "ok";
        public Principal resolve(AuthService.User user) {
            return switch (mode) {
                case "unavailable" -> throw new IllegalStateException("private-provider-detail");
                case "missing" -> null;
                case "mismatch" -> new Principal("other-user", "tenant-a", roles);
                default -> new Principal(user.id(), "tenant-a", roles);
            };
        }
    }
    static final class MutableDocuments implements DocumentProvider {
        volatile List<Map<String, Object>> rows = CoreApplication.demoDocuments();
        public List<Map<String, Object>> load() { return rows; }
    }
    @TestConfiguration static class Providers {
        @Bean @Primary MutableMembership currentMembership() { return new MutableMembership(); }
        @Bean @Primary MutableDocuments currentDocuments() { return new MutableDocuments(); }
    }
}
