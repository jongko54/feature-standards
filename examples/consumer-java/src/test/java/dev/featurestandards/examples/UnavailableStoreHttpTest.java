package dev.featurestandards.examples;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.featurestandards.auth.AuthService;
import dev.featurestandards.auth.AuthStore;
import dev.featurestandards.auth.StorageUnavailableException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import static org.assertj.core.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        classes = {ConsumerApplication.class, UnavailableStoreHttpTest.BrokenStore.class}, properties = {
    "AUTH_DEMO=true", "AUTH_STORE=memory", "AUTH_ACCOUNT_LIFECYCLE=false", "AUTH_COOKIE_SECURE=false"
})
class UnavailableStoreHttpTest {
    @LocalServerPort int port;

    @Test void protectedProfileFailsClosedOnStorageFailure() throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/profile"))
                .header("Cookie", "fs_session=opaque-test-token").GET().build();
        var response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(503);
        assertThat(new ObjectMapper().readTree(response.body()).path("error").path("code").asText())
                .isEqualTo("STORAGE_UNAVAILABLE");
        assertThat(response.headers().firstValue("Set-Cookie")).isEmpty();
        assertThat(response.headers().firstValue("Cache-Control")).contains("no-store");
    }

    @TestConfiguration static class BrokenStore {
        @Bean @Primary AuthService unavailableAuthService() {
            return new AuthService(new AuthStore() {
                public AuthService.Login login(String peer, String previous, String email, String password) {
                    throw new StorageUnavailableException();
                }
                public AuthService.Session session(String token) { throw new StorageUnavailableException(); }
                public boolean logout(String token, String csrf) { throw new StorageUnavailableException(); }
            });
        }
    }
}
