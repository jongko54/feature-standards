package dev.featurestandards.auth;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.net.URI;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import static org.assertj.core.api.Assertions.*;

/** Only the explicitly selected schema-2 disposable database is modified. */
@EnabledIfEnvironmentVariable(named = "AUTH_ACCOUNT_TEST_DATABASE_URL", matches = ".+")
class PostgresAccountStoreTest {
    static final String EMAIL = "java-new@example.com";
    static final String OLD = "first-correct-password";
    static final String NEW = "second-correct-password";
    static AuthConfig config;
    static PostgresConnectionFactory connections;
    PostgresAuthStore store;
    AuthService service;

    @BeforeAll static void prepare() {
        String url = System.getenv("AUTH_ACCOUNT_TEST_DATABASE_URL");
        URI uri = URI.create(url);
        if (!("127.0.0.1".equals(uri.getHost()) || "localhost".equals(uri.getHost()) || "[::1]".equals(uri.getHost()))
                || uri.getPort() < 1 || uri.getPort() > 65535 || uri.getFragment() != null
                || uri.getPath() == null || !uri.getPath().matches("/feature_standards_test[A-Za-z0-9_]*")
                || !Objects.equals(uri.getRawPath(), uri.getPath())
                || uri.getRawQuery() != null && !uri.getRawQuery().equals("sslmode=disable")) {
            throw new IllegalArgumentException("An explicit disposable loopback account DB is required");
        }
        config = config(url, true);
        connections = new PostgresConnectionFactory(url);
        new PostgresAuthStore(config); // Migration is explicit and is never run by the application/test.
    }
    static AuthConfig config(String url, boolean enabled) {
        return AuthConfig.load(Map.of("AUTH_DEMO", "true", "AUTH_STORE", "postgres", "AUTH_DATABASE_URL", url,
                "AUTH_ACCOUNT_LIFECYCLE", Boolean.toString(enabled))::get);
    }
    @BeforeEach void clearDedicatedFixtures() throws Exception {
        execute("TRUNCATE feature_auth.users CASCADE; TRUNCATE feature_auth.account_attempts,feature_auth.login_attempts");
        store = new PostgresAuthStore(config);
        service = new AuthService(store);
    }
    int account(String action, String token, String password) {
        return service.account(action, "127.0.0.1", EMAIL, token, password);
    }
    String scalar(String query) throws Exception {
        try (var conn = connections.open(); var statement = conn.createStatement(); var result = statement.executeQuery(query)) {
            assertThat(result.next()).isTrue(); return result.getString(1);
        }
    }
    void execute(String query) throws Exception {
        try (var conn = connections.open(); var statement = conn.createStatement()) { statement.execute(query); }
    }
    String register() throws Exception {
        assertThat(account("register", "", OLD)).isZero();
        return scalar("SELECT token FROM feature_auth.mail_outbox WHERE kind='verify'");
    }
    void verified() throws Exception {
        assertThat(account("verify-confirm", register(), "")).isZero();
    }
    @Test void pendingUserCannotLoginAndVerificationCommitsAcrossStores() throws Exception {
        String token = register();
        assertThat(service.login("127.0.0.1", null, EMAIL, OLD).session()).isNull();
        assertThat(scalar("SELECT enabled FROM feature_auth.users")).isEqualTo("f");
        assertThat(account("verify-confirm", token, "")).isZero();
        var other = new AuthService(new PostgresAuthStore(config));
        var login = other.login("127.0.0.1", null, EMAIL, OLD);
        assertThat(login.session().user().email()).isEqualTo(EMAIL);
        assertThat(store.session(login.token())).isNotNull();
        assertThat(account("verify-confirm", token, "")).isEqualTo(-1);
        assertThat(scalar("SELECT count(*) FROM feature_auth.account_tokens")).isEqualTo("0");
    }
    @Test void duplicateRegistrationPreservesPasswordAndOriginalCapability() throws Exception {
        String token = register();
        String hash = scalar("SELECT password_hash FROM feature_auth.users");
        assertThat(account("register", "", NEW)).isZero();
        assertThat(Objects.equals(hash, scalar("SELECT password_hash FROM feature_auth.users"))).isTrue();
        assertThat(Objects.equals(token, scalar("SELECT token FROM feature_auth.mail_outbox"))).isTrue();
        assertThat(scalar("SELECT count(*) FROM feature_auth.users")).isEqualTo("1");
    }
    @Test void resetReplacesPasswordRevokesEverySessionAndRejectsReuse() throws Exception {
        verified();
        var first = service.login("127.0.0.1", null, EMAIL, OLD);
        var second = service.login("127.0.0.1", null, EMAIL, OLD);
        assertThat(account("reset-request", "", "")).isZero();
        String token = scalar("SELECT token FROM feature_auth.mail_outbox WHERE kind='reset'");
        assertThat(account("reset-confirm", token, NEW)).isZero();
        assertThat(store.session(first.token())).isNull();
        assertThat(store.session(second.token())).isNull();
        assertThat(service.login("127.0.0.1", null, EMAIL, OLD).session()).isNull();
        assertThat(service.login("127.0.0.1", null, EMAIL, NEW).session()).isNotNull();
        assertThat(account("reset-confirm", token, OLD)).isEqualTo(-1);
    }
    @Test void policyAndDisabledStateDoNotConsumeCapabilityOrEnableAdministratorDisabledUser() throws Exception {
        String token = register();
        execute("UPDATE feature_auth.users SET admin_enabled=false");
        assertThat(account("verify-confirm", token, "")).isEqualTo(-1);
        assertThat(scalar("SELECT admin_enabled FROM feature_auth.users")).isEqualTo("f");
        assertThat(scalar("SELECT count(*) FROM feature_auth.account_tokens")).isEqualTo("1");
        execute("UPDATE feature_auth.users SET admin_enabled=true");
        assertThat(account("verify-confirm", token, "")).isZero();
        var original = service.login("127.0.0.1", null, EMAIL, OLD);
        account("reset-request", "", "");
        String reset = scalar("SELECT token FROM feature_auth.mail_outbox WHERE kind='reset'");
        assertThatThrownBy(() -> account("reset-confirm", reset, "too-short")).isInstanceOf(IllegalArgumentException.class);
        assertThat(store.session(original.token())).isNotNull();
        assertThat(scalar("SELECT count(*) FROM feature_auth.account_tokens WHERE kind='reset'")).isEqualTo("1");
    }
    @Test void databaseResultRateLimitIsCommittedAndSharedBetweenInstances() throws Exception {
        var other = new AuthService(new PostgresAuthStore(config));
        for (int i = 0; i < 10; i++) {
            assertThat((i % 2 == 0 ? service : other).account("reset-request", "127.0.0.1", "missing@example.com", "", "")).isZero();
        }
        assertThat(account("reset-request", "", "")).isPositive();
        assertThat(scalar("SELECT hits FROM feature_auth.account_attempts WHERE action='reset-request'")).isEqualTo("10");
    }
    @Test void exhaustedPeerIsRejectedBeforePasswordHashingAndOnlyOneReservationIsCounted() throws Exception {
        AtomicInteger hashes = new AtomicInteger();
        var measured = new AuthService(new PostgresAuthStore(config, connections, password -> {
            hashes.incrementAndGet(); return PasswordHashes.encode(password);
        }));
        assertThat(measured.account("register", "127.0.0.1", EMAIL, "", OLD)).isZero();
        assertThat(hashes.get()).isEqualTo(1);
        assertThat(scalar("SELECT hits FROM feature_auth.account_attempts WHERE action='register'")).isEqualTo("1");
        execute("UPDATE feature_auth.account_attempts SET hits=10 WHERE action='register'");
        assertThat(measured.account("register", "127.0.0.1", EMAIL, "", NEW)).isPositive();
        assertThat(hashes.get()).isEqualTo(1);
        assertThat(scalar("SELECT hits FROM feature_auth.account_attempts WHERE action='register'")).isEqualTo("10");
    }
    @Test void commitFailureRollsBackUserOutboxPasswordTokensAndSessionDeletion() throws Exception {
        AtomicBoolean failCommit = new AtomicBoolean();
        var failing = new AuthService(new PostgresAuthStore(config, () -> {
            Connection connection = connections.open();
            return (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(), new Class<?>[]{Connection.class},
                    (proxy, method, args) -> {
                        if (method.getName().equals("commit") && failCommit.get()) throw new SQLException("secret database URL");
                        try { return method.invoke(connection, args); }
                        catch (InvocationTargetException ex) { throw ex.getCause(); }
                    });
        }));
        failCommit.set(true);
        assertThatThrownBy(() -> failing.account("register", "127.0.0.1", EMAIL, "", OLD))
                .isInstanceOf(StorageUnavailableException.class).hasNoCause().hasMessageNotContaining("secret");
        assertThat(scalar("SELECT count(*) FROM feature_auth.users")).isEqualTo("0");
        assertThat(scalar("SELECT count(*) FROM feature_auth.mail_outbox")).isEqualTo("0");
        verified();
        var original = service.login("127.0.0.1", null, EMAIL, OLD);
        account("reset-request", "", "");
        String token = scalar("SELECT token FROM feature_auth.mail_outbox WHERE kind='reset'");
        assertThatThrownBy(() -> failing.account("reset-confirm", "127.0.0.1", "", token, NEW)).isInstanceOf(StorageUnavailableException.class);
        assertThat(store.session(original.token())).isNotNull();
        assertThat(scalar("SELECT count(*) FROM feature_auth.account_tokens WHERE kind='reset'")).isEqualTo("1");
        assertThat(service.login("127.0.0.1", null, EMAIL, OLD).session()).isNotNull();
    }
    @Test void oldProfileCannotStartOnUpgradedSchema() {
        assertThatThrownBy(() -> new PostgresAuthStore(config(System.getenv("AUTH_ACCOUNT_TEST_DATABASE_URL"), false)))
                .isInstanceOf(StorageUnavailableException.class);
        String legacy = System.getenv("AUTH_TEST_DATABASE_URL");
        if (legacy != null) assertThatThrownBy(() -> new PostgresAuthStore(config(legacy, true)))
                .isInstanceOf(StorageUnavailableException.class);
    }
}
