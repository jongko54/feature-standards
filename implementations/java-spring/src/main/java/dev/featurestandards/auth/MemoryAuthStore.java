package dev.featurestandards.auth;

import java.time.Clock;
import java.time.Instant;
import java.util.HashMap;
import java.util.Map;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;

/** v1 process-local, single-user state. Hash verification remains serialized. */
public final class MemoryAuthStore implements AuthStore {
    private record Failure(int count, Instant expiresAt) { }
    private final AuthConfig config;
    private final Clock clock;
    private final Argon2PasswordEncoder encoder = new Argon2PasswordEncoder(16, 32, 4, 65536, 3);
    private final String passwordHash;
    private final Map<String, AuthService.Session> sessions = new HashMap<>();
    private final Map<String, Failure> failures = new HashMap<>();

    public MemoryAuthStore(AuthConfig config, String password, Clock clock) {
        this.config = config;
        this.clock = clock;
        this.passwordHash = encoder.encode(password);
    }
    @Override public synchronized AuthService.Login login(String peer, String previous, String email, String password) {
        Instant now = clock.instant();
        clean(now);
        Failure failure = failures.get(peer);
        if (failure != null && failure.count >= config.rateLimit()) {
            long remainingMillis = java.time.Duration.between(now, failure.expiresAt).toMillis();
            return new AuthService.Login(null, null, Math.max(1, (remainingMillis + 999) / 1000));
        }
        boolean passwordMatches = encoder.matches(password, passwordHash);
        if (!passwordMatches || !email.equals(config.email())) {
            failures.put(peer, failure == null ? new Failure(1, now.plusSeconds(config.rateWindow()))
                    : new Failure(failure.count + 1, failure.expiresAt));
            return new AuthService.Login(null, null, 0);
        }
        failures.remove(peer);
        if (previous != null) sessions.remove(previous);
        String token = Tokens.random();
        var session = new AuthService.Session(Tokens.random(), clock.instant().plusSeconds(config.sessionTtl()),
                new AuthService.User("demo-user", config.email()));
        sessions.put(token, session);
        return new AuthService.Login(session, token, 0);
    }
    @Override public synchronized AuthService.Session session(String token) {
        clean(clock.instant());
        return token == null ? null : sessions.get(token);
    }
    @Override public synchronized boolean logout(String token, String csrf) {
        var session = session(token);
        if (session == null) return true;
        if (!Tokens.equal(session.csrfToken(), csrf)) return false;
        sessions.remove(token);
        return true;
    }
    private void clean(Instant now) {
        sessions.values().removeIf(session -> !session.expiresAt().isAfter(now));
        failures.values().removeIf(failure -> !failure.expiresAt.isAfter(now));
    }
}
