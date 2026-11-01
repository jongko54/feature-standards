package dev.featurestandards.auth;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.net.URI;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;
import static org.assertj.core.api.Assertions.*;

/** Explicitly opted-in destructive tests; only their isolated loopback test database is allowed. */
@EnabledIfEnvironmentVariable(named = "AUTH_TEST_DATABASE_URL", matches = ".+")
class PostgresAuthStoreTest {
    static PostgresConnectionFactory connections;
    static AuthConfig config;
    static String passwordHash;
    PostgresAuthStore first;
    PostgresAuthStore second;
    @BeforeAll static void setup() throws Exception {
        String url = System.getenv("AUTH_TEST_DATABASE_URL");
        URI uri = URI.create(url);
        if (!("127.0.0.1".equals(uri.getHost()) || "localhost".equals(uri.getHost()) || "[::1]".equals(uri.getHost()))
                || uri.getPath() == null || !uri.getPath().startsWith("/feature_standards_test")) {
            throw new IllegalArgumentException("Only an isolated loopback feature_standards_test database is allowed");
        }
        config = AuthConfig.load(Map.of("AUTH_STORE", "postgres", "AUTH_DATABASE_URL", url, "AUTH_DEMO", "true",
                "AUTH_RATE_LIMIT_MAX", "3", "AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")::get);
        connections = new PostgresConnectionFactory(url);
        passwordHash = new Argon2PasswordEncoder(16, 32, 4, 65536, 3).encode("한글😀 ");
        new PostgresAuthStore(config); // Schema must have been explicitly migrated before this suite.
    }
    @BeforeEach void cleanAndSeedExplicitFixtures() throws Exception {
        try (var connection = connections.open(); var statement = connection.createStatement()) {
            statement.execute("TRUNCATE feature_auth.sessions, feature_auth.login_attempts, feature_auth.users CASCADE");
        }
        try (var connection = connections.open(); var statement = connection.prepareStatement(
                "INSERT INTO feature_auth.users(id, email, password_hash) VALUES (?, ?, ?), (?, ?, ?)")) {
            statement.setString(1, "원본-id😀"); statement.setString(2, "demo@example.com"); statement.setString(3, passwordHash);
            statement.setString(4, "other-user"); statement.setString(5, "other@example.com"); statement.setString(6, passwordHash);
            statement.executeUpdate();
        }
        first = new PostgresAuthStore(config);
        second = new PostgresAuthStore(config);
    }
    AuthService.Login login(PostgresAuthStore store, String peer, String previous, String email, String password) {
        return new AuthService(store).login(peer, previous, email, password);
    }
    AuthService.Login correct(PostgresAuthStore store, String peer, String previous) {
        return login(store, peer, previous, "  DEMO@EXAMPLE.COM ", "한글😀 ");
    }
    long scalar(String sql) throws Exception {
        try (var connection = connections.open(); var statement = connection.createStatement(); var result = statement.executeQuery(sql)) {
            result.next(); return result.getLong(1);
        }
    }
    void execute(String sql) throws Exception {
        try (var connection = connections.open(); var statement = connection.createStatement()) { statement.execute(sql); }
    }
    @Test void persistsRealUserAndHashedTokenAcrossInstancesAndRestartWithoutDemoOverwrite() throws Exception {
        var login = correct(first, "127.0.0.1", null);
        assertThat(login.session().user().id()).isEqualTo("원본-id😀");
        assertThat(second.session(login.token())).isEqualTo(login.session());
        assertThat(new PostgresAuthStore(config).session(login.token())).isEqualTo(login.session());
        assertThat(login.token()).hasSize(43).isNotEqualTo(login.session().csrfToken());
        try (var connection = connections.open(); var query = connection.prepareStatement(
                "SELECT token_hash, csrf_token FROM feature_auth.sessions WHERE user_id = ?")) {
            query.setString(1, "원본-id😀");
            try (var result = query.executeQuery()) {
                assertThat(result.next()).isTrue();
                assertThat(result.getBytes(1)).isEqualTo(Tokens.hash(login.token())).hasSize(32);
                assertThat(result.getString(2)).isEqualTo(login.session().csrfToken());
            }
        }
        assertThat(scalar("SELECT count(*) FROM feature_auth.users")).isEqualTo(2);
        assertThat(login(first, "127.0.0.2", null, "demo@example.com", "correct-horse-battery-staple").session()).isNull();
    }
    @Test void rotatesOnlyPassedSessionAndMaintainsOtherUsersAndCsrfUntilCommittedLogout() {
        var old = correct(first, "127.0.0.1", null);
        var browser = correct(first, "127.0.0.1", null);
        var other = login(second, "127.0.0.2", null, "other@example.com", "한글😀 ");
        var rotated = correct(second, "127.0.0.1", old.token());
        assertThat(first.session(old.token())).isNull();
        assertThat(first.session(browser.token())).isNotNull();
        assertThat(first.session(other.token()).user().id()).isEqualTo("other-user");
        assertThat(first.logout(rotated.token(), other.session().csrfToken())).isFalse();
        assertThat(first.session(rotated.token())).isNotNull();
        assertThat(second.logout(rotated.token(), rotated.session().csrfToken())).isTrue();
        assertThat(first.session(rotated.token())).isNull();
        assertThat(second.logout(rotated.token(), null)).isTrue();
    }
    @Test void normalizesInetPeersAndSerializesConcurrentFailuresAcrossInstances() throws Exception {
        var start = new CountDownLatch(1);
        try (var pool = Executors.newFixedThreadPool(8)) {
            var tasks = new ArrayList<java.util.concurrent.Future<AuthService.Login>>();
            for (int i = 0; i < 8; i++) {
                final int index = i;
                tasks.add(pool.submit(() -> {
                    start.await();
                    return login(index % 2 == 0 ? first : second,
                            index % 2 == 0 ? "::1" : "0:0:0:0:0:0:0:1/64", null, "missing@example.com", "wrong");
                }));
            }
            start.countDown();
            int failures = 0, limited = 0;
            for (var task : tasks) {
                var result = task.get(20, TimeUnit.SECONDS);
                if (result.retryAfter() > 0) limited++; else failures++;
                assertThat(result.session()).isNull();
            }
            assertThat(failures).isEqualTo(3);
            assertThat(limited).isEqualTo(5);
        }
        assertThat(scalar("SELECT count(*) FROM feature_auth.login_attempts")).isEqualTo(1);
        assertThat(scalar("SELECT failures FROM feature_auth.login_attempts")).isEqualTo(3);
    }
    @Test void successClearsSharedFailuresAndDatabaseClockControlsExpiryWithoutExtendingTtl() throws Exception {
        login(first, "127.0.0.1", null, "demo@example.com", "wrong");
        var session = correct(second, "127.0.0.1", null);
        assertThat(scalar("SELECT count(*) FROM feature_auth.login_attempts")).isZero();
        var originalExpiry = first.session(session.token()).expiresAt();
        assertThat(second.session(session.token()).expiresAt()).isEqualTo(originalExpiry);
        execute("UPDATE feature_auth.sessions SET created_at = clock_timestamp() - interval '2 hours', expires_at = clock_timestamp() - interval '1 hour'");
        assertThat(first.session(session.token())).isNull();
        assertThat(first.logout(session.token(), null)).isTrue();
    }
    @Test void readsFreshClockAfterWaitingForPeerLock() throws Exception {
        execute("INSERT INTO feature_auth.login_attempts VALUES ('127.0.0.1', 3, clock_timestamp() + interval '350 milliseconds')");
        try (var connection = connections.open(); var statement = connection.createStatement();
             var executor = Executors.newSingleThreadExecutor()) {
            connection.setAutoCommit(false);
            statement.execute("SELECT pg_advisory_xact_lock(20261102, hashtext(host('127.0.0.1'::inet)))");
            var started = new CountDownLatch(1);
            var future = executor.submit(() -> {
                started.countDown(); return correct(first, "127.0.0.1", null);
            });
            assertThat(started.await(5, TimeUnit.SECONDS)).isTrue();
            // The failure record has expired by the time the advisory lock is released.
            statement.execute("SELECT pg_sleep(0.5)");
            connection.commit();
            assertThat(future.get(10, TimeUnit.SECONDS).session()).isNotNull();
        }
    }
    @Test void disabledUsersAreDeniedAndMalformedPhcRollsBackAttemptAndRotation() throws Exception {
        var current = correct(first, "127.0.0.1", null);
        execute("UPDATE feature_auth.users SET enabled = false WHERE email = 'demo@example.com'");
        assertThat(second.session(current.token())).isNull();
        assertThat(correct(first, "127.0.0.2", null).session()).isNull();
        execute("UPDATE feature_auth.users SET enabled = true, password_hash = 'unsupported' WHERE email = 'demo@example.com'");
        assertThatThrownBy(() -> correct(first, "127.0.0.3", current.token())).isInstanceOf(StorageUnavailableException.class).hasNoCause();
        assertThat(scalar("SELECT count(*) FROM feature_auth.login_attempts WHERE peer = '127.0.0.3'")).isZero();
        assertThat(first.session(current.token())).isNotNull();
    }
    @Test void disabledUsersStillRequireCsrfForTheirUnexpiredStoredSessions() throws Exception {
        var current = correct(first, "127.0.0.1", null);
        execute("UPDATE feature_auth.users SET enabled = false WHERE email = 'demo@example.com'");
        assertThat(second.session(current.token())).isNull();
        assertThat(first.logout(current.token(), null)).isFalse();
        assertThat(scalar("SELECT count(*) FROM feature_auth.sessions")).isEqualTo(1);
        assertThat(second.logout(current.token(), "wrong")).isFalse();
        assertThat(scalar("SELECT count(*) FROM feature_auth.sessions")).isEqualTo(1);
        assertThat(second.logout(current.token(), current.session().csrfToken())).isTrue();
        assertThat(scalar("SELECT count(*) FROM feature_auth.sessions")).isZero();
    }
    @Test void commitFailureRollsBackSuccessfulRotationFailureRecordingAndLogout() throws Exception {
        var original = correct(first, "127.0.0.1", null);
        AtomicBoolean failCommit = new AtomicBoolean();
        var failing = new PostgresAuthStore(config, () -> {
            Connection connection = connections.open();
            return (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(), new Class<?>[]{Connection.class},
                    (proxy, method, args) -> {
                        if (method.getName().equals("commit") && failCommit.get()) throw new SQLException("secret database URL");
                        try { return method.invoke(connection, args); }
                        catch (InvocationTargetException ex) { throw ex.getCause(); }
                    });
        });
        failCommit.set(true);
        assertThatThrownBy(() -> correct(failing, "127.0.0.1", original.token()))
                .isInstanceOf(StorageUnavailableException.class).hasNoCause().hasMessageNotContaining("secret");
        assertThat(scalar("SELECT count(*) FROM feature_auth.sessions")).isEqualTo(1);
        assertThat(first.session(original.token())).isNotNull();
        assertThatThrownBy(() -> login(failing, "127.0.0.2", null, "missing@example.com", "wrong"))
                .isInstanceOf(StorageUnavailableException.class);
        assertThat(scalar("SELECT count(*) FROM feature_auth.login_attempts")).isZero();
        assertThatThrownBy(() -> failing.logout(original.token(), original.session().csrfToken()))
                .isInstanceOf(StorageUnavailableException.class);
        assertThat(first.session(original.token())).isNotNull();
    }
    @Test void startupRejectsSchemaMismatchAndReadinessObservesRuntimeConnectionFailure() throws Exception {
        execute("DELETE FROM feature_auth.schema_version");
        try {
            assertThatThrownBy(() -> new PostgresAuthStore(config)).isInstanceOf(StorageUnavailableException.class);
            assertThatThrownBy(first::checkReady).isInstanceOf(StorageUnavailableException.class);
        } finally { execute("INSERT INTO feature_auth.schema_version VALUES (1)"); }
        AtomicBoolean unavailable = new AtomicBoolean();
        var store = new PostgresAuthStore(config, () -> {
            if (unavailable.get()) throw new SQLException("secret postgres URL");
            return connections.open();
        });
        unavailable.set(true);
        assertThatThrownBy(store::checkReady).isInstanceOf(StorageUnavailableException.class).hasNoCause().hasMessageNotContaining("secret");
        assertThatThrownBy(() -> store.session(null)).isInstanceOf(StorageUnavailableException.class);
        assertThatThrownBy(() -> store.logout(null, null)).isInstanceOf(StorageUnavailableException.class);
        assertThatThrownBy(() -> correct(store, "127.0.0.1", null)).isInstanceOf(StorageUnavailableException.class);
    }
}
