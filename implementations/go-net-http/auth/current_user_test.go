package auth

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestCurrentUserReturnsIndependentIdentity(t *testing.T) {
	s := testServer(t)
	defer s.Close()
	cookie, _ := readLogin(t, loginRequest(s, nil))
	r := httptest.NewRequest(http.MethodGet, "/api/profile", nil)
	r.AddCookie(cookie)
	w := httptest.NewRecorder()
	user, ok := s.CurrentUser(w, r)
	if !ok || user["email"] != "demo@example.com" {
		t.Fatal("authenticated identity missing")
	}
	if w.Header().Get("Cache-Control") != "no-store" || w.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatal("protected response must not be cached or sniffed")
	}
	user["email"] = "changed@example.com"
	user, ok = s.CurrentUser(httptest.NewRecorder(), r)
	if !ok || user["email"] != "demo@example.com" {
		t.Fatal("caller mutated stored identity")
	}
}

func TestCurrentUserRefusesAnonymousAndExpiredSession(t *testing.T) {
	s := testServer(t)
	defer s.Close()
	r := httptest.NewRequest(http.MethodGet, "/api/profile", nil)
	w := httptest.NewRecorder()
	user, ok := s.CurrentUser(w, r)
	if ok || user != nil {
		t.Fatal("anonymous request must not return an identity")
	}
	responseCode(t, w, http.StatusUnauthorized, "UNAUTHENTICATED")
	cookie, _ := readLogin(t, loginRequest(s, nil))
	r.AddCookie(cookie)
	now := s.now()
	s.now = func() time.Time { return now.Add(s.config.SessionTTL) }
	w = httptest.NewRecorder()
	user, ok = s.CurrentUser(w, r)
	if ok || user != nil {
		t.Fatal("expired request must not return an identity")
	}
	responseCode(t, w, http.StatusUnauthorized, "UNAUTHENTICATED")
}

type unavailableCurrentStore struct {
	AuthStore
	err error
}

func (s unavailableCurrentStore) Current(context.Context, string) (Session, error) {
	return Session{}, s.err
}

func TestCurrentUserFailsClosedWithoutStorageDetails(t *testing.T) {
	for _, tc := range []struct {
		err    error
		status int
		code   string
	}{
		{storageError(), 503, "STORAGE_UNAVAILABLE"},
		{errors.New("private database diagnostic"), 500, "INTERNAL_ERROR"},
	} {
		s := NewServerWithStore(testConfig(), unavailableCurrentStore{err: tc.err})
		w := httptest.NewRecorder()
		user, ok := s.CurrentUser(w, httptest.NewRequest(http.MethodGet, "/api/profile", nil))
		if ok || user != nil {
			t.Fatal("storage failure returned identity")
		}
		responseCode(t, w, tc.status, tc.code)
		if strings.Contains(w.Body.String(), "private") {
			t.Fatal("storage diagnostic leaked")
		}
	}
}
