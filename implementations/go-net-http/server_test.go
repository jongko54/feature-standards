package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

const demoPassword = "correct-horse-battery-staple"

func testConfig() Config {
	return Config{Host: "127.0.0.1", Port: "8000", Demo: true, Email: "demo@example.com", Password: demoPassword, Origin: "http://127.0.0.1:5173", SessionTTL: 30 * time.Minute, RateLimit: 5, RateWindow: time.Minute}
}

func testServer(t *testing.T) *Server {
	t.Helper()
	s, err := NewServer(testConfig())
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func request(s *Server, method, path, body string, cookie *http.Cookie, headers map[string]string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.RemoteAddr = "127.0.0.1:11000"
	if cookie != nil {
		r.AddCookie(cookie)
	}
	for k, v := range headers {
		r.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	s.ServeHTTP(w, r)
	return w
}

func loginRequest(s *Server, cookie *http.Cookie) *httptest.ResponseRecorder {
	return request(s, http.MethodPost, "/auth/login", `{"email":"demo@example.com","password":"`+demoPassword+`"}`, cookie, map[string]string{"Origin": s.config.Origin, "Content-Type": "application/json"})
}

func responseCode(t *testing.T, w *httptest.ResponseRecorder, wantStatus int, wantCode string) {
	t.Helper()
	if w.Code != wantStatus {
		t.Fatalf("status %d, want %d: %s", w.Code, wantStatus, w.Body.String())
	}
	if wantCode != "" {
		var body struct {
			Error struct {
				Code string `json:"code"`
			} `json:"error"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
			t.Fatal(err)
		}
		if body.Error.Code != wantCode {
			t.Fatalf("error code %q, want %q", body.Error.Code, wantCode)
		}
	}
}

func readLogin(t *testing.T, w *httptest.ResponseRecorder) (*http.Cookie, string) {
	t.Helper()
	responseCode(t, w, 200, "")
	var body struct {
		User struct {
			ID    string `json:"id"`
			Email string `json:"email"`
		} `json:"user"`
		CSRF string `json:"csrfToken"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.User.ID != "demo-user" || body.User.Email != "demo@example.com" || len(body.CSRF) < 43 {
		t.Fatalf("unexpected login body %s", w.Body.String())
	}
	for _, c := range w.Result().Cookies() {
		if c.Name == "fs_session" {
			return c, body.CSRF
		}
	}
	t.Fatal("session cookie missing")
	return nil, ""
}

func TestSessionLifecycleAndCopiedCookie(t *testing.T) {
	s := testServer(t)
	responseCode(t, request(s, "GET", "/auth/me", "", nil, nil), 401, "UNAUTHENTICATED")
	cookie, csrf := readLogin(t, loginRequest(s, nil))
	if !cookie.HttpOnly || cookie.SameSite != http.SameSiteLaxMode || cookie.Path != "/" || cookie.Domain != "" || cookie.MaxAge != 1800 {
		t.Fatalf("bad cookie: %#v", cookie)
	}
	responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 200, "")
	responseCode(t, request(s, "POST", "/auth/logout", "", cookie, map[string]string{"Origin": s.config.Origin}), 403, "CSRF_INVALID")
	responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 200, "")
	w := request(s, "POST", "/auth/logout", "", cookie, map[string]string{"Origin": s.config.Origin, "X-CSRF-Token": csrf})
	responseCode(t, w, 204, "")
	if w.Body.Len() != 0 || !strings.Contains(w.Header().Get("Set-Cookie"), "Max-Age=0") {
		t.Fatal("logout must clear cookie and have no body")
	}
	responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 401, "UNAUTHENTICATED")
	responseCode(t, request(s, "POST", "/auth/logout", "", cookie, map[string]string{"Origin": s.config.Origin}), 204, "")
}

func TestLoginRotationPreservesIndependentSession(t *testing.T) {
	s := testServer(t)
	first, _ := readLogin(t, loginRequest(s, nil))
	independent, _ := readLogin(t, loginRequest(s, nil))
	replacement, _ := readLogin(t, loginRequest(s, first))
	if first.Value == replacement.Value {
		t.Fatal("login did not rotate session ID")
	}
	responseCode(t, request(s, "GET", "/auth/me", "", first, nil), 401, "UNAUTHENTICATED")
	responseCode(t, request(s, "GET", "/auth/me", "", independent, nil), 200, "")
	responseCode(t, request(s, "GET", "/auth/me", "", replacement, nil), 200, "")
}

func TestOriginAndResponseHeaders(t *testing.T) {
	s := testServer(t)
	for _, origin := range []string{"", "null", "http://evil.example", s.config.Origin + "/"} {
		w := request(s, "POST", "/auth/login", `{}`, nil, map[string]string{"Content-Type": "application/json", "Origin": origin})
		responseCode(t, w, 403, "ORIGIN_DENIED")
		if w.Header().Get("Cache-Control") != "no-store" || w.Header().Get("X-Content-Type-Options") != "nosniff" {
			t.Fatal("auth response security headers missing")
		}
		if w.Header().Get("Access-Control-Allow-Origin") != "" {
			t.Fatal("profile must not enable CORS")
		}
	}
	responseCode(t, request(s, "GET", "/auth/login", "", nil, nil), 405, "METHOD_NOT_ALLOWED")
	responseCode(t, request(s, "GET", "/auth/not-real", "", nil, nil), 404, "NOT_FOUND")
}

func TestStrictJSONAndBounds(t *testing.T) {
	s := testServer(t)
	cases := []struct {
		name, body string
		status     int
		code       string
	}{
		{"duplicate", `{"email":"demo@example.com","email":"other@example.com","password":"x"}`, 400, "INVALID_REQUEST"},
		{"unknown", `{"email":"demo@example.com","password":"x","admin":true}`, 400, "INVALID_REQUEST"},
		{"null", `{"email":"demo@example.com","password":null}`, 400, "INVALID_REQUEST"},
		{"array", `[]`, 400, "INVALID_REQUEST"},
		{"trailing", `{"email":"demo@example.com","password":"x"}{}`, 400, "INVALID_REQUEST"},
		{"invalid utf8", "{\"email\":\"\xff@example.com\",\"password\":\"x\"}", 400, "INVALID_REQUEST"},
		{"lone high surrogate", `{"email":"demo@example.com","password":"\ud800"}`, 400, "INVALID_REQUEST"},
		{"lone low surrogate", `{"email":"demo@example.com","password":"\udfff"}`, 400, "INVALID_REQUEST"},
		{"high surrogate then text", `{"email":"demo@example.com","password":"\ud800x"}`, 400, "INVALID_REQUEST"},
		{"long password", `{"email":"demo@example.com","password":"` + strings.Repeat("x", 1025) + `"}`, 400, "INVALID_REQUEST"},
		{"long unicode password", `{"email":"demo@example.com","password":"` + strings.Repeat("한", 342) + `"}`, 400, "INVALID_REQUEST"},
		{"huge", strings.Repeat("x", 4097), 413, "REQUEST_TOO_LARGE"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			responseCode(t, request(s, "POST", "/auth/login", tc.body, nil, map[string]string{"Origin": s.config.Origin, "Content-Type": "application/json"}), tc.status, tc.code)
		})
	}
	responseCode(t, request(s, "POST", "/auth/login", `{}`, nil, map[string]string{"Origin": s.config.Origin, "Content-Type": "text/plain"}), 415, "UNSUPPORTED_MEDIA_TYPE")
	responseCode(t, request(s, "POST", "/auth/login", `{"email":" DEMO@EXAMPLE.COM ","password":"`+demoPassword+`"}`, nil, map[string]string{"Origin": s.config.Origin, "Content-Type": "application/json; charset=utf-8"}), 200, "")
}

func TestStrictSurrogateEscapes(t *testing.T) {
	cases := []struct {
		name, raw, want string
		valid           bool
	}{
		{"lone high", `"\ud800"`, "", false},
		{"lone low", `"\udfff"`, "", false},
		{"high then text", `"\ud800x"`, "", false},
		{"high then high", `"\ud800\ud800"`, "", false},
		{"low then high", `"\udfff\ud800"`, "", false},
		{"high then escaped backslash", `"\ud800\\udc00"`, "", false},
		{"paired emoji", `"\ud83d\ude00"`, "😀", true},
		{"uppercase pair", `"\uD83D\uDE00"`, "😀", true},
		{"maximum scalar", `"\udbff\udfff"`, "\U0010ffff", true},
		{"literal slash-u text", `"\\ud800"`, `\ud800`, true},
		{"escaped slash then pair", `"\\\ud83d\ude00"`, "\\😀", true},
		{"replacement character", `"�"`, "�", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			body := []byte(`{"email":"demo@example.com","password":` + tc.raw + `}`)
			_, password, ok := decodeCredentials(body)
			if ok != tc.valid || (ok && password != tc.want) {
				t.Fatalf("decode valid=%v password=%q; want valid=%v password=%q", ok, password, tc.valid, tc.want)
			}
		})
	}
}

func TestEmailNormalizationIsASCIIOnly(t *testing.T) {
	cases := []struct{ input, want string }{
		{"\t\n\v\f\r DEMO@EXAMPLE.COM \t\n\v\f\r", "demo@example.com"},
		{"İSTANBUL@EXAMPLE.COM", "İstanbul@example.com"},
		{"\u00a0DEMO@EXAMPLE.COM\u00a0", "\u00a0demo@example.com\u00a0"},
		{"\u0085DEMO@EXAMPLE.COM\u0085", "\u0085demo@example.com\u0085"},
		{"\u001cDEMO@EXAMPLE.COM\u001c", "\u001cdemo@example.com\u001c"},
		{"K@EXAMPLE.COM", "K@example.com"},
	}
	for _, tc := range cases {
		if got := normalizeEmail(tc.input); got != tc.want {
			t.Errorf("normalizeEmail(%q)=%q, want %q", tc.input, got, tc.want)
		}
		body, err := json.Marshal(map[string]string{"email": tc.input, "password": "x"})
		if err != nil {
			t.Fatal(err)
		}
		email, _, ok := decodeCredentials(body)
		if !ok || email != tc.want {
			t.Errorf("request normalization=%q valid=%v, want %q", email, ok, tc.want)
		}
	}
}

func TestConfiguredUserUsesSameASCIINormalization(t *testing.T) {
	for _, name := range []string{"AUTH_HOST", "AUTH_PORT", "AUTH_SESSION_TTL_SECONDS", "AUTH_RATE_LIMIT_MAX", "AUTH_RATE_LIMIT_WINDOW_SECONDS"} {
		t.Setenv(name, "")
	}
	t.Setenv("AUTH_DEMO", "false")
	t.Setenv("AUTH_ALLOWED_ORIGIN", "https://example.com")
	t.Setenv("AUTH_COOKIE_SECURE", "true")
	t.Setenv("AUTH_USER_EMAIL", "\t İDEMO@EXAMPLE.COM\u00a0")
	t.Setenv("AUTH_USER_PASSWORD", demoPassword)
	config, err := LoadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if config.Email != "İdemo@example.com\u00a0" {
		t.Fatalf("configured email=%q", config.Email)
	}
	s, err := NewServer(config)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]string{"email": "\r İDEMO@EXAMPLE.COM\u00a0", "password": demoPassword})
	responseCode(t, request(s, "POST", "/auth/login", string(body), nil, map[string]string{"Origin": config.Origin, "Content-Type": "application/json"}), 200, "")
}

func TestExpirationIsAbsoluteAndPrunesState(t *testing.T) {
	s := testServer(t)
	now := time.Now()
	s.now = func() time.Time { return now }
	cookie, _ := readLogin(t, loginRequest(s, nil))
	now = now.Add(29 * time.Minute)
	responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 200, "")
	now = now.Add(time.Minute)
	responseCode(t, request(s, "GET", "/auth/me", "", cookie, nil), 401, "UNAUTHENTICATED")
	if len(s.sessions) != 0 {
		t.Fatal("expired session not pruned")
	}
}

func TestRateLimitUsesPeerAndRecovers(t *testing.T) {
	s := testServer(t)
	now := time.Now()
	s.now = func() time.Time { return now }
	for i := 0; i < 5; i++ {
		responseCode(t, request(s, "POST", "/auth/login", `{"email":"missing@example.com","password":"x"}`, nil, map[string]string{"Origin": s.config.Origin, "Content-Type": "application/json", "X-Forwarded-For": "192.0.2." + strings.Repeat("1", i+1)}), 401, "INVALID_CREDENTIALS")
	}
	w := loginRequest(s, nil)
	responseCode(t, w, 429, "RATE_LIMITED")
	if w.Header().Get("Retry-After") != "60" {
		t.Fatalf("bad Retry-After %q", w.Header().Get("Retry-After"))
	}
	now = now.Add(time.Minute)
	readLogin(t, loginRequest(s, nil))
	if len(s.failures) != 0 {
		t.Fatal("successful login failed to reset limiter")
	}
}

func TestConcurrentSessions(t *testing.T) {
	s := testServer(t)
	cookie, _ := readLogin(t, loginRequest(s, nil))
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			w := request(s, "GET", "/auth/me", "", cookie, nil)
			if w.Code != 200 {
				t.Errorf("concurrent me: %d", w.Code)
			}
		}()
	}
	wg.Wait()
}

func TestHealth(t *testing.T) {
	s := testServer(t)
	w := request(s, "GET", "/healthz", "", nil, nil)
	responseCode(t, w, 200, "")
	if !bytes.Contains(w.Body.Bytes(), []byte(`"profile":"browser-session-v1"`)) {
		t.Fatal("profile missing")
	}
}

func TestConfigSafety(t *testing.T) {
	for _, name := range []string{"AUTH_HOST", "AUTH_PORT", "AUTH_DEMO", "AUTH_USER_EMAIL", "AUTH_USER_PASSWORD", "AUTH_ALLOWED_ORIGIN", "AUTH_COOKIE_SECURE", "AUTH_SESSION_TTL_SECONDS", "AUTH_RATE_LIMIT_MAX", "AUTH_RATE_LIMIT_WINDOW_SECONDS"} {
		t.Setenv(name, "")
	}
	if _, err := LoadConfig(); err == nil {
		t.Fatal("non-demo mode without credentials must fail")
	}
	t.Setenv("AUTH_DEMO", "true")
	t.Setenv("AUTH_COOKIE_SECURE", "false")
	if _, err := LoadConfig(); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AUTH_ALLOWED_ORIGIN", "http://example.com")
	if _, err := LoadConfig(); err == nil {
		t.Fatal("insecure non-loopback origin accepted")
	}
	t.Setenv("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173/path")
	if _, err := LoadConfig(); err == nil {
		t.Fatal("origin with path accepted")
	}
	t.Setenv("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173")
	t.Setenv("AUTH_SESSION_TTL_SECONDS", "0")
	if _, err := LoadConfig(); err == nil {
		t.Fatal("nonpositive TTL accepted")
	}
}

func TestHTTPIntegration(t *testing.T) {
	s := testServer(t)
	h := httptest.NewServer(s)
	defer h.Close()
	r, err := http.NewRequest("POST", h.URL+"/auth/login", strings.NewReader(`{"email":"demo@example.com","password":"`+demoPassword+`"}`))
	if err != nil {
		t.Fatal(err)
	}
	r.Header.Set("Origin", s.config.Origin)
	r.Header.Set("Content-Type", "application/json")
	resp, err := h.Client().Do(r)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 || !strings.Contains(string(body), "csrfToken") {
		t.Fatalf("HTTP login: %d %s", resp.StatusCode, body)
	}
}

func TestUnsupportedStoreRejected(t *testing.T) {
	t.Setenv("AUTH_STORE", "unsupported")
	t.Setenv("AUTH_DEMO", "true")
	if _, err := LoadConfig(); err == nil {
		t.Fatal("unsupported store accepted")
	}
}
