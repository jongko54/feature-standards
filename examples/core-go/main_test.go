package main

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jongko54/feature-standards/implementations/go-net-http/auth"
	"github.com/jongko54/feature-standards/libraries/go/authorization"
)

const origin = "http://127.0.0.1:5173"

type membershipState struct {
	mu                                   sync.RWMutex
	roles                                []string
	fail, missing, mismatch, mutateInput bool
}

func (s *membershipState) load(user map[string]string) (*authorization.Principal, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.fail {
		return nil, errors.New("private-provider-detail")
	}
	if s.missing {
		return nil, nil
	}
	subject := user["id"]
	if s.mutateInput {
		user["id"] = "other-user"
		subject = "other-user"
	}
	if s.mismatch {
		subject = "other-user"
	}
	return &authorization.Principal{SubjectID: subject, TenantID: "tenant-a", Roles: append([]string{}, s.roles...)}, nil
}

func consumer(t *testing.T, data ...[]document) (*httptest.Server, *membershipState) {
	t.Helper()
	state := &membershipState{roles: []string{"viewer"}}
	config := auth.Config{
		Host: "127.0.0.1", Port: "8000", Store: "memory", Demo: true,
		Email: "demo@example.com", Password: "correct-horse-battery-staple", Origin: origin,
		SessionTTL: 30 * time.Minute, RateLimit: 1000, RateWindow: time.Minute,
	}
	var handler http.Handler
	var closeStore func()
	var err error
	if len(data) == 0 {
		handler, closeStore, err = newHandler(config, state.load)
	} else {
		handler, closeStore, err = handlerWithDocuments(config, state.load, data[0])
	}
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(handler)
	t.Cleanup(closeStore)
	t.Cleanup(server.Close)
	return server, state
}

func request(t *testing.T, server *httptest.Server, method, path, body string, cookie *http.Cookie, headers ...string) *http.Response {
	t.Helper()
	r, err := http.NewRequest(method, server.URL+path, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < len(headers); i += 2 {
		r.Header.Set(headers[i], headers[i+1])
	}
	if cookie != nil {
		r.AddCookie(cookie)
	}
	client := server.Client()
	client.Timeout = 5 * time.Second
	response, err := client.Do(r)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = response.Body.Close() })
	return response
}

func body(t *testing.T, response *http.Response) map[string]any {
	t.Helper()
	var result map[string]any
	if err := json.NewDecoder(response.Body).Decode(&result); err != nil {
		t.Fatal(err)
	}
	return result
}

func errorResponse(t *testing.T, response *http.Response, status int, code string) {
	t.Helper()
	if response.StatusCode != status {
		t.Fatalf("HTTP status %d, want %d", response.StatusCode, status)
	}
	data := body(t, response)
	if data["error"].(map[string]any)["code"] != code {
		t.Fatal("error code mismatch")
	}
	if response.Header.Get("Cache-Control") != "no-store" || response.Header.Get("X-Content-Type-Options") != "nosniff" {
		t.Fatal("product error headers missing")
	}
	encoded, _ := json.Marshal(data)
	if strings.Contains(string(encoded), "private-provider-detail") {
		t.Fatal("private detail exposed")
	}
}

func login(t *testing.T, server *httptest.Server) (*http.Cookie, string) {
	t.Helper()
	response := request(t, server, "POST", "/auth/login", `{"email":"demo@example.com","password":"correct-horse-battery-staple"}`, nil, "Origin", origin, "Content-Type", "application/json")
	if response.StatusCode != 200 {
		t.Fatalf("login status %d", response.StatusCode)
	}
	data := body(t, response)
	csrf, ok := data["csrfToken"].(string)
	if !ok || csrf == "" {
		t.Fatal("CSRF missing")
	}
	for _, cookie := range response.Cookies() {
		if cookie.Name == "fs_session" {
			return cookie, csrf
		}
	}
	t.Fatal("session cookie missing")
	return nil, ""
}

func TestAnonymousAndForgedSessions(t *testing.T) {
	server, _ := consumer(t)
	for _, path := range []string{"/api/documents", "/api/documents/own-a"} {
		errorResponse(t, request(t, server, "GET", path, "", nil), 401, "UNAUTHENTICATED")
		errorResponse(t, request(t, server, "GET", path, "", &http.Cookie{Name: "fs_session", Value: "forged"}), 401, "UNAUTHENTICATED")
	}
}

func TestProductRoutesAcceptGetOnly(t *testing.T) {
	server, _ := consumer(t)
	response := request(t, server, "POST", "/api/documents", "", nil)
	errorResponse(t, response, 405, "METHOD_NOT_ALLOWED")
	if response.Header.Get("Allow") != "GET" {
		t.Fatal("product Allow header mismatch")
	}
}

func TestOwnerTenantAndHiddenTotals(t *testing.T) {
	server, _ := consumer(t)
	cookie, _ := login(t, server)
	response := request(t, server, "GET", "/api/documents/own-a", "", cookie)
	if response.StatusCode != 200 || body(t, response)["id"] != "own-a" {
		t.Fatal("owner access failed")
	}
	for _, id := range []string{"other-owner", "other-tenant", "missing"} {
		errorResponse(t, request(t, server, "GET", "/api/documents/"+id, "", cookie), 403, "FORBIDDEN")
	}
	response = request(t, server, "GET", "/api/documents?sort=-score&limit=1", "", cookie)
	data := body(t, response)
	if response.StatusCode != 200 || data["total"] != float64(2) || data["nextOffset"] != float64(1) || data["items"].([]any)[0].(map[string]any)["id"] != "own-a" {
		t.Fatal("scoped total or stable pagination mismatch")
	}
	if response.Header.Get("Cache-Control") != "no-store" || response.Header.Get("X-Content-Type-Options") != "nosniff" {
		t.Fatal("product headers missing")
	}
	if _, leaked := data["items"].([]any)[0].(map[string]any)["ownerId"]; leaked {
		t.Fatal("private metadata exposed")
	}
	response = request(t, server, "GET", "/api/documents?sort=-score&limit=1&offset=1", "", cookie)
	data = body(t, response)
	if data["items"].([]any)[0].(map[string]any)["id"] != "own-b" || data["nextOffset"] != nil {
		t.Fatal("second page mismatch")
	}
}

func TestTypedFilteringAndQueryFailures(t *testing.T) {
	server, _ := consumer(t)
	cookie, _ := login(t, server)
	for _, query := range []string{"filter.active=true", "filter.score=2&filter.name=Alpha"} {
		response := request(t, server, "GET", "/api/documents?"+query, "", cookie)
		data := body(t, response)
		if response.StatusCode != 200 || data["total"] != float64(1) || data["items"].([]any)[0].(map[string]any)["id"] != "own-a" {
			t.Fatal("typed filter mismatch")
		}
	}
	for _, query := range []string{"limit=1&%6cimit=2", "sort=ownerId", "filter.active=1", "offset=01", "role=admin", "filter.name=%FF", "filter.name=%00"} {
		errorResponse(t, request(t, server, "GET", "/api/documents?"+query, "", cookie), 400, "INVALID_LIST_QUERY")
	}
	response := request(t, server, "GET", "/api/documents?offset=10000", "", cookie)
	data := body(t, response)
	if data["total"] != float64(2) || len(data["items"].([]any)) != 0 || data["nextOffset"] != nil {
		t.Fatal("out-of-range page mismatch")
	}
}

func TestMembershipRevocationFailureAndSpoofing(t *testing.T) {
	server, state := consumer(t)
	cookie, _ := login(t, server)
	spoof := []string{"X-Role", "admin", "X-Roles", "viewer", "X-Tenant-Id", "tenant-b", "X-Subject-Id", "other-user"}
	errorResponse(t, request(t, server, "GET", "/api/documents/other-tenant", "", cookie, spoof...), 403, "FORBIDDEN")
	state.mu.Lock()
	state.roles = nil
	state.mu.Unlock()
	errorResponse(t, request(t, server, "GET", "/api/documents", "", cookie, spoof...), 403, "FORBIDDEN")
	state.mu.Lock()
	state.roles = []string{"viewer"}
	state.fail = true
	state.mu.Unlock()
	errorResponse(t, request(t, server, "GET", "/api/documents", "", cookie), 503, "AUTHORIZATION_UNAVAILABLE")
	state.mu.Lock()
	state.fail = false
	state.mismatch = true
	state.mu.Unlock()
	errorResponse(t, request(t, server, "GET", "/api/documents/own-a", "", cookie), 403, "FORBIDDEN")
	state.mu.Lock()
	state.mismatch = false
	state.missing = true
	state.mu.Unlock()
	errorResponse(t, request(t, server, "GET", "/api/documents", "", cookie), 403, "FORBIDDEN")
	profile := request(t, server, "GET", "/auth/me", "", cookie)
	if profile.StatusCode != 200 || body(t, profile)["user"].(map[string]any)["id"] != "demo-user" {
		t.Fatal("provider changed the authenticated session identity")
	}
}

func TestTrustedDataFailureIsGeneric(t *testing.T) {
	server, _ := consumer(t, []document{{"tenant-a", "demo-user", map[string]any{"id": "own-a", "score": 2, "active": true}}})
	cookie, _ := login(t, server)
	for _, path := range []string{"/api/documents", "/api/documents/own-a"} {
		errorResponse(t, request(t, server, "GET", path, "", cookie), 500, "INVALID_LIST_DATA")
	}
	invalid, _ := consumer(t, []document{{"tenant-a", "demo-user", map[string]any{"id": "own-a", "name": "Alpha", "score": "private-invalid-number", "active": true}}})
	cookie, _ = login(t, invalid)
	errorResponse(t, request(t, invalid, "GET", "/api/documents?sort=score", "", cookie), 500, "INVALID_LIST_DATA")
}

func TestMembershipProviderCannotReplaceSessionIdentity(t *testing.T) {
	server, state := consumer(t)
	cookie, _ := login(t, server)
	state.mu.Lock()
	state.mutateInput = true
	state.mu.Unlock()
	errorResponse(t, request(t, server, "GET", "/api/documents", "", cookie), 403, "FORBIDDEN")
	errorResponse(t, request(t, server, "GET", "/api/documents/other-owner", "", cookie), 403, "FORBIDDEN")
	profile := request(t, server, "GET", "/auth/me", "", cookie)
	if profile.StatusCode != 200 || body(t, profile)["user"].(map[string]any)["id"] != "demo-user" {
		t.Fatal("provider changed the authenticated session identity")
	}
}

func TestLogoutRevokesCopiedCookie(t *testing.T) {
	server, _ := consumer(t)
	cookie, csrf := login(t, server)
	response := request(t, server, "POST", "/auth/logout", "", cookie, "Origin", origin, "X-CSRF-Token", "wrong")
	if response.StatusCode != 403 {
		t.Fatal("CSRF must reject")
	}
	response = request(t, server, "GET", "/api/documents", "", cookie)
	if response.StatusCode != 200 {
		t.Fatal("failed CSRF revoked session")
	}
	response = request(t, server, "POST", "/auth/logout", "", cookie, "Origin", origin, "X-CSRF-Token", csrf)
	if response.StatusCode != 204 {
		t.Fatal("logout failed")
	}
	if data, err := io.ReadAll(response.Body); err != nil || len(data) != 0 {
		t.Fatal("logout body must be empty")
	}
	errorResponse(t, request(t, server, "GET", "/api/documents", "", cookie), 401, "UNAUTHENTICATED")
	errorResponse(t, request(t, server, "GET", "/api/documents/own-a", "", cookie), 401, "UNAUTHENTICATED")
}
