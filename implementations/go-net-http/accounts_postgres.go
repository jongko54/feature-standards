package main

import (
	"context"
	"time"
)

// Account commits the common DB gateway before exposing accepted/token/rate outcomes.
func (p *postgresStore) Account(parent context.Context, action, peer, email, token, password string) error {
	if !p.accountLifecycle {
		return authError(404, "NOT_FOUND")
	}
	ctx, cancel := context.WithTimeout(parent, 12*time.Second)
	defer cancel()
	tx, err := p.pool.Begin(ctx)
	if err != nil {
		return storageError()
	}
	defer tx.Rollback(ctx)
	var outcome int
	if err = tx.QueryRow(ctx, "SELECT feature_auth.account_reserve($1,$2)", action, peer).Scan(&outcome); err != nil || outcome < 0 {
		return storageError()
	}
	if outcome == 0 {
		// The same transaction holds the peer reservation before allocating Argon2 memory.
		encoded := ""
		if password != "" {
			encoded, err = p.passwordHash(password)
			if err != nil {
				return storageError()
			}
		}
		if action == "register" || action == "verify-request" || action == "reset-request" {
			token, err = randomToken()
			if err != nil {
				return storageError()
			}
		}
		if err = tx.QueryRow(ctx, "SELECT feature_auth.account_apply($1,$2,$3,$4,$5)", action, peer, email, token, encoded).Scan(&outcome); err != nil {
			return storageError()
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return storageError()
	}
	if outcome == -1 {
		return authError(400, "INVALID_TOKEN")
	}
	if outcome > 0 {
		return &authFailure{Status: 429, Code: "RATE_LIMITED", Retry: outcome}
	}
	if outcome != 0 {
		return storageError()
	}
	return nil
}
