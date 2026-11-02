package main

import (
	"context"
	"net/http"
	"strings"
	"testing"
)

type accountCall struct{ action, peer, email, token, password string }
type accountTestStore struct {
	AuthStore
	calls []accountCall
	err   error
}

func (a *accountTestStore) Ready(context.Context) error { return nil }
func (a *accountTestStore) Account(_ context.Context, action, peer, email, token, password string) error {
	a.calls = append(a.calls, accountCall{action, peer, email, token, password})
	return a.err
}

func TestAccountConfigurationRequiresPostgres(t *testing.T) {
	t.Setenv("AUTH_DEMO", "true")
	t.Setenv("AUTH_ACCOUNT_LIFECYCLE", "true")
	t.Setenv("AUTH_STORE", "memory")
	if _, err := LoadConfig(); err == nil {
		t.Fatal("memory lifecycle accepted")
	}
	t.Setenv("AUTH_STORE", "postgres")
	t.Setenv("AUTH_DATABASE_URL", "postgresql://127.0.0.1/test")
	c, err := LoadConfig()
	if err != nil || !c.AccountLifecycle {
		t.Fatalf("v3 config %v", err)
	}
	for _, invalid := range []string{"TRUE", ""} {
		t.Setenv("AUTH_ACCOUNT_LIFECYCLE", invalid)
		if _, err := LoadConfig(); err == nil {
			t.Fatal("ambiguous boolean accepted")
		}
	}
	c = testConfig()
	c.AccountLifecycle = true
	if _, err := NewServer(c); err == nil {
		t.Fatal("direct memory lifecycle accepted")
	}
}

func TestAccountRoutesAreHiddenInOlderProfiles(t *testing.T) {
	s := testServer(t)
	for path := range accountRoutes {
		for _, method := range []string{"GET", "POST", "PUT"} {
			responseCode(t, request(s, method, path, "", nil, nil), 404, "NOT_FOUND")
		}
	}
}

func TestAccountHTTPContractAndOutcomes(t *testing.T) {
	c := testConfig()
	c.Store = "postgres"
	c.AccountLifecycle = true
	store := &accountTestStore{}
	s := NewServerWithStore(c, store)
	headers := map[string]string{"Origin": c.Origin, "Content-Type": "application/json"}
	if got := request(s, "GET", "/healthz", "", nil, nil).Body.String(); !strings.Contains(got, "browser-session-v3") {
		t.Fatal(got)
	}
	cases := []struct {
		path, action, body, email, token, password string
		status                                     int
	}{
		{"/auth/register", "register", `{"email":"  한@EXAMPLE.COM  ","password":"` + demoPassword + `"}`, "한@example.com", "", demoPassword, 202},
		{"/auth/email-verification/request", "verify-request", `{"email":"한@example.com"}`, "한@example.com", "", "", 202},
		{"/auth/email-verification/confirm", "verify-confirm", `{"token":"` + strings.Repeat("A", 43) + `"}`, "", strings.Repeat("A", 43), "", 204},
		{"/auth/password-reset/request", "reset-request", `{"email":"한@example.com"}`, "한@example.com", "", "", 202},
		{"/auth/password-reset/confirm", "reset-confirm", `{"token":"` + strings.Repeat("A", 43) + `","password":"` + demoPassword + `"}`, "", strings.Repeat("A", 43), demoPassword, 204},
	}
	for _, tc := range cases {
		got := request(s, "POST", tc.path, tc.body, nil, headers)
		responseCode(t, got, tc.status, "")
		if got.Header().Get("Set-Cookie") != "" || got.Header().Get("Cache-Control") != "no-store" || got.Header().Get("X-Content-Type-Options") != "nosniff" {
			t.Fatal(got.Header())
		}
		if tc.status == 204 && got.Body.Len() != 0 {
			t.Fatal("confirm body present")
		}
		if tc.status == 202 && strings.TrimSpace(got.Body.String()) != `{"status":"accepted"}` {
			t.Fatal(got.Body.String())
		}
		call := store.calls[len(store.calls)-1]
		if call != (accountCall{tc.action, "127.0.0.1", tc.email, tc.token, tc.password}) {
			t.Fatalf("unexpected storage args %#v", call)
		}
	}
	for _, failure := range []*authFailure{{Status: 400, Code: "INVALID_TOKEN"}, {Status: 429, Code: "RATE_LIMITED", Retry: 59}, {Status: 503, Code: "STORAGE_UNAVAILABLE"}} {
		store.err = failure
		got := request(s, "POST", cases[2].path, cases[2].body, nil, headers)
		responseCode(t, got, failure.Status, failure.Code)
		if got.Header().Get("Set-Cookie") != "" {
			t.Fatal("error issued cookie")
		}
		if failure.Retry > 0 && got.Header().Get("Retry-After") != "59" {
			t.Fatal("missing retry")
		}
	}
}

func TestAccountInputBoundaries(t *testing.T) {
	for _, body := range []string{`{"email":"a\u0000@b"}`, `{"email":"a\r\n@b"}`, `{"email":"a b@c"}`, `{"email":"a\u007f@b"}`} {
		if _, ok := decodeAccount("reset-request", []byte(body)); ok {
			t.Fatal("unsafe email accepted")
		}
	}
	for _, body := range []string{`null`, `[]`, `{"email":"a@b","email":"c@d"}`, `{"email":null}`, `{"email":"a@b","extra":"x"}`, `{"email":"\ud800@b"}`, `{"email":"a@b"} {}`, `{"email":NaN}`} {
		if _, ok := decodeAccount("reset-request", []byte(body)); ok {
			t.Fatalf("accepted %q", body)
		}
	}
	for _, password := range []string{strings.Repeat("a", 14), strings.Repeat("😀", 14), strings.Repeat("한", 342)} {
		if _, ok := decodeAccount("register", []byte(`{"email":"a@b","password":"`+password+`"}`)); ok {
			t.Fatal("bad password accepted")
		}
	}
	for _, password := range []string{strings.Repeat("😀", 15), strings.Repeat(" ", 15), strings.Repeat("a", 1024)} {
		if _, ok := decodeAccount("register", []byte(`{"email":"a@b","password":"`+password+`"}`)); !ok {
			t.Fatal("valid unicode/byte boundary rejected")
		}
	}
	c := testConfig()
	c.Store = "postgres"
	c.AccountLifecycle = true
	store := &accountTestStore{}
	s := NewServerWithStore(c, store)
	path := "/auth/email-verification/confirm"
	responseCode(t, request(s, "POST", path, `{}`, nil, nil), 403, "ORIGIN_DENIED")
	responseCode(t, request(s, "POST", path, `{}`, nil, map[string]string{"Origin": c.Origin}), 415, "UNSUPPORTED_MEDIA_TYPE")
	responseCode(t, request(s, "POST", path, strings.Repeat("x", 4097), nil, map[string]string{"Origin": c.Origin, "Content-Type": "application/json"}), 413, "REQUEST_TOO_LARGE")
	responseCode(t, request(s, http.MethodGet, path, "", nil, nil), 405, "METHOD_NOT_ALLOWED")
	if len(store.calls) != 0 {
		t.Fatal("invalid request reached store")
	}
}
