package dev.featurestandards.auth;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import static org.assertj.core.api.Assertions.*;

class AccountBoundaryTest {
    static final String TOKEN = "A".repeat(43);
    static final String PASSWORD = "new-correct-horse-password";
    static AuthConfig config() {
        return AuthConfig.load(Map.of("AUTH_DEMO", "true", "AUTH_STORE", "postgres",
                "AUTH_ACCOUNT_LIFECYCLE", "true", "AUTH_DATABASE_URL",
                "postgresql://test@127.0.0.1:5432/feature_standards_test_v3_java?sslmode=disable")::get);
    }
    static AuthStore store() {
        return new AuthStore() {
            public AuthService.Login login(String peer, String old, String email, String password) { return null; }
            public AuthService.Session session(String token) { return null; }
            public boolean logout(String token, String csrf) { return true; }
        };
    }
    @Test void selectedLifecycleAdvertisesV3WithoutDependingOnDatabaseInHttp() throws Exception {
        var response = new MockHttpServletResponse();
        new AuthFilter(config(), new AuthService(store())).doFilter(new MockHttpServletRequest("GET", "/healthz"),
                response, (a, b) -> fail("Unexpected chain"));
        assertThat(response.getContentAsString()).contains("browser-session-v3");
    }
    @Test void routesStayHiddenInBothExistingProfiles() throws Exception {
        for (AuthConfig config : new AuthConfig[]{AuthConfig.load(Map.of("AUTH_DEMO", "true")::get),
                AuthConfig.load(Map.of("AUTH_DEMO", "true", "AUTH_STORE", "postgres", "AUTH_DATABASE_URL",
                        "postgresql://test@localhost/feature_standards_test?sslmode=disable")::get)}) {
            var filter = new AuthFilter(config, new AuthService(store()));
            for (String path : new String[]{"/auth/register", "/auth/email-verification/request", "/auth/email-verification/confirm",
                    "/auth/password-reset/request", "/auth/password-reset/confirm"}) {
                assertThat(send(filter, "POST", path, "{}", true, true).getStatus()).isEqualTo(404);
            }
        }
    }
    @Test void allFiveActionsPassOnlyValidatedInputsAndDoNotIssueCookies() throws Exception {
        var capture = new Capture();
        var filter = new AuthFilter(config(), new AuthService(capture));
        var register = send(filter, "POST", "/auth/register", "{\"email\":\"  한@EXAMPLE.COM  \",\"password\":\"" + PASSWORD + "\"}", true, true);
        assertThat(register.getStatus()).isEqualTo(202);
        assertThat(register.getContentAsString()).isEqualTo("{\"status\":\"accepted\"}");
        assertThat(capture.action).isEqualTo("register");
        assertThat(capture.email).isEqualTo("한@example.com");
        assertThat(capture.token).isEmpty();
        assertThat(capture.password).isEqualTo(PASSWORD);
        for (String[] path : new String[][]{{"/auth/email-verification/request", "verify-request"}, {"/auth/password-reset/request", "reset-request"}}) {
            var response = send(filter, "POST", path[0], "{\"email\":\"missing@example.com\"}", true, true);
            assertThat(response.getStatus()).isEqualTo(202);
            assertThat(response.getContentAsString()).isEqualTo(register.getContentAsString());
            assertThat(capture.action).isEqualTo(path[1]);
            assertThat(capture.password).isEmpty();
            assertThat(capture.token).isEmpty();
        }
        for (String[] path : new String[][]{{"/auth/email-verification/confirm", "verify-confirm"}, {"/auth/password-reset/confirm", "reset-confirm"}}) {
            String body = "{\"token\":\"" + TOKEN + "\"" + (path[1].equals("reset-confirm") ? ",\"password\":\"" + PASSWORD + "\"" : "") + "}";
            var response = send(filter, "POST", path[0], body, true, true);
            assertThat(response.getStatus()).isEqualTo(204);
            assertThat(response.getContentAsString()).isEmpty();
            assertThat(capture.action).isEqualTo(path[1]);
            assertThat(capture.email).isEmpty();
            assertThat(capture.token).isEqualTo(TOKEN);
        }
    }
    @Test void strictInputAndOriginFailuresNeverReachStorage() throws Exception {
        var capture = new Capture();
        var filter = new AuthFilter(config(), new AuthService(capture));
        for (String body : new String[]{"null", "[]", "{}", "{\"email\":12}", "{\"email\":\"x@y\",\"extra\":\"x\"}",
                "{\"email\":\"x@y\",\"email\":\"z@y\"}", "{\"email\":\"\\ud800@example.com\"}", "{\"email\":\"x@y\"} {}"}) {
            assertThat(send(filter, "POST", "/auth/password-reset/request", body, true, true).getStatus()).isEqualTo(400);
        }
        assertThat(send(filter, "POST", "/auth/password-reset/request", "{}", false, true).getStatus()).isEqualTo(403);
        assertThat(send(filter, "POST", "/auth/password-reset/request", "{}", true, false).getStatus()).isEqualTo(415);
        assertThat(send(filter, "POST", "/auth/password-reset/request", "x".repeat(4097), true, true).getStatus()).isEqualTo(413);
        var method = send(filter, "GET", "/auth/password-reset/request", "", false, false);
        assertThat(method.getStatus()).isEqualTo(405);
        assertThat(method.getHeader("Allow")).isEqualTo("POST");
        assertThat(capture.calls.get()).isZero();
    }
    @Test void passwordPolicyCountsUnicodeScalarsWithoutTrimmingAndTokenFormatIsStrict() {
        assertThatThrownBy(() -> AccountInput.checked("register", "x@y", "", "😀".repeat(14))).isInstanceOf(IllegalArgumentException.class);
        assertThat(AccountInput.checked("register", "x@y", "", "😀".repeat(15)).password()).isEqualTo("😀".repeat(15));
        String spaces = " ".repeat(15);
        assertThat(AccountInput.checked("reset-confirm", "", TOKEN, spaces).password()).isEqualTo(spaces);
        assertThatThrownBy(() -> AccountInput.checked("register", "x@y", "", "한".repeat(342))).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> AccountInput.checked("reset-confirm", "", TOKEN + "=", PASSWORD)).isInstanceOf(IllegalArgumentException.class);
        for (String email : new String[]{"x\u0000@y", "x\r\n@y", "x y@z", "x\u007f@y"}) {
            assertThatThrownBy(() -> AccountInput.checked("reset-request", email, "", "")).isInstanceOf(IllegalArgumentException.class);
        }
        assertThatThrownBy(() -> AccountInput.decode("verify-confirm", ("{\"token\":\"" + TOKEN + "\",\"password\":\"" + PASSWORD + "\"}").getBytes(StandardCharsets.UTF_8)))
                .isInstanceOf(IllegalArgumentException.class);
        byte[] malformed = "{\"email\":\"x@y\"}".getBytes(StandardCharsets.UTF_8); malformed[10] = (byte) 0xff;
        assertThatThrownBy(() -> AccountInput.decode("reset-request", malformed)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test void invalidTokenRateLimitAndUnavailableStorageUseGenericErrorsWithoutCookies() throws Exception {
        var capture = new Capture();
        var filter = new AuthFilter(config(), new AuthService(capture));
        capture.result = -1;
        var invalid = send(filter, "POST", "/auth/email-verification/confirm", "{\"token\":\"" + TOKEN + "\"}", true, true);
        assertThat(invalid.getStatus()).isEqualTo(400);
        assertThat(invalid.getContentAsString()).contains("INVALID_TOKEN").doesNotContain(TOKEN);
        capture.result = 23;
        var limited = send(filter, "POST", "/auth/password-reset/request", "{\"email\":\"x@y\"}", true, true);
        assertThat(limited.getStatus()).isEqualTo(429);
        assertThat(limited.getHeader("Retry-After")).isEqualTo("23");
        capture.unavailable = true;
        var unavailable = send(filter, "POST", "/auth/register", "{\"email\":\"x@y\",\"password\":\"" + PASSWORD + "\"}", true, true);
        assertThat(unavailable.getStatus()).isEqualTo(503);
        assertThat(unavailable.getContentAsString()).contains("STORAGE_UNAVAILABLE").doesNotContain(PASSWORD);
    }
    static MockHttpServletResponse send(AuthFilter filter, String method, String path, String body, boolean origin, boolean json) throws Exception {
        var request = new MockHttpServletRequest(method, path);
        if (origin) request.addHeader("Origin", config().origin());
        if (json) request.addHeader("Content-Type", "application/json");
        request.setContent(body.getBytes(StandardCharsets.UTF_8));
        var response = new MockHttpServletResponse();
        filter.doFilter(request, response, (a, b) -> fail("Unexpected chain"));
        assertThat(response.getHeader("Set-Cookie")).isNull();
        assertThat(response.getHeader("Cache-Control")).isEqualTo("no-store");
        assertThat(response.getHeader("X-Content-Type-Options")).isEqualTo("nosniff");
        return response;
    }
    static class Capture implements AuthStore {
        String action, email, token, password;
        int result;
        boolean unavailable;
        AtomicInteger calls = new AtomicInteger();
        public AuthService.Login login(String peer, String old, String email, String password) { return null; }
        public AuthService.Session session(String token) { return null; }
        public boolean logout(String token, String csrf) { return true; }
        public int account(String action, String peer, String email, String token, String password) {
            calls.incrementAndGet(); this.action = action; this.email = email; this.token = token; this.password = password;
            if (unavailable) throw new StorageUnavailableException();
            return result;
        }
    }
}
