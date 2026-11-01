package dev.featurestandards.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.junit.jupiter.api.MethodOrderer;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import static org.assertj.core.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
    "AUTH_DEMO=true", "AUTH_COOKIE_SECURE=false", "AUTH_RATE_LIMIT_MAX=3", "AUTH_RATE_LIMIT_WINDOW_SECONDS=10",
    "AUTH_SESSION_TTL_SECONDS=2", "server.address=127.0.0.1"
})
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class AuthHttpTest {
    static final String ORIGIN = "http://127.0.0.1:5173";
    static final String LOGIN = "{\"email\":\"demo@example.com\",\"password\":\"correct-horse-battery-staple\"}";
    static final ObjectMapper JSON = new ObjectMapper();
    @LocalServerPort int port;
    final HttpClient client = HttpClient.newHttpClient();
    HttpResponse<String> initial;

    @BeforeEach void clearPeerFailures() throws Exception {
        initial = request("POST", "/auth/login", LOGIN, null, "Origin", ORIGIN, "Content-Type", "application/json");
        assertThat(initial.statusCode()).isEqualTo(200);
    }
    @Test void anonymousMeUsesContractError() throws Exception {
        error(request("GET", "/auth/me", null, null), 401, "UNAUTHENTICATED");
        error(request("GET", "/auth/me", null, "fs_session=forged"), 401, "UNAUTHENTICATED");
    }
    @Test void loginReturnsUserAndIndependentTokensAndCookiePolicy() throws Exception {
        var body = JSON.readTree(initial.body());
        assertThat(body.path("user").path("email").asText()).isEqualTo("demo@example.com");
        assertThat(body.path("user").path("id").asText()).isEqualTo("demo-user");
        assertThat(body.path("csrfToken").asText()).hasSize(43);
        String cookie = initial.headers().firstValue("Set-Cookie").orElseThrow();
        assertThat(cookie).contains("Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=2").doesNotContain("Secure", "Domain");
        var me = request("GET", "/auth/me", null, cookie(initial));
        assertThat(JSON.readTree(me.body())).isEqualTo(body);
        assertThat(me.headers().firstValue("Cache-Control")).contains("no-store");
    }
    @Test void methodAndUnknownPathUseContractErrors() throws Exception {
        for (String[] pair : new String[][]{{"GET", "/auth/login"}, {"GET", "/auth/logout"}, {"POST", "/auth/me"}, {"OPTIONS", "/auth/login"}}) {
            var response = request(pair[0], pair[1], null, null);
            error(response, 405, "METHOD_NOT_ALLOWED");
            assertThat(response.headers().firstValue("Allow")).isPresent();
            assertThat(response.headers().firstValue("Access-Control-Allow-Origin")).isEmpty();
        }
        error(request("GET", "/auth/missing", null, null), 404, "NOT_FOUND");
        var health = request("GET", "/healthz", null, null);
        assertThat(health.statusCode()).isEqualTo(200);
        assertThat(health.body()).contains("browser-session-v1", "java-spring").doesNotContain("demo@example.com");
    }
    @Test void originMustBeExactAndSingleAndFormatErrorsDoNotConsumeLimit() throws Exception {
        error(request("POST", "/auth/login", LOGIN, null, "Content-Type", "application/json"), 403, "ORIGIN_DENIED");
        for (String origin : new String[]{"null", ORIGIN + ".evil", ORIGIN + "/", "https://evil.example"}) {
            error(request("POST", "/auth/login", LOGIN, null, "Origin", origin, "Content-Type", "application/json"), 403, "ORIGIN_DENIED");
        }
        error(request("POST", "/auth/login", LOGIN, null, "Origin", ORIGIN, "Origin", ORIGIN, "Content-Type", "application/json"), 403, "ORIGIN_DENIED");
        for (int i = 0; i < 4; i++) error(request("POST", "/auth/login", "{}", null, "Origin", ORIGIN, "Content-Type", "application/json"), 400, "INVALID_REQUEST");
        assertThat(login(null).statusCode()).isEqualTo(200);
    }
    @Test void enforcesContentTypeAndExactBodyByteLimit() throws Exception {
        error(request("POST", "/auth/login", "{}", null, "Origin", ORIGIN), 415, "UNSUPPORTED_MEDIA_TYPE");
        error(request("POST", "/auth/login", "{}", null, "Origin", ORIGIN, "Content-Type", "text/json"), 415, "UNSUPPORTED_MEDIA_TYPE");
        error(request("POST", "/auth/login", "x".repeat(4097), null, "Origin", ORIGIN, "Content-Type", "application/json"), 413, "REQUEST_TOO_LARGE");
        assertThat(request("POST", "/auth/login", LOGIN + " ".repeat(4096 - LOGIN.length()), null,
                "Origin", ORIGIN, "Content-Type", "application/json; charset=utf-8").statusCode()).isEqualTo(200);
    }
    @Test void malformedUtf8AndSurrogateJsonAreRejectedOverHttp() throws Exception {
        byte[] body = LOGIN.getBytes(StandardCharsets.UTF_8); body[10] = (byte) 0xff;
        var req = builder("POST", "/auth/login", body, null, "Origin", ORIGIN, "Content-Type", "application/json");
        error(client.send(req, HttpResponse.BodyHandlers.ofString()), 400, "INVALID_REQUEST");
        error(request("POST", "/auth/login", "{\"email\":\"demo@example.com\",\"password\":\"\\ud800\"}", null,
                "Origin", ORIGIN, "Content-Type", "application/json"), 400, "INVALID_REQUEST");
    }
    @Test void normalizedEmailAndGenericCredentialFailures() throws Exception {
        assertThat(request("POST", "/auth/login", LOGIN.replace("demo@example.com", "  DEMO@EXAMPLE.COM  "), null,
                "Origin", ORIGIN, "Content-Type", "application/json").statusCode()).isEqualTo(200);
        var wrong = request("POST", "/auth/login", LOGIN.replace("correct-horse-battery-staple", "wrong"), null,
                "Origin", ORIGIN, "Content-Type", "application/json");
        var unknown = request("POST", "/auth/login", LOGIN.replace("demo@example.com", "missing@example.com"), null,
                "Origin", ORIGIN, "Content-Type", "application/json");
        error(wrong, 401, "INVALID_CREDENTIALS"); error(unknown, 401, "INVALID_CREDENTIALS");
        assertThat(wrong.body()).isEqualTo(unknown.body());
    }
    @Test void rotationAndCsrfBoundToSessionWithOtherBrowserPreserved() throws Exception {
        String old = cookie(initial);
        var other = login(null);
        var rotated = login(old);
        assertThat(cookie(rotated)).isNotEqualTo(old);
        error(request("GET", "/auth/me", null, old), 401, "UNAUTHENTICATED");
        assertThat(request("GET", "/auth/me", null, cookie(other)).statusCode()).isEqualTo(200);
        error(request("POST", "/auth/logout", null, cookie(rotated), "Origin", ORIGIN, "X-CSRF-Token", csrf(other)), 403, "CSRF_INVALID");
        assertThat(request("GET", "/auth/me", null, cookie(rotated)).statusCode()).isEqualTo(200);
    }
    @Test void failedLogoutPreservesSessionAndSuccessfulLogoutRevokesCopiedCookie() throws Exception {
        String cookie = cookie(initial);
        error(request("POST", "/auth/logout", null, cookie, "Origin", ORIGIN), 403, "CSRF_INVALID");
        error(request("POST", "/auth/logout", null, cookie, "Origin", "https://evil.example", "X-CSRF-Token", csrf(initial)), 403, "ORIGIN_DENIED");
        assertThat(request("GET", "/auth/me", null, cookie).statusCode()).isEqualTo(200);
        var logout = request("POST", "/auth/logout", null, cookie, "Origin", ORIGIN, "X-CSRF-Token", csrf(initial));
        assertThat(logout.statusCode()).isEqualTo(204); assertThat(logout.body()).isEmpty();
        assertThat(logout.headers().firstValue("Set-Cookie").orElseThrow()).contains("Max-Age=0", "Path=/", "HttpOnly", "SameSite=Lax");
        error(request("GET", "/auth/me", null, cookie), 401, "UNAUTHENTICATED");
        assertThat(request("POST", "/auth/logout", null, cookie, "Origin", ORIGIN).statusCode()).isEqualTo(204);
    }
    @Test void readsDoNotExtendAbsoluteExpiry() throws Exception {
        String cookie = cookie(initial);
        Thread.sleep(1100);
        assertThat(request("GET", "/auth/me", null, cookie).statusCode()).isEqualTo(200);
        Thread.sleep(1100);
        error(request("GET", "/auth/me", null, cookie), 401, "UNAUTHENTICATED");
        assertThat(request("POST", "/auth/logout", null, cookie, "Origin", ORIGIN).statusCode()).isEqualTo(204);
    }
    @Test @Order(Integer.MAX_VALUE) void peerRateLimitIgnoresForwardedHeaders() throws Exception {
        for (int i = 0; i < 3; i++) error(request("POST", "/auth/login", LOGIN.replace("correct-horse-battery-staple", "wrong"), null,
                "Origin", ORIGIN, "Content-Type", "application/json", "X-Forwarded-For", "198.51.100." + i), 401, "INVALID_CREDENTIALS");
        var blocked = login(null);
        error(blocked, 429, "RATE_LIMITED");
        assertThat(Long.parseLong(blocked.headers().firstValue("Retry-After").orElseThrow())).isPositive();
    }
    private HttpResponse<String> login(String cookie) throws Exception { return request("POST", "/auth/login", LOGIN, cookie, "Origin", ORIGIN, "Content-Type", "application/json"); }
    private String cookie(HttpResponse<String> response) { return response.headers().firstValue("Set-Cookie").orElseThrow().split(";", 2)[0]; }
    private String csrf(HttpResponse<String> response) throws Exception { return JSON.readTree(response.body()).path("csrfToken").asText(); }
    private HttpResponse<String> request(String method, String path, String body, String cookie, String... headers) throws Exception {
        return client.send(builder(method, path, body == null ? new byte[0] : body.getBytes(StandardCharsets.UTF_8), cookie, headers), HttpResponse.BodyHandlers.ofString());
    }
    private HttpRequest builder(String method, String path, byte[] body, String cookie, String... headers) {
        var builder = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path)).method(method, HttpRequest.BodyPublishers.ofByteArray(body));
        if (cookie != null) builder.header("Cookie", cookie);
        if (headers.length > 0) builder.headers(headers);
        return builder.build();
    }
    private void error(HttpResponse<String> response, int status, String code) throws Exception {
        assertThat(response.statusCode()).as(response.body()).isEqualTo(status);
        assertThat(JSON.readTree(response.body()).path("error").path("code").asText()).isEqualTo(code);
        assertThat(response.headers().firstValue("Cache-Control")).contains("no-store");
        assertThat(response.headers().firstValue("X-Content-Type-Options")).contains("nosniff");
        assertThat(response.body()).doesNotContain("correct-horse-battery-staple", "fs_session=");
    }
}
