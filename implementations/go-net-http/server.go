package main

import (
	"crypto/rand"
	"crypto/subtle"
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
	Demo, Secure                        bool
	SessionTTL, RateWindow              time.Duration
	RateLimit                           int
}

type Server struct {
	config       Config
	now          func() time.Time
	mu           sync.Mutex
	sessions     map[string]session
	failures     map[string]failure
	salt         []byte
	passwordHash []byte
}

type session struct {
	CSRF      string
	ExpiresAt time.Time
}

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
	var err error
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
	if c.Demo {
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
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return nil, err
	}
	// RFC 9106's memory-constrained recommendation: Argon2id, 64 MiB, 3 passes.
	hash := argon2.IDKey([]byte(config.Password), salt, 3, 64*1024, 4, 32)
	config.Password = ""
	return &Server{config: config, now: time.Now, sessions: make(map[string]session), failures: make(map[string]failure), salt: salt, passwordHash: hash}, nil
}

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
	switch r.URL.Path {
	case "/auth/login", "/auth/logout":
		method = "POST"
	case "/auth/me", "/healthz":
		method = "GET"
	default:
		writeError(w, http.StatusNotFound, "NOT_FOUND")
		return
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
	switch r.URL.Path {
	case "/auth/login":
		s.login(w, r)
	case "/auth/me":
		s.me(w, r)
	case "/auth/logout":
		s.logout(w, r)
	case "/healthz":
		writeJSON(w, 200, map[string]string{"status": "ok", "profile": "browser-session-v1", "implementation": "go-net-http"})
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
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.now()
	s.prune(now)
	ip := peerIP(r)
	failureRecord := s.failures[ip]
	if failureRecord.Count >= s.config.RateLimit {
		retry := int(math.Ceil(failureRecord.ExpiresAt.Sub(now).Seconds()))
		if retry < 1 {
			retry = 1
		}
		w.Header().Set("Retry-After", strconv.Itoa(retry))
		writeError(w, http.StatusTooManyRequests, "RATE_LIMITED")
		return
	}
	// Serialize verification to bound Argon2 memory use and make rate limits atomic.
	derived := argon2.IDKey([]byte(password), s.salt, 3, 64*1024, 4, 32)
	passwordValid := subtle.ConstantTimeCompare(derived, s.passwordHash) == 1
	if !passwordValid || email != s.config.Email {
		if failureRecord.Count == 0 {
			failureRecord.ExpiresAt = now.Add(s.config.RateWindow)
		}
		failureRecord.Count++
		s.failures[ip] = failureRecord
		writeError(w, http.StatusUnauthorized, "INVALID_CREDENTIALS")
		return
	}
	token, err := randomToken()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "INTERNAL_ERROR")
		return
	}
	csrf, err := randomToken()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "INTERNAL_ERROR")
		return
	}
	delete(s.failures, ip)
	delete(s.sessions, sessionToken(r))
	s.sessions[token] = session{CSRF: csrf, ExpiresAt: now.Add(s.config.SessionTTL)}
	s.setCookie(w, token, false)
	s.writeUser(w, csrf)
}

func (s *Server) writeUser(w http.ResponseWriter, csrf string) {
	writeJSON(w, http.StatusOK, map[string]any{"user": map[string]string{"id": "demo-user", "email": s.config.Email}, "csrfToken": csrf})
}

func (s *Server) me(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.prune(s.now())
	value, ok := s.sessions[sessionToken(r)]
	if !ok {
		writeError(w, http.StatusUnauthorized, "UNAUTHENTICATED")
		return
	}
	s.writeUser(w, value.CSRF)
}

func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.prune(s.now())
	token := sessionToken(r)
	value, ok := s.sessions[token]
	if ok && (len(r.Header.Values("X-CSRF-Token")) != 1 || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-CSRF-Token")), []byte(value.CSRF)) != 1) {
		writeError(w, http.StatusForbidden, "CSRF_INVALID")
		return
	}
	delete(s.sessions, token)
	s.setCookie(w, "", true)
	w.WriteHeader(http.StatusNoContent)
}
