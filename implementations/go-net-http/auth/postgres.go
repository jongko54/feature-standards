package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"math"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/argon2"
)

var phcPattern = regexp.MustCompile(`^\$argon2id\$v=19\$m=65536,t=3,p=4\$([A-Za-z0-9+/]{22})\$([A-Za-z0-9+/]{43})$`)

func verifyPHC(encoded, password string) (bool, error) {
	parts := phcPattern.FindStringSubmatch(encoded)
	if parts == nil {
		return false, storageError()
	}
	salt, err := base64.RawStdEncoding.Strict().DecodeString(parts[1])
	if err != nil || len(salt) != 16 {
		return false, storageError()
	}
	expected, err := base64.RawStdEncoding.Strict().DecodeString(parts[2])
	if err != nil || len(expected) != 32 {
		return false, storageError()
	}
	hash := argon2.IDKey([]byte(password), salt, 3, 65536, 4, 32)
	return subtle.ConstantTimeCompare(hash, expected) == 1, nil
}
func newDummyPHC() (string, error) {
	password := make([]byte, 32)
	if _, err := rand.Read(password); err != nil {
		return "", err
	}
	return newPasswordPHC(string(password))
}
func newPasswordPHC(password string) (string, error) {
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return "", err
	}
	hash := argon2.IDKey([]byte(password), salt, 3, 65536, 4, 32)
	return "$argon2id$v=19$m=65536,t=3,p=4$" + base64.RawStdEncoding.EncodeToString(salt) + "$" + base64.RawStdEncoding.EncodeToString(hash), nil
}
func hashToken(token string) []byte { value := sha256.Sum256([]byte(token)); return value[:] }

type postgresStore struct {
	pool             *pgxpool.Pool
	ttl, window      float64
	limit            int
	dummy            string
	accountLifecycle bool
	passwordHash     func(string) (string, error)
}

func newPostgresStore(config Config) (*postgresStore, error) {
	if !strings.HasPrefix(config.DatabaseURL, "postgresql://") && !strings.HasPrefix(config.DatabaseURL, "postgres://") {
		return nil, storageError()
	}
	parsed, err := pgxpool.ParseConfig(config.DatabaseURL)
	if err != nil {
		return nil, storageError()
	}
	parsed.ConnConfig.ConnectTimeout = 3 * time.Second
	parsed.ConnConfig.RuntimeParams["statement_timeout"] = "10000"
	parsed.ConnConfig.RuntimeParams["lock_timeout"] = "8000"
	parsed.MaxConns = 8
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(ctx, parsed)
	if err != nil {
		return nil, storageError()
	}
	dummy, err := newDummyPHC()
	if err != nil {
		pool.Close()
		return nil, storageError()
	}
	store := &postgresStore{pool: pool, ttl: config.SessionTTL.Seconds(), window: config.RateWindow.Seconds(), limit: config.RateLimit, dummy: dummy, accountLifecycle: config.AccountLifecycle, passwordHash: newPasswordPHC}
	if err := store.Ready(ctx); err != nil {
		pool.Close()
		return nil, storageError()
	}
	return store, nil
}
func (p *postgresStore) Close() { p.pool.Close() }
func (p *postgresStore) Ready(parent context.Context) error {
	ctx, cancel := context.WithTimeout(parent, 5*time.Second)
	defer cancel()
	var count, version int
	wanted := 1
	if p.accountLifecycle {
		wanted = 2
	}
	if err := p.pool.QueryRow(ctx, "SELECT count(*), COALESCE(min(version),0) FROM feature_auth.schema_version").Scan(&count, &version); err != nil || count != 1 || version != wanted {
		return storageError()
	}
	return nil
}
func (p *postgresStore) Login(parent context.Context, peer, email, password, oldToken string) (string, Session, error) {
	ctx, cancel := context.WithTimeout(parent, 12*time.Second)
	defer cancel()
	tx, err := p.pool.Begin(ctx)
	if err != nil {
		return "", Session{}, storageError()
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, "SELECT pg_advisory_xact_lock(20261102, hashtext(host(CAST($1 AS inet))))", peer); err != nil {
		return "", Session{}, storageError()
	}
	var now time.Time
	if err = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&now); err != nil {
		return "", Session{}, storageError()
	}
	if _, err = tx.Exec(ctx, "DELETE FROM feature_auth.login_attempts WHERE peer=CAST($1 AS inet) AND expires_at<=$2", peer, now); err != nil {
		return "", Session{}, storageError()
	}
	var failures int64
	var expires time.Time
	err = tx.QueryRow(ctx, "SELECT failures,expires_at FROM feature_auth.login_attempts WHERE peer=CAST($1 AS inet)", peer).Scan(&failures, &expires)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", Session{}, storageError()
	}
	if failures >= int64(p.limit) {
		retry := int(math.Ceil(expires.Sub(now).Seconds()))
		if retry < 1 {
			retry = 1
		}
		if err = tx.Commit(ctx); err != nil {
			return "", Session{}, storageError()
		}
		return "", Session{}, &authFailure{Status: 429, Code: "RATE_LIMITED", Retry: retry}
	}
	var id, userEmail, encoded string
	var enabled bool
	err = tx.QueryRow(ctx, "SELECT id,email,password_hash,enabled FROM feature_auth.users WHERE email=$1 FOR SHARE", email).Scan(&id, &userEmail, &encoded, &enabled)
	found := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", Session{}, storageError()
	}
	if !found {
		encoded = p.dummy
	}
	matches, err := verifyPHC(encoded, password)
	if err != nil {
		return "", Session{}, err
	}
	if !matches || !found || !enabled {
		if _, err = tx.Exec(ctx, `INSERT INTO feature_auth.login_attempts(peer,failures,expires_at)
    VALUES(CAST($1 AS inet),1,$2::timestamptz + $3 * interval '1 second')
    ON CONFLICT(peer) DO UPDATE SET failures=feature_auth.login_attempts.failures+1`, peer, now, p.window); err != nil {
			return "", Session{}, storageError()
		}
		if err = tx.Commit(ctx); err != nil {
			return "", Session{}, storageError()
		}
		return "", Session{}, authError(401, "INVALID_CREDENTIALS")
	}
	if _, err = tx.Exec(ctx, "DELETE FROM feature_auth.login_attempts WHERE peer=CAST($1 AS inet)", peer); err != nil {
		return "", Session{}, storageError()
	}
	if _, err = tx.Exec(ctx, "DELETE FROM feature_auth.sessions WHERE token_hash=$1", hashToken(oldToken)); err != nil {
		return "", Session{}, storageError()
	}
	token, err := randomToken()
	if err != nil {
		return "", Session{}, err
	}
	csrf, err := randomToken()
	if err != nil {
		return "", Session{}, err
	}
	if err = tx.QueryRow(ctx, `INSERT INTO feature_auth.sessions(token_hash,user_id,csrf_token,created_at,expires_at)
    SELECT $1,$2,$3,t,t+$4 * interval '1 second' FROM (SELECT clock_timestamp() AS t) AS clock
    RETURNING expires_at`, hashToken(token), id, csrf, p.ttl).Scan(&expires); err != nil {
		return "", Session{}, storageError()
	}
	if err = tx.Commit(ctx); err != nil {
		return "", Session{}, storageError()
	}
	return token, Session{CSRF: csrf, ExpiresAt: expires, User: map[string]string{"id": id, "email": userEmail}}, nil
}
func (p *postgresStore) Current(parent context.Context, token string) (Session, error) {
	ctx, cancel := context.WithTimeout(parent, 5*time.Second)
	defer cancel()
	var value Session
	var id, email string
	err := p.pool.QueryRow(ctx, `SELECT s.csrf_token,s.expires_at,u.id,u.email
    FROM feature_auth.sessions s JOIN feature_auth.users u ON u.id=s.user_id
    WHERE s.token_hash=$1 AND s.expires_at>clock_timestamp() AND u.enabled`, hashToken(token)).Scan(&value.CSRF, &value.ExpiresAt, &id, &email)
	if errors.Is(err, pgx.ErrNoRows) {
		return Session{}, authError(401, "UNAUTHENTICATED")
	}
	if err != nil {
		return Session{}, storageError()
	}
	value.User = map[string]string{"id": id, "email": email}
	return value, nil
}
func (p *postgresStore) Logout(parent context.Context, token, csrf string) error {
	ctx, cancel := context.WithTimeout(parent, 12*time.Second)
	defer cancel()
	tx, err := p.pool.Begin(ctx)
	if err != nil {
		return storageError()
	}
	defer tx.Rollback(ctx)
	var expected string
	var expires, now time.Time
	err = tx.QueryRow(ctx, "SELECT csrf_token,expires_at FROM feature_auth.sessions WHERE token_hash=$1 FOR UPDATE", hashToken(token)).Scan(&expected, &expires)
	found := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return storageError()
	}
	if err = tx.QueryRow(ctx, "SELECT clock_timestamp()").Scan(&now); err != nil {
		return storageError()
	}
	if found && expires.After(now) && subtle.ConstantTimeCompare([]byte(csrf), []byte(expected)) != 1 {
		return authError(403, "CSRF_INVALID")
	}
	if _, err = tx.Exec(ctx, "DELETE FROM feature_auth.sessions WHERE token_hash=$1", hashToken(token)); err != nil {
		return storageError()
	}
	if err = tx.Commit(ctx); err != nil {
		return storageError()
	}
	return nil
}
