package auth

import (
	"context"
	"crypto/subtle"
	"golang.org/x/crypto/argon2"
	"math"
)

type memoryStore struct{ server *Server }

func (m *memoryStore) Ready(context.Context) error { return nil }
func (m *memoryStore) Close()                      {}
func (m *memoryStore) Login(_ context.Context, peer, email, password, oldToken string) (string, Session, error) {
	s := m.server
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.now()
	s.prune(now)
	record := s.failures[peer]
	if record.Count >= s.config.RateLimit {
		retry := int(math.Ceil(record.ExpiresAt.Sub(now).Seconds()))
		if retry < 1 {
			retry = 1
		}
		return "", Session{}, &authFailure{Status: 429, Code: "RATE_LIMITED", Retry: retry}
	}
	derived := argon2.IDKey([]byte(password), s.salt, 3, 64*1024, 4, 32)
	if subtle.ConstantTimeCompare(derived, s.passwordHash) != 1 || email != s.config.Email {
		if record.Count == 0 {
			record.ExpiresAt = now.Add(s.config.RateWindow)
		}
		record.Count++
		s.failures[peer] = record
		return "", Session{}, authError(401, "INVALID_CREDENTIALS")
	}
	token, err := randomToken()
	if err != nil {
		return "", Session{}, err
	}
	csrf, err := randomToken()
	if err != nil {
		return "", Session{}, err
	}
	delete(s.failures, peer)
	delete(s.sessions, oldToken)
	value := Session{CSRF: csrf, ExpiresAt: now.Add(s.config.SessionTTL), User: map[string]string{"id": "demo-user", "email": s.config.Email}}
	s.sessions[token] = value
	return token, value, nil
}
func (m *memoryStore) Current(_ context.Context, token string) (Session, error) {
	s := m.server
	s.mu.Lock()
	defer s.mu.Unlock()
	s.prune(s.now())
	value, ok := s.sessions[token]
	if !ok {
		return Session{}, authError(401, "UNAUTHENTICATED")
	}
	return value, nil
}
func (m *memoryStore) Logout(_ context.Context, token, csrf string) error {
	s := m.server
	s.mu.Lock()
	defer s.mu.Unlock()
	s.prune(s.now())
	value, ok := s.sessions[token]
	if ok && subtle.ConstantTimeCompare([]byte(csrf), []byte(value.CSRF)) != 1 {
		return authError(403, "CSRF_INVALID")
	}
	delete(s.sessions, token)
	return nil
}
