package auth

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
)

func accountPostgresConfig(t *testing.T) (Config, *pgx.Conn) {
	t.Helper()
	raw := os.Getenv("AUTH_ACCOUNT_TEST_DATABASE_URL")
	if raw == "" {
		t.Skip("AUTH_ACCOUNT_TEST_DATABASE_URL is not set")
	}
	safe, err := safeTestDatabaseURL(raw, os.Environ())
	if err != nil {
		t.Fatal(err)
	}
	conn, err := pgx.Connect(context.Background(), safe)
	if err != nil {
		t.Fatal("could not connect to account fixture")
	}
	t.Cleanup(func() { conn.Close(context.Background()) })
	var version int
	if err = conn.QueryRow(context.Background(), "SELECT version FROM feature_auth.schema_version").Scan(&version); err != nil || version != 2 {
		t.Fatal("account tests require schema2")
	}
	if _, err = conn.Exec(context.Background(), `DELETE FROM feature_auth.users WHERE id NOT IN ('demo-user','other-user');
        TRUNCATE feature_auth.sessions,feature_auth.login_attempts,feature_auth.account_tokens,
        feature_auth.account_attempts,feature_auth.account_mail_limits,feature_auth.mail_outbox`); err != nil {
		t.Fatal(err)
	}
	c := testConfig()
	c.Store = "postgres"
	c.DatabaseURL = safe
	c.AccountLifecycle = true
	return c, conn
}

func accountJSON(t *testing.T, value map[string]string) string {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

func TestPostgresAccountWorkflowAndSchemaSelection(t *testing.T) {
	c, conn := accountPostgresConfig(t)
	old := c
	old.AccountLifecycle = false
	if _, err := NewServer(old); err == nil {
		t.Fatal("v2 accepted schema2")
	}
	s := postgresTestServer(t, c)
	headers := map[string]string{"Origin": c.Origin, "Content-Type": "application/json"}
	email := "한@go.example.com"
	responseCode(t, request(s, "POST", "/auth/register", accountJSON(t, map[string]string{"email": email, "password": demoPassword}), nil, headers), 202, "")
	var enabled, admin bool
	var hash, token string
	if err := conn.QueryRow(context.Background(), "SELECT enabled,admin_enabled,password_hash FROM feature_auth.users WHERE email=$1", email).Scan(&enabled, &admin, &hash); err != nil || enabled || !admin {
		t.Fatal("pending account state invalid")
	}
	if match, err := verifyPHC(hash, demoPassword); err != nil || !match {
		t.Fatal("new account PHC invalid")
	}
	body := accountJSON(t, map[string]string{"email": email, "password": demoPassword})
	responseCode(t, request(s, "POST", "/auth/login", body, nil, headers), 401, "INVALID_CREDENTIALS")
	if err := conn.QueryRow(context.Background(), "SELECT token FROM feature_auth.mail_outbox WHERE recipient=$1", email).Scan(&token); err != nil || len(token) != 43 {
		t.Fatal("verification outbox missing")
	}
	verify := accountJSON(t, map[string]string{"token": token})
	responseCode(t, request(s, "POST", "/auth/email-verification/confirm", verify, nil, headers), 204, "")
	responseCode(t, request(s, "POST", "/auth/email-verification/confirm", verify, nil, headers), 400, "INVALID_TOKEN")
	first := request(s, "POST", "/auth/login", body, nil, headers)
	responseCode(t, first, 200, "")
	second := request(s, "POST", "/auth/login", body, nil, headers)
	responseCode(t, second, 200, "")
	responseCode(t, request(s, "POST", "/auth/password-reset/request", accountJSON(t, map[string]string{"email": email}), nil, headers), 202, "")
	if err := conn.QueryRow(context.Background(), "SELECT token FROM feature_auth.mail_outbox WHERE recipient=$1 AND kind='reset'", email).Scan(&token); err != nil {
		t.Fatal("reset outbox missing")
	}
	newPassword := "replacement-password-is-long"
	reset := accountJSON(t, map[string]string{"token": token, "password": newPassword})
	responseCode(t, request(s, "POST", "/auth/password-reset/confirm", reset, nil, headers), 204, "")
	for _, cookie := range first.Result().Cookies() {
		if cookie.Name == "fs_session" {
			responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 401, "UNAUTHENTICATED")
		}
	}
	for _, cookie := range second.Result().Cookies() {
		if cookie.Name == "fs_session" {
			responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 401, "UNAUTHENTICATED")
		}
	}
	responseCode(t, request(s, "POST", "/auth/login", body, nil, headers), 401, "INVALID_CREDENTIALS")
	responseCode(t, request(s, "POST", "/auth/login", accountJSON(t, map[string]string{"email": email, "password": newPassword}), nil, headers), 200, "")
}

func TestPostgresAccountSemanticErrorsCommitLimiter(t *testing.T) {
	c, _ := accountPostgresConfig(t)
	s := postgresTestServer(t, c)
	headers := map[string]string{"Origin": c.Origin, "Content-Type": "application/json"}
	for i := 0; i < 10; i++ {
		responseCode(t, request(s, "POST", "/auth/email-verification/confirm", `{"token":"`+strings.Repeat("A", 43)+`"}`, nil, headers), 400, "INVALID_TOKEN")
	}
	got := request(s, "POST", "/auth/email-verification/confirm", `{"token":"`+strings.Repeat("A", 43)+`"}`, nil, headers)
	responseCode(t, got, 429, "RATE_LIMITED")
	if got.Header().Get("Retry-After") == "" {
		t.Fatal("retry missing")
	}
}

func TestPostgresAccountExhaustedRateGateSkipsPasswordHash(t *testing.T) {
	c, conn := accountPostgresConfig(t)
	s := postgresTestServer(t, c)
	store := s.store.(*postgresStore)
	calls := 0
	store.passwordHash = func(string) (string, error) {
		calls++
		return "not-used-because-the-peer-is-limited", nil
	}
	for _, action := range []string{"register", "reset-confirm"} {
		if _, err := conn.Exec(context.Background(), "INSERT INTO feature_auth.account_attempts(peer,action,hits,expires_at) VALUES ('127.0.0.1',$1,10,clock_timestamp()+interval '60 seconds')", action); err != nil {
			t.Fatal(err)
		}
		err := store.Account(context.Background(), action, "127.0.0.1", "limited@example.com", strings.Repeat("A", 43), demoPassword)
		failure, ok := err.(*authFailure)
		if !ok || failure.Status != 429 {
			t.Fatal("exhausted account peer was not rate limited")
		}
		var hits int
		if err := conn.QueryRow(context.Background(), "SELECT hits FROM feature_auth.account_attempts WHERE action=$1", action).Scan(&hits); err != nil || hits != 10 {
			t.Fatal("exhausted account counter was incremented")
		}
	}
	if calls != 0 {
		t.Fatalf("rate-limited requests executed password hasher %d times", calls)
	}
}

func TestPostgresAccountCommitFailureNeverAcceptsOrPartiallyPersists(t *testing.T) {
	c, conn := accountPostgresConfig(t)
	s := postgresTestServer(t, c)
	if _, err := conn.Exec(context.Background(), `CREATE FUNCTION feature_auth.reject_go_account_commit()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'deferred test failure'; END $$;
        CREATE CONSTRAINT TRIGGER reject_go_account_commit AFTER INSERT ON feature_auth.mail_outbox
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION feature_auth.reject_go_account_commit()`); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, err := conn.Exec(context.Background(), `DROP TRIGGER reject_go_account_commit ON feature_auth.mail_outbox;
        DROP FUNCTION feature_auth.reject_go_account_commit()`)
		if err != nil {
			t.Error(err)
		}
	})
	got := request(s, "POST", "/auth/register", accountJSON(t, map[string]string{"email": "rollback@go.example.com", "password": demoPassword}), nil, map[string]string{"Origin": c.Origin, "Content-Type": "application/json"})
	responseCode(t, got, 503, "STORAGE_UNAVAILABLE")
	if got.Header().Get("Set-Cookie") != "" {
		t.Fatal("commit error issued cookie")
	}
	var count int
	if err := conn.QueryRow(context.Background(), "SELECT count(*) FROM feature_auth.users WHERE email='rollback@go.example.com'").Scan(&count); err != nil || count != 0 {
		t.Fatal("partial user persisted")
	}
	if err := conn.QueryRow(context.Background(), "SELECT count(*) FROM feature_auth.mail_outbox").Scan(&count); err != nil || count != 0 {
		t.Fatal("partial mail persisted")
	}
}
