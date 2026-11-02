package dev.featurestandards.examples;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.featurestandards.auth.AuthService;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Path;
import java.util.jar.JarFile;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import static org.assertj.core.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
    "AUTH_DEMO=true", "AUTH_STORE=memory", "AUTH_ACCOUNT_LIFECYCLE=false", "AUTH_COOKIE_SECURE=false",
    "AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173", "AUTH_SESSION_TTL_SECONDS=1800"
})
class ConsumerHttpTest {
    static final ObjectMapper JSON = new ObjectMapper();
    static final String ORIGIN = "http://127.0.0.1:5173";
    static final String LOGIN = "{\"email\":\"demo@example.com\",\"password\":\"correct-horse-battery-staple\"}";
    @LocalServerPort int port;
    final HttpClient client = HttpClient.newHttpClient();

    @Test void dependencyUsesInstalledPlainJar() throws Exception {
        var location = AuthService.class.getProtectionDomain().getCodeSource().getLocation();
        assertThat(location.toString()).endsWith("java-spring-auth-1.0.0-library.jar");
        try (var jar = new JarFile(Path.of(location.toURI()).toFile())) {
            assertThat(jar.getEntry("dev/featurestandards/auth/AuthService.class")).isNotNull();
            assertThat(jar.getEntry("BOOT-INF/classes/dev/featurestandards/auth/AuthService.class")).isNull();
            assertThat(jar.getEntry("application.properties")).isNull();
            assertThat(jar.getEntry("dev/featurestandards/auth/AuthApplication.class")).isNull();
        }
    }

    @Test void protectedProfileRequiresLiveSessionAndLogoutRevokesCopiedCookie() throws Exception {
        error(request("GET", "/api/profile", null, null), 401, "UNAUTHENTICATED");
        error(request("GET", "/api/profile", null, "fs_session=forged"), 401, "UNAUTHENTICATED");
        var login = request("POST", "/auth/login", LOGIN, null, "Origin", ORIGIN, "Content-Type", "application/json");
        assertThat(login.statusCode()).isEqualTo(200);
        String cookie = login.headers().firstValue("Set-Cookie").orElseThrow().split(";", 2)[0];
        String csrf = JSON.readTree(login.body()).path("csrfToken").asText();
        var profile = request("GET", "/api/profile", null, cookie);
        assertThat(profile.statusCode()).isEqualTo(200);
        assertThat(JSON.readTree(profile.body()).path("user"))
                .isEqualTo(JSON.readTree(login.body()).path("user"));
        var logout = request("POST", "/auth/logout", null, cookie, "Origin", ORIGIN, "X-CSRF-Token", csrf);
        assertThat(logout.statusCode()).isEqualTo(204);
        error(request("GET", "/api/profile", null, cookie), 401, "UNAUTHENTICATED");
        error(request("GET", "/auth/me", null, cookie), 401, "UNAUTHENTICATED");
    }

    @Test void failedCsrfPreservesProfileSession() throws Exception {
        var login = request("POST", "/auth/login", LOGIN, null, "Origin", ORIGIN, "Content-Type", "application/json");
        assertThat(login.statusCode()).isEqualTo(200);
        String cookie = login.headers().firstValue("Set-Cookie").orElseThrow().split(";", 2)[0];
        error(request("POST", "/auth/logout", null, cookie, "Origin", ORIGIN, "X-CSRF-Token", "wrong"), 403, "CSRF_INVALID");
        assertThat(request("GET", "/api/profile", null, cookie).statusCode()).isEqualTo(200);
    }

    private HttpResponse<String> request(String method, String path, String body, String cookie, String... headers) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .method(method, HttpRequest.BodyPublishers.ofString(body == null ? "" : body));
        if (cookie != null) request.header("Cookie", cookie);
        if (headers.length > 0) request.headers(headers);
        return client.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static void error(HttpResponse<String> response, int status, String code) throws Exception {
        // Avoid printing responses/cookies/tokens on a failing authentication assertion.
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(JSON.readTree(response.body()).path("error").path("code").asText()).isEqualTo(code);
        assertThat(response.headers().firstValue("Cache-Control")).contains("no-store");
    }
}
