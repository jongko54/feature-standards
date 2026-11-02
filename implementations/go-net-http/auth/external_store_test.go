package auth_test

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jongko54/feature-standards/implementations/go-net-http/auth"
)

type externalStore struct{ err error }

func (s externalStore) Login(context.Context, string, string, string, string) (string, auth.Session, error) {
	return "", auth.Session{}, s.err
}
func (s externalStore) Current(context.Context, string) (auth.Session, error) {
	return auth.Session{User: map[string]string{"id": "must-not-escape"}}, s.err
}
func (s externalStore) Logout(context.Context, string, string) error { return s.err }
func (s externalStore) Account(context.Context, string, string, string, string, string) error {
	return s.err
}
func (s externalStore) Ready(context.Context) error { return s.err }
func (s externalStore) Close()                      {}

func TestExternalStoreCurrentUserErrorsFailClosed(t *testing.T) {
	for _, tc := range []struct {
		name   string
		err    error
		status int
		code   string
	}{
		{"unauthenticated", auth.UnauthenticatedError(), 401, "UNAUTHENTICATED"},
		{"unavailable", auth.StorageUnavailableError(), 503, "STORAGE_UNAVAILABLE"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server := auth.NewServerWithStore(auth.Config{}, externalStore{fmt.Errorf("private storage context: %w", tc.err)})
			defer server.Close()
			w := httptest.NewRecorder()
			user, ok := server.CurrentUser(w, httptest.NewRequest(http.MethodGet, "/api/profile", nil))
			if user != nil || ok {
				t.Fatal("failing external store returned identity")
			}
			checkError(t, w, tc.status, tc.code)
		})
	}
}

func TestExternalStoreHTTPFixedErrorOutcomes(t *testing.T) {
	for _, tc := range []struct {
		name, method, path, body string
		err                      error
		status                   int
		code, retry              string
	}{
		{"invalid credentials", "POST", "/auth/login", `{"email":"demo@example.com","password":"test"}`, auth.InvalidCredentialsError(), 401, "INVALID_CREDENTIALS", ""},
		{"CSRF", "POST", "/auth/logout", "", auth.CSRFInvalidError(), 403, "CSRF_INVALID", ""},
		{"session", "GET", "/auth/me", "", auth.UnauthenticatedError(), 401, "UNAUTHENTICATED", ""},
		{"storage", "GET", "/healthz", "", auth.StorageUnavailableError(), 503, "STORAGE_UNAVAILABLE", ""},
		{"account token", "POST", "/auth/email-verification/confirm", `{"token":"` + strings.Repeat("A", 43) + `"}`, auth.InvalidTokenError(), 400, "INVALID_TOKEN", ""},
		{"rate", "POST", "/auth/login", `{"email":"demo@example.com","password":"test"}`, auth.RateLimitedError(7), 429, "RATE_LIMITED", "7"},
		{"rate lower bound", "POST", "/auth/login", `{"email":"demo@example.com","password":"test"}`, auth.RateLimitedError(0), 429, "RATE_LIMITED", "1"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			config := auth.Config{Origin: "https://example.test", Store: "memory"}
			if strings.Contains(tc.path, "verification") {
				config.Store, config.AccountLifecycle = "postgres", true
			}
			server := auth.NewServerWithStore(config, externalStore{fmt.Errorf("private storage context: %w", tc.err)})
			defer server.Close()
			r := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body))
			r.Header.Set("Origin", "https://example.test")
			r.Header.Set("Content-Type", "application/json")
			w := httptest.NewRecorder()
			server.ServeHTTP(w, r)
			checkError(t, w, tc.status, tc.code)
			if w.Header().Get("Retry-After") != tc.retry {
				t.Fatal("unexpected retry delay")
			}
		})
	}
}

func checkError(t *testing.T, w *httptest.ResponseRecorder, status int, code string) {
	t.Helper()
	if w.Code != status || !strings.Contains(w.Body.String(), `"code":"`+code+`"`) {
		t.Fatalf("status/code mismatch: status %d, expected %d/%s", w.Code, status, code)
	}
	if strings.Contains(w.Body.String(), "private") || strings.Contains(w.Body.String(), "must-not-escape") {
		t.Fatal("external store diagnostic or identity leaked")
	}
	if w.Header().Get("Set-Cookie") != "" || w.Header().Get("Cache-Control") != "no-store" || w.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatal("error response cookie/cache/security policy mismatch")
	}
}
