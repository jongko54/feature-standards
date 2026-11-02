package auth

// UnauthenticatedError reports a missing, expired, or revoked session (401).
// External AuthStore adapters can wrap this error without exposing diagnostics.
func UnauthenticatedError() error { return authError(401, "UNAUTHENTICATED") }

// InvalidCredentialsError reports a rejected login without revealing whether a
// user exists (401). Do not include account or password details in HTTP errors.
func InvalidCredentialsError() error { return authError(401, "INVALID_CREDENTIALS") }

// CSRFInvalidError reports a session's missing or incorrect logout CSRF (403).
func CSRFInvalidError() error { return authError(403, "CSRF_INVALID") }

// InvalidTokenError reports a rejected verification/reset token (400) from an
// external AccountStore without disclosing its value or rejection reason.
func InvalidTokenError() error { return authError(400, "INVALID_TOKEN") }

// StorageUnavailableError reports a storage operation that could not complete
// safely (503). It never represents success or permits a memory fallback.
func StorageUnavailableError() error { return storageError() }

// RateLimitedError reports a peer's exhausted request budget (429). The retry
// delay is a whole number of seconds and is clamped to at least one second.
func RateLimitedError(retryAfterSeconds int) error {
	if retryAfterSeconds < 1 {
		retryAfterSeconds = 1
	}
	return &authFailure{Status: 429, Code: "RATE_LIMITED", Retry: retryAfterSeconds}
}
