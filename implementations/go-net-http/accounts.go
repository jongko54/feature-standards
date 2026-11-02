package main

import (
	"context"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"regexp"
	"strings"
	"unicode/utf8"
)

var accountRoutes = map[string]string{
	"/auth/register":                   "register",
	"/auth/email-verification/request": "verify-request",
	"/auth/email-verification/confirm": "verify-confirm",
	"/auth/password-reset/request":     "reset-request",
	"/auth/password-reset/confirm":     "reset-confirm",
}
var accountFields = map[string][]string{
	"register":       {"email", "password"},
	"verify-request": {"email"},
	"verify-confirm": {"token"},
	"reset-request":  {"email"},
	"reset-confirm":  {"token", "password"},
}
var accountToken = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)

// AccountStore is optional; memory and existing auth-only injected stores stay unchanged.
type AccountStore interface {
	Account(context.Context, string, string, string, string, string) error
}

func decodeAccount(action string, body []byte) (map[string]string, bool) {
	expected, supported := accountFields[action]
	if !supported || !utf8.Valid(body) {
		return nil, false
	}
	decoder := json.NewDecoder(strings.NewReader(string(body)))
	start, err := decoder.Token()
	if err != nil || start != json.Delim('{') {
		return nil, false
	}
	values := map[string]string{}
	for decoder.More() {
		keyToken, err := decoder.Token()
		key, valid := keyToken.(string)
		if err != nil || !valid {
			return nil, false
		}
		if _, duplicate := values[key]; duplicate {
			return nil, false
		}
		permitted := false
		for _, name := range expected {
			if key == name {
				permitted = true
			}
		}
		if !permitted {
			return nil, false
		}
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			return nil, false
		}
		value, valid := strictJSONString(raw)
		if !valid {
			return nil, false
		}
		values[key] = value
	}
	end, err := decoder.Token()
	if err != nil || end != json.Delim('}') {
		return nil, false
	}
	if _, err = decoder.Token(); err != io.EOF || len(values) != len(expected) {
		return nil, false
	}
	if email, present := values["email"]; present {
		email = normalizeEmail(email)
		if !validEmail(email) {
			return nil, false
		}
		for _, scalar := range email {
			if scalar <= 32 || scalar == 127 {
				return nil, false
			}
		}
		values["email"] = email
	}
	if password, present := values["password"]; present && (utf8.RuneCountInString(password) < 15 || len(password) > 1024) {
		return nil, false
	}
	if token, present := values["token"]; present && !accountToken.MatchString(token) {
		return nil, false
	}
	return values, true
}

func (s *Server) account(w http.ResponseWriter, r *http.Request, action string) {
	media, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || media != "application/json" {
		writeError(w, 415, "UNSUPPORTED_MEDIA_TYPE")
		return
	}
	if r.ContentLength > 4096 {
		writeError(w, 413, "REQUEST_TOO_LARGE")
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 4097))
	if err != nil {
		writeError(w, 400, "INVALID_REQUEST")
		return
	}
	if len(body) > 4096 {
		writeError(w, 413, "REQUEST_TOO_LARGE")
		return
	}
	values, valid := decodeAccount(action, body)
	if !valid {
		writeError(w, 400, "INVALID_REQUEST")
		return
	}
	store, ok := s.store.(AccountStore)
	if !ok {
		writeAuthError(w, storageError())
		return
	}
	if err := store.Account(r.Context(), action, peerIP(r), values["email"], values["token"], values["password"]); err != nil {
		writeAuthError(w, err)
		return
	}
	if strings.HasSuffix(action, "confirm") {
		w.WriteHeader(204)
		return
	}
	writeJSON(w, 202, map[string]string{"status": "accepted"})
}
