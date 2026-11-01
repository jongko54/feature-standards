package main

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"testing"

	"github.com/jackc/pgx/v5"
)

func safeTestDatabaseURL(raw string, environ []string) (string, error) {
	fail := errors.New("PostgreSQL tests require a disposable loopback URL without routing overrides")
	for _, entry := range environ {
		name, value, _ := strings.Cut(entry, "=")
		if strings.HasPrefix(name, "PG") && value != "" {
			return "", fail
		}
	}
	parsed, err := url.Parse(raw)
	if err != nil {
		return "", fail
	}
	query, err := url.ParseQuery(parsed.RawQuery)
	if err != nil {
		return "", fail
	}
	if len(query) > 0 && (len(query) != 1 || len(query["sslmode"]) != 1 || query.Get("sslmode") != "disable") {
		return "", fail
	}
	port := parsed.Port()
	if port == "" {
		port = "5432"
	}
	portNumber, err := strconv.Atoi(port)
	if err != nil || portNumber < 1 || portNumber > 65535 {
		return "", fail
	}
	database := strings.TrimPrefix(parsed.Path, "/")
	if (parsed.Scheme != "postgresql" && parsed.Scheme != "postgres") || (parsed.Hostname() != "127.0.0.1" && parsed.Hostname() != "localhost" && parsed.Hostname() != "::1") || !regexp.MustCompile(`^feature_standards_test[A-Za-z0-9_]*$`).MatchString(database) || parsed.Fragment != "" {
		return "", fail
	}
	host := "127.0.0.1"
	if parsed.Hostname() == "::1" {
		host = "::1"
	}
	parsed.Host = net.JoinHostPort(host, port)
	parsed.Path = "/" + database
	parsed.RawPath = ""
	parsed.RawQuery = "sslmode=disable"
	return parsed.String(), nil
}

func TestTestDatabaseGuardRejectsQueryRoutingOverrides(t *testing.T) {
	for _, query := range []string{"host=production.example&dbname=production", "hostaddr=203.0.113.10", "dbname=production", "service=production", "%68ost=production.example", "sslmode=disable&host=production.example", "sslmode=disable&sslmode=prefer"} {
		if _, err := safeTestDatabaseURL("postgresql://127.0.0.1/feature_standards_test?"+query, nil); err == nil {
			t.Errorf("routing query accepted: %s", query)
		}
	}
}
func TestTestDatabaseGuardRejectsRoutingEnvironment(t *testing.T) {
	for _, name := range []string{"PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE"} {
		if _, err := safeTestDatabaseURL("postgresql://127.0.0.1/feature_standards_test", []string{name + "=production"}); err == nil {
			t.Errorf("routing environment accepted: %s", name)
		}
	}
}

func TestTestDatabaseGuardPinsDriverRouting(t *testing.T) {
	for _, test := range []struct {
		raw, host string
		port      uint16
		database  string
	}{
		{"postgresql://tester@localhost/feature_standards_test", "127.0.0.1", 5432, "feature_standards_test"},
		{"postgresql://tester@127.0.0.1:51105/feature_standards_test_pygo?sslmode=disable", "127.0.0.1", 51105, "feature_standards_test_pygo"},
		{"postgres://tester@[::1]:51105/feature_standards_test_ipv6", "::1", 51105, "feature_standards_test_ipv6"},
	} {
		safe, err := safeTestDatabaseURL(test.raw, nil)
		if err != nil {
			t.Fatal(err)
		}
		parsed, err := pgx.ParseConfig(safe)
		if err != nil {
			t.Fatal("driver rejected safe test URI")
		}
		if parsed.Host != test.host || parsed.Port != test.port || parsed.Database != test.database || len(parsed.Fallbacks) != 0 {
			t.Fatal("safe test URI changed driver routing")
		}
	}
}
func TestTestDatabaseGuardRejectsUnsafeSurface(t *testing.T) {
	for _, raw := range []string{
		"postgresql://production.example/feature_standards_test",
		"postgresql://127.0.0.1/production",
		"postgresql://127.0.0.1/feature_standards_test%2Fproduction",
		"postgresql://127.0.0.1:0/feature_standards_test",
		"postgresql://127.0.0.1/feature_standards_test#host=production.example",
	} {
		if _, err := safeTestDatabaseURL(raw, nil); err == nil {
			t.Error("unsafe test URL accepted")
		}
	}
}

func postgresTestConfig(t *testing.T) Config {
	t.Helper()
	raw := os.Getenv("AUTH_TEST_DATABASE_URL")
	if raw == "" {
		t.Skip("AUTH_TEST_DATABASE_URL is not set")
	}
	var err error
	raw, err = safeTestDatabaseURL(raw, os.Environ())
	if err != nil {
		t.Fatal(err)
	}
	config := testConfig()
	config.Store = "postgres"
	config.DatabaseURL = raw
	config.Email = ""
	config.Password = ""
	conn, err := pgx.Connect(context.Background(), raw)
	if err != nil {
		t.Fatal("test database connection failed")
	}
	defer conn.Close(context.Background())
	if _, err = conn.Exec(context.Background(), "TRUNCATE feature_auth.sessions,feature_auth.login_attempts"); err != nil {
		t.Fatal(err)
	}
	return config
}
func postgresTestServer(t *testing.T, config Config) *Server {
	t.Helper()
	s, err := NewServer(config)
	if err != nil {
		t.Fatal("could not initialize test database adapter")
	}
	t.Cleanup(s.Close)
	return s
}
func TestPHCValidation(t *testing.T) {
	dummy, err := newDummyPHC()
	if err != nil {
		t.Fatal(err)
	}
	if ok, err := verifyPHC(dummy, "not-the-random-password"); err != nil || ok {
		t.Fatal("valid PHC did not reject wrong password")
	}
	for _, encoded := range []string{"corrupt", strings.Replace(dummy, "m=65536", "m=8", 1), strings.Replace(dummy, "argon2id", "argon2i", 1), dummy + "="} {
		if _, err := verifyPHC(encoded, "password"); err == nil {
			t.Fatal("unsupported PHC accepted")
		}
	}
}
func TestPostgresConfigDoesNotNeedMemoryUser(t *testing.T) {
	t.Setenv("AUTH_STORE", "postgres")
	t.Setenv("AUTH_DATABASE_URL", "postgresql://127.0.0.1/feature_standards_test")
	t.Setenv("AUTH_DEMO", "false")
	t.Setenv("AUTH_ALLOWED_ORIGIN", "https://app.example.com")
	t.Setenv("AUTH_COOKIE_SECURE", "true")
	t.Setenv("AUTH_USER_EMAIL", "")
	t.Setenv("AUTH_USER_PASSWORD", "")
	config, err := LoadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if config.Email != "" || config.Password != "" {
		t.Fatal("postgres mode used memory credentials")
	}
}
func TestPostgresStartupFailureRedactsCredentials(t *testing.T) {
	config := testConfig()
	config.Store = "postgres"
	config.DatabaseURL = "postgresql://owner:never-print-this@127.0.0.1:1/feature_standards_test?sslmode=disable"
	_, err := NewServer(config)
	if err == nil || strings.Contains(err.Error(), "never-print-this") || strings.Contains(err.Error(), "postgresql://") {
		t.Fatal("startup must fail with a generic error")
	}
}
func TestPostgresSharedRotationAndUsers(t *testing.T) {
	config := postgresTestConfig(t)
	one := postgresTestServer(t, config)
	two := postgresTestServer(t, config)
	cookie, csrf := readLogin(t, loginRequest(one, nil))
	responseCode(t, request(two, "GET", "/auth/me", "", cookie, nil), 200, "")
	other := request(two, "POST", "/auth/login", `{"email":"other@example.com","password":"other-correct-horse-password"}`, nil, map[string]string{"Origin": config.Origin, "Content-Type": "application/json"})
	responseCode(t, other, 200, "")
	var body struct {
		User map[string]string `json:"user"`
	}
	if err := json.Unmarshal(other.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.User["id"] != "other-user" {
		t.Fatal("other session does not identify other user")
	}
	otherCookie := other.Result().Cookies()[0]
	rotated, _ := readLogin(t, loginRequest(two, cookie))
	responseCode(t, request(one, "GET", "/auth/me", "", cookie, nil), 401, "UNAUTHENTICATED")
	responseCode(t, request(one, "GET", "/auth/me", "", otherCookie, nil), 200, "")
	responseCode(t, request(one, "POST", "/auth/logout", "", rotated, map[string]string{"Origin": config.Origin, "X-CSRF-Token": csrf}), 403, "CSRF_INVALID")
	value := request(one, "GET", "/auth/me", "", rotated, nil)
	var sessionBody struct {
		CSRF string `json:"csrfToken"`
	}
	if err := json.Unmarshal(value.Body.Bytes(), &sessionBody); err != nil {
		t.Fatal(err)
	}
	responseCode(t, request(two, "POST", "/auth/logout", "", rotated, map[string]string{"Origin": config.Origin, "X-CSRF-Token": sessionBody.CSRF}), 204, "")
	responseCode(t, request(one, "GET", "/auth/me", "", rotated, nil), 401, "UNAUTHENTICATED")
	responseCode(t, request(one, "GET", "/auth/me", "", otherCookie, nil), 200, "")
}
func TestPostgresAtomicFailuresCanonicalPeer(t *testing.T) {
	config := postgresTestConfig(t)
	config.RateLimit = 2
	stores := []*Server{postgresTestServer(t, config), postgresTestServer(t, config)}
	statuses := make(chan int, 8)
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(index int) {
			defer wg.Done()
			peer := "::1"
			if index%2 == 0 {
				peer = "0:0:0:0:0:0:0:1"
			}
			_, _, err := stores[index%2].store.Login(context.Background(), peer, "demo@example.com", "wrong", "")
			failure, ok := err.(*authFailure)
			if !ok {
				statuses <- 500
				return
			}
			statuses <- failure.Status
		}(i)
	}
	wg.Wait()
	close(statuses)
	counts := map[int]int{}
	for status := range statuses {
		counts[status]++
	}
	if counts[401] != 2 || counts[429] != 6 {
		t.Fatalf("atomic failure statuses=%v", counts)
	}
}
func TestPostgresRuntimeFailureDoesNotIssueCookie(t *testing.T) {
	config := postgresTestConfig(t)
	s := postgresTestServer(t, config)
	cookie, _ := readLogin(t, loginRequest(s, nil))
	s.store.Close()
	for _, test := range []struct{ method, path string }{{"GET", "/auth/me"}, {"GET", "/healthz"}, {"POST", "/auth/login"}, {"POST", "/auth/logout"}} {
		body := ""
		headers := map[string]string{"Origin": config.Origin}
		if test.path == "/auth/login" {
			body = `{"email":"demo@example.com","password":"` + demoPassword + `"}`
			headers["Content-Type"] = "application/json"
		}
		w := request(s, test.method, test.path, body, cookie, headers)
		responseCode(t, w, 503, "STORAGE_UNAVAILABLE")
		if w.Header().Get("Set-Cookie") != "" || w.Header().Get("Cache-Control") != "no-store" || w.Header().Get("X-Content-Type-Options") != "nosniff" {
			t.Fatal("failure response issued cookie or omitted error headers")
		}
	}
}
func TestDuplicateCSRFHeaderIsRejected(t *testing.T) {
	s := testServer(t)
	cookie, csrf := readLogin(t, loginRequest(s, nil))
	r := httptest.NewRequest(http.MethodPost, "/auth/logout", nil)
	r.AddCookie(cookie)
	r.Header.Set("Origin", s.config.Origin)
	r.Header.Add("X-CSRF-Token", csrf)
	r.Header.Add("X-CSRF-Token", csrf)
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	responseCode(t, w, 403, "CSRF_INVALID")
	responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 200, "")
}

func TestPostgresSchemaMismatchRejected(t *testing.T) {
	config := postgresTestConfig(t)
	conn, err := pgx.Connect(context.Background(), config.DatabaseURL)
	if err != nil {
		t.Fatal("test connection failed")
	}
	defer conn.Close(context.Background())
	if _, err = conn.Exec(context.Background(), "DELETE FROM feature_auth.schema_version"); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := conn.Exec(context.Background(), "INSERT INTO feature_auth.schema_version(version) VALUES(1)"); err != nil {
			t.Error(err)
		}
	}()
	if server, err := NewServer(config); err == nil {
		server.Close()
		t.Fatal("app started without schema version 1")
	}
}

func TestPostgresCommitFailurePreservesOldSession(t *testing.T) {
	config := postgresTestConfig(t)
	s := postgresTestServer(t, config)
	cookie, csrf := readLogin(t, loginRequest(s, nil))
	conn, err := pgx.Connect(context.Background(), config.DatabaseURL)
	if err != nil {
		t.Fatal("test connection failed")
	}
	defer conn.Close(context.Background())
	if _, err = conn.Exec(context.Background(), `CREATE FUNCTION feature_auth.reject_go_test_commit()
    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test deferred failure'; END $$`); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := conn.Exec(context.Background(), "DROP FUNCTION feature_auth.reject_go_test_commit() CASCADE"); err != nil {
			t.Error(err)
		}
	}()
	if _, err = conn.Exec(context.Background(), `CREATE CONSTRAINT TRIGGER reject_go_test_commit
    AFTER INSERT OR DELETE ON feature_auth.sessions DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION feature_auth.reject_go_test_commit()`); err != nil {
		t.Fatal(err)
	}
	for _, w := range []*httptest.ResponseRecorder{
		loginRequest(s, cookie),
		request(s, "POST", "/auth/logout", "", cookie, map[string]string{"Origin": config.Origin, "X-CSRF-Token": csrf}),
	} {
		responseCode(t, w, 503, "STORAGE_UNAVAILABLE")
		if w.Header().Get("Set-Cookie") != "" {
			t.Fatal("failed commit changed cookie")
		}
		responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 200, "")
	}
}

func TestPostgresCorruptPHCFailsClosed(t *testing.T) {
	config := postgresTestConfig(t)
	s := postgresTestServer(t, config)
	cookie, _ := readLogin(t, loginRequest(s, nil))
	conn, err := pgx.Connect(context.Background(), config.DatabaseURL)
	if err != nil {
		t.Fatal("test connection failed")
	}
	defer conn.Close(context.Background())
	var encoded string
	if err = conn.QueryRow(context.Background(), "SELECT password_hash FROM feature_auth.users WHERE id='demo-user'").Scan(&encoded); err != nil {
		t.Fatal(err)
	}
	if _, err = conn.Exec(context.Background(), "UPDATE feature_auth.users SET password_hash='corrupt' WHERE id='demo-user'"); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := conn.Exec(context.Background(), "UPDATE feature_auth.users SET password_hash=$1 WHERE id='demo-user'", encoded); err != nil {
			t.Error(err)
		}
	}()
	w := loginRequest(s, cookie)
	responseCode(t, w, 503, "STORAGE_UNAVAILABLE")
	if w.Header().Get("Set-Cookie") != "" {
		t.Fatal("invalid hash changed cookie")
	}
	responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 200, "")
}
