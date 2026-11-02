package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/jongko54/feature-standards/implementations/go-net-http/auth"
)

const origin = "http://127.0.0.1:5173"

func consumer(t *testing.T) *httptest.Server {
	t.Helper()
	handler, closeStore, err := newHandler(auth.Config{
		Host: "127.0.0.1", Port: "8000", Store: "memory", Demo: true,
		Email: "demo@example.com", Password: "correct-horse-battery-staple", Origin: origin,
		SessionTTL: 30 * time.Minute, RateLimit: 5, RateWindow: time.Minute,
	})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(handler)
	t.Cleanup(closeStore)
	t.Cleanup(server.Close)
	return server
}

func request(t *testing.T, server *httptest.Server, method, path, body string, cookie *http.Cookie, csrf string) *http.Response {
	t.Helper()
	r, err := http.NewRequest(method, server.URL+path, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	r.Header.Set("Origin", origin)
	if body != "" {
		r.Header.Set("Content-Type", "application/json")
	}
	if cookie != nil {
		r.AddCookie(cookie)
	}
	if csrf != "" {
		r.Header.Set("X-CSRF-Token", csrf)
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

func status(t *testing.T, response *http.Response, want int) {
	t.Helper()
	if response.StatusCode != want {
		t.Fatalf("HTTP status %d, want %d", response.StatusCode, want)
	}
}

func login(t *testing.T, server *httptest.Server) (*http.Cookie, string) {
	t.Helper()
	response := request(t, server, http.MethodPost, "/auth/login", `{"email":"demo@example.com","password":"correct-horse-battery-staple"}`, nil, "")
	status(t, response, http.StatusOK)
	var body struct {
		CSRF string `json:"csrfToken"`
	}
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if body.CSRF == "" {
		t.Fatal("CSRF token missing")
	}
	for _, cookie := range response.Cookies() {
		if cookie.Name == "fs_session" {
			if !cookie.HttpOnly || cookie.Path != "/" || cookie.SameSite != http.SameSiteLaxMode {
				t.Fatal("session cookie attributes missing")
			}
			return cookie, body.CSRF
		}
	}
	t.Fatal("session cookie missing")
	return nil, ""
}

func TestConsumerSessionLifecycle(t *testing.T) {
	server := consumer(t)
	status(t, request(t, server, http.MethodGet, "/api/profile", "", nil, ""), http.StatusUnauthorized)
	cookie, csrf := login(t, server)
	profile := request(t, server, http.MethodGet, "/api/profile", "", cookie, "")
	status(t, profile, http.StatusOK)
	var body struct {
		User map[string]string `json:"user"`
	}
	if err := json.NewDecoder(profile.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if body.User["id"] != "demo-user" || body.User["email"] != "demo@example.com" || profile.Header.Get("Cache-Control") != "no-store" {
		t.Fatal("protected identity or cache policy mismatch")
	}
	status(t, request(t, server, http.MethodPost, "/auth/logout", "", cookie, "wrong"), http.StatusForbidden)
	status(t, request(t, server, http.MethodGet, "/api/profile", "", cookie, ""), http.StatusOK)
	logout := request(t, server, http.MethodPost, "/auth/logout", "", cookie, csrf)
	status(t, logout, http.StatusNoContent)
	data, err := io.ReadAll(logout.Body)
	if err != nil || len(data) != 0 {
		t.Fatal("logout must have no response body")
	}
	if cookies := logout.Cookies(); len(cookies) != 1 || cookies[0].MaxAge >= 0 {
		t.Fatal("logout must clear session cookie")
	}
	status(t, request(t, server, http.MethodGet, "/api/profile", "", cookie, ""), http.StatusUnauthorized)
	status(t, request(t, server, http.MethodGet, "/auth/me", "", cookie, ""), http.StatusUnauthorized)
}

func TestConsumerKeepsIndependentSession(t *testing.T) {
	server := consumer(t)
	first, csrf := login(t, server)
	second, _ := login(t, server)
	status(t, request(t, server, http.MethodPost, "/auth/logout", "", first, csrf), http.StatusNoContent)
	status(t, request(t, server, http.MethodGet, "/api/profile", "", first, ""), http.StatusUnauthorized)
	status(t, request(t, server, http.MethodGet, "/api/profile", "", second, ""), http.StatusOK)
}
