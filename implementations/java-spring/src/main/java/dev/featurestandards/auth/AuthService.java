package dev.featurestandards.auth;

import java.time.Clock;
import java.time.Instant;

/** Reusable service: consumers can inject a storage implementation without using Servlet APIs. */
public final class AuthService {
    public record User(String id, String email) { }
    public record Session(String csrfToken, Instant expiresAt, User user) { }
    public record Login(Session session, String token, long retryAfter) { }
    private final AuthStore store;

    public AuthService(AuthStore store) { this.store = java.util.Objects.requireNonNull(store); }
    public AuthService(AuthConfig config, String password, Clock clock) {
        this(new MemoryAuthStore(config, password, clock));
    }
    public static AuthService create(AuthConfig config, String memoryPassword, Clock clock) {
        return new AuthService(config.store().equals("postgres") ? new PostgresAuthStore(config)
                : new MemoryAuthStore(config, memoryPassword, clock));
    }
    Login login(String peer, String previous, Credentials credentials) {
        return login(peer, previous, credentials.email(), credentials.password());
    }
    public Login login(String peer, String previous, String email, String password) {
        String normalized = Credentials.normalizeEmail(email);
        if (!Credentials.validEmail(normalized) || !Credentials.validPassword(password)) {
            throw new IllegalArgumentException("Invalid credentials format");
        }
        return store.login(peer, previous, normalized, password);
    }
    public Session session(String token) { return store.session(token); }
    public boolean logout(String token, String csrf) { return store.logout(token, csrf); }
    public void checkReady() { store.checkReady(); }
}
