package main

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"mime"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"golang.org/x/crypto/argon2"
)

type Config struct {
	Host, Port, Email, Password, Origin string
	Store, DatabaseURL                  string
	Demo, Secure                        bool
	AccountLifecycle                    bool
	SessionTTL, RateWindow              time.Duration
	RateLimit                           int
}

type Server struct {
	config       Config
	store        AuthStore
	now          func() time.Time
	mu           sync.Mutex
	sessions     map[string]session
	failures     map[string]failure
	salt         []byte
	passwordHash []byte
}

type Session struct {
	User      map[string]string
	CSRF      string
	ExpiresAt time.Time
}

type session = Session

type failure struct {
	Count     int
	ExpiresAt time.Time
}

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func envBool(name string, fallback bool) (bool, error) {
	switch env(name, strconv.FormatBool(fallback)) {
	case "true":
		return true, nil
	case "false":
		return false, nil
	default:
		return false, fmt.Errorf("%s must be true or false", name)
	}
}

func envPositive(name string, fallback int) (int, error) {
	value, err := strconv.Atoi(env(name, strconv.Itoa(fallback)))
	if err != nil || value <= 0 || int64(value) > math.MaxInt64/int64(time.Second) {
		return 0, fmt.Errorf("%s must be a positive integer within duration range", name)
	}
	return value, nil
}

func validEmail(value string) bool {
	return value != "" && len(value) <= 254 && strings.Contains(value, "@") && utf8.ValidString(value)
}
func normalizeEmail(value string) string {
	// Keep normalization independent of Go/Python Unicode case and space tables.
	value = strings.Trim(value, "\t\n\v\f\r ")
	bytes := []byte(value)
	for i, b := range bytes {
		if b >= 'A' && b <= 'Z' {
			bytes[i] = b + ('a' - 'A')
		}
	}
	return string(bytes)
}

// LoadConfig rejects unsafe defaults outside an explicitly enabled local demo.
func LoadConfig() (Config, error) {
	c := Config{Host: env("AUTH_HOST", "127.0.0.1"), Port: env("AUTH_PORT", "8000"), Origin: env("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173")}
	c.Store = "memory"
	if value, exists := os.LookupEnv("AUTH_STORE"); exists {
		c.Store = value
	}
	if c.Store != "memory" && c.Store != "postgres" {
		return c, errors.New("AUTH_STORE must be memory or postgres")
	}
	if c.Store == "postgres" {
		c.DatabaseURL = os.Getenv("AUTH_DATABASE_URL")
		if !strings.HasPrefix(c.DatabaseURL, "postgresql://") && !strings.HasPrefix(c.DatabaseURL, "postgres://") {
			return c, errors.New("AUTH_DATABASE_URL must be a PostgreSQL URI")
		}
	}
	var err error
	if c.AccountLifecycle, err = envBool("AUTH_ACCOUNT_LIFECYCLE", false); err != nil {
		return c, err
	}
	if raw, exists := os.LookupEnv("AUTH_ACCOUNT_LIFECYCLE"); exists && raw != "true" && raw != "false" {
		return c, errors.New("AUTH_ACCOUNT_LIFECYCLE must be true or false")
	}
	if c.AccountLifecycle && c.Store != "postgres" {
		return c, errors.New("AUTH_ACCOUNT_LIFECYCLE requires postgres storage")
	}
	if c.Demo, err = envBool("AUTH_DEMO", false); err != nil {
		return c, err
	}
	if c.Secure, err = envBool("AUTH_COOKIE_SECURE", true); err != nil {
		return c, err
	}
	port, err := strconv.Atoi(c.Port)
	if err != nil || port < 1 || port > 65535 {
		return c, errors.New("AUTH_PORT must be between 1 and 65535")
	}
	origin, err := url.Parse(c.Origin)
	if err != nil || (origin.Scheme != "http" && origin.Scheme != "https") || origin.Host == "" || origin.Hostname() == "" || origin.User != nil || origin.Path != "" || origin.RawQuery != "" || origin.Fragment != "" || origin.ForceQuery || strings.Contains(c.Origin, "*") {
		return c, errors.New("AUTH_ALLOWED_ORIGIN must be one exact HTTP(S) origin without path, credentials, query or fragment")
	}
	if origin.Port() != "" {
		n, e := strconv.Atoi(origin.Port())
		if e != nil || n < 1 || n > 65535 {
			return c, errors.New("AUTH_ALLOWED_ORIGIN has an invalid port")
		}
	}
	host := origin.Hostname()
	loopback := host == "localhost" || (net.ParseIP(host) != nil && net.ParseIP(host).IsLoopback())
	if !c.Secure && (!c.Demo || !loopback) {
		return c, errors.New("AUTH_COOKIE_SECURE=false is allowed only for an explicit loopback demo")
	}
	if !c.Demo && origin.Scheme != "https" {
		return c, errors.New("non-demo mode requires an HTTPS origin")
	}
	if c.Store == "postgres" {
		c.Email, c.Password = "", ""
	} else if c.Demo {
		c.Email, c.Password = "demo@example.com", "correct-horse-battery-staple"
	} else {
		c.Email, c.Password = normalizeEmail(os.Getenv("AUTH_USER_EMAIL")), os.Getenv("AUTH_USER_PASSWORD")
		if !validEmail(c.Email) || len(c.Password) < 1 || len(c.Password) > 1024 || !utf8.ValidString(c.Password) {
			return c, errors.New("non-demo mode requires valid AUTH_USER_EMAIL and AUTH_USER_PASSWORD")
		}
	}
	ttl, err := envPositive("AUTH_SESSION_TTL_SECONDS", 1800)
	if err != nil {
		return c, err
	}
	window, err := envPositive("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60)
	if err != nil {
		return c, err
	}
	if c.RateLimit, err = envPositive("AUTH_RATE_LIMIT_MAX", 5); err != nil {
		return c, err
	}
	c.SessionTTL, c.RateWindow = time.Duration(ttl)*time.Second, time.Duration(window)*time.Second
	return c, nil
}

func NewServer(config Config) (*Server, error) {
	if config.AccountLifecycle && config.Store != "postgres" {
		return nil, errors.New("AUTH_ACCOUNT_LIFECYCLE requires postgres storage")
	}
	if config.Store != "" && config.Store != "memory" && config.Store != "postgres" {
		return nil, errors.New("AUTH_STORE must be memory or postgres")
	}
	if config.Store == "postgres" {
		store, err := newPostgresStore(config)
		if err != nil {
			return nil, err
		}
		return NewServerWithStore(config, store), nil
	}
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return nil, err
	}
	hash := argon2.IDKey([]byte(config.Password), salt, 3, 64*1024, 4, 32)
	config.Password = ""
	s := NewServerWithStore(config, nil)
	s.salt, s.passwordHash = salt, hash
	s.sessions, s.failures = make(map[string]session), make(map[string]failure)
	s.store = &memoryStore{server: s}
	return s, nil
}

// NewServerWithStore injects an atomic storage adapter without exposing SQL to HTTP.
func NewServerWithStore(config Config, store AuthStore) *Server {
	config.Password, config.DatabaseURL = "", ""
	return &Server{config: config, store: store, now: time.Now}
}

func (s *Server) Close() { s.store.Close() }

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": code}})
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if strings.HasPrefix(r.URL.Path, "/auth/") {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
	}
	var method string
	action, accountRoute := accountRoutes[r.URL.Path]
	if accountRoute {
		if !s.config.AccountLifecycle {
			writeError(w, http.StatusNotFound, "NOT_FOUND")
			return
		}
		method = "POST"
	}
	switch r.URL.Path {
	case "/auth/login", "/auth/logout":
		method = "POST"
	case "/auth/me", "/healthz":
		method = "GET"
	default:
		if !accountRoute {
			writeError(w, http.StatusNotFound, "NOT_FOUND")
			return
		}
	}
	if r.Method != method {
		w.Header().Set("Allow", method)
		writeError(w, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED")
		return
	}
	if method == "POST" && (len(r.Header.Values("Origin")) != 1 || r.Header.Get("Origin") != s.config.Origin) {
		writeError(w, http.StatusForbidden, "ORIGIN_DENIED")
		return
	}
	if accountRoute {
		s.account(w, r, action)
		return
	}
	switch r.URL.Path {
	case "/auth/login":
		s.login(w, r)
	case "/auth/me":
		s.me(w, r)
	case "/auth/logout":
		s.logout(w, r)
	case "/healthz":
		if err := s.store.Ready(r.Context()); err != nil {
			writeAuthError(w, err)
			return
		}
		profile := "browser-session-v1"
		if s.config.Store == "postgres" {
			profile = "browser-session-v2"
		}
		if s.config.AccountLifecycle {
			profile = "browser-session-v3"
		}
		writeJSON(w, 200, map[string]string{"status": "ok", "profile": profile, "implementation": "go-net-http"})
	}
}

// strictJSONString checks escaped UTF-16 code units before encoding/json can
// replace unpaired surrogates with U+FFFD. JSON syntax stays the stdlib's job.
func strictJSONString(raw []byte) (string, bool) {
	if len(raw) < 2 || raw[0] != '"' || !json.Valid(raw) {
		return "", false
	}
	for i := 1; i < len(raw)-1; i++ {
		if raw[i] != '\\' {
			continue
		}
		i++ // Skip the escaped character, including a literal escaped backslash.
		if raw[i] != 'u' {
			continue
		}
		unit, err := strconv.ParseUint(string(raw[i+1:i+5]), 16, 16)
		if err != nil {
			return "", false
		}
		i += 4
		if unit >= 0xDC00 && unit <= 0xDFFF {
			return "", false
		}
		if unit >= 0xD800 && unit <= 0xDBFF {
			next := i + 1
			if next+6 > len(raw)-1 || raw[next] != '\\' || raw[next+1] != 'u' {
				return "", false
			}
			low, err := strconv.ParseUint(string(raw[next+2:next+6]), 16, 16)
			if err != nil || low < 0xDC00 || low > 0xDFFF {
				return "", false
			}
			i = next + 5
		}
	}
	var value string
	if err := json.Unmarshal(raw, &value); err != nil {
		return "", false
	}
	return value, true
}

func decodeCredentials(body []byte) (email, password string, ok bool) {
	if !utf8.Valid(body) {
		return "", "", false
	}
	decoder := json.NewDecoder(strings.NewReader(string(body)))
	start, err := decoder.Token()
	if err != nil || start != json.Delim('{') {
		return "", "", false
	}
	seen := map[string]bool{}
	for decoder.More() {
		token, err := decoder.Token()
		key, isString := token.(string)
		if err != nil || !isString || seen[key] || (key != "email" && key != "password") {
			return "", "", false
		}
		seen[key] = true
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			return "", "", false
		}
		value, validString := strictJSONString(raw)
		if !validString {
			return "", "", false
		}
		if key == "email" {
			email = value
		} else {
			password = value
		}
	}
	end, err := decoder.Token()
	if err != nil || end != json.Delim('}') {
		return "", "", false
	}
	if _, err := decoder.Token(); err != io.EOF {
		return "", "", false
	}
	email = normalizeEmail(email)
	return email, password, seen["email"] && seen["password"] && validEmail(email) && len(password) >= 1 && len(password) <= 1024
}

func peerIP(r *http.Request) string {
	if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
		return host
	}
	return r.RemoteAddr
}

func sessionToken(r *http.Request) string {
	cookie, err := r.Cookie("fs_session")
	if err != nil {
		return ""
	}
	return cookie.Value
}

func randomToken() (string, error) {
	value := make([]byte, 32)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(value), nil
}

// prune is called under mu. An active deployment cannot accumulate expired state.
func (s *Server) prune(now time.Time) {
	for id, value := range s.sessions {
		if !now.Before(value.ExpiresAt) {
			delete(s.sessions, id)
		}
	}
	for ip, value := range s.failures {
		if !now.Before(value.ExpiresAt) {
			delete(s.failures, ip)
		}
	}
}

func (s *Server) setCookie(w http.ResponseWriter, token string, logout bool) {
	cookie := &http.Cookie{Name: "fs_session", Value: token, Path: "/", HttpOnly: true, Secure: s.config.Secure, SameSite: http.SameSiteLaxMode, MaxAge: int(s.config.SessionTTL / time.Second)}
	if logout {
		cookie.MaxAge = -1
	}
	http.SetCookie(w, cookie)
}

func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	mediaType, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mediaType != "application/json" {
		writeError(w, http.StatusUnsupportedMediaType, "UNSUPPORTED_MEDIA_TYPE")
		return
	}
	if r.ContentLength > 4096 {
		writeError(w, http.StatusRequestEntityTooLarge, "REQUEST_TOO_LARGE")
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 4097))
	if err != nil {
		writeError(w, http.StatusBadRequest, "INVALID_REQUEST")
		return
	}
	if len(body) > 4096 {
		writeError(w, http.StatusRequestEntityTooLarge, "REQUEST_TOO_LARGE")
		return
	}
	email, password, ok := decodeCredentials(body)
	if !ok {
		writeError(w, http.StatusBadRequest, "INVALID_REQUEST")
		return
	}
	token, value, err := s.store.Login(r.Context(), peerIP(r), email, password, sessionToken(r))
	if err != nil {
		writeAuthError(w, err)
		return
	}
	s.setCookie(w, token, false)
	s.writeUser(w, value)
}

func (s *Server) writeUser(w http.ResponseWriter, value Session) {
	writeJSON(w, http.StatusOK, map[string]any{"user": value.User, "csrfToken": value.CSRF})
}

func (s *Server) me(w http.ResponseWriter, r *http.Request) {
	value, err := s.store.Current(r.Context(), sessionToken(r))
	if err != nil {
		writeAuthError(w, err)
		return
	}
	s.writeUser(w, value)
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	csrf := ""
	if len(r.Header.Values("X-CSRF-Token")) == 1 {
		csrf = r.Header.Get("X-CSRF-Token")
	}
	if err := s.store.Logout(r.Context(), sessionToken(r), csrf); err != nil {
		writeAuthError(w, err)
		return
	}
	s.setCookie(w, "", true)
	w.WriteHeader(http.StatusNoContent)
}

// AuthStore operations own the complete transaction and return only committed results.
type AuthStore interface {
	Login(context.Context, string, string, string, string) (string, Session, error)
	Current(context.Context, string) (Session, error)
	Logout(context.Context, string, string) error
	Ready(context.Context) error
	Close()
}

type authFailure struct {
	Status int
	Code   string
	Retry  int
}

func (e *authFailure) Error() string          { return e.Code }
func authError(status int, code string) error { return &authFailure{Status: status, Code: code} }
func storageError() error                     { return authError(503, "STORAGE_UNAVAILABLE") }
func writeAuthError(w http.ResponseWriter, err error) {
	var failure *authFailure
	if !errors.As(err, &failure) {
		failure = &authFailure{Status: 500, Code: "INTERNAL_ERROR"}
	}
	if failure.Retry > 0 {
		w.Header().Set("Retry-After", strconv.Itoa(failure.Retry))
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	writeError(w, failure.Status, failure.Code)
}
