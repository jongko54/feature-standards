BEGIN;
CREATE SCHEMA IF NOT EXISTS feature_auth;
CREATE TABLE IF NOT EXISTS feature_auth.schema_version (
    version integer PRIMARY KEY CHECK (version = 1)
);
INSERT INTO feature_auth.schema_version(version) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS feature_auth.users (
    id text PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
    email text COLLATE "C" NOT NULL UNIQUE CHECK (octet_length(email) BETWEEN 1 AND 254 AND position('@' IN email) > 0),
    password_hash text NOT NULL,
    enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS feature_auth.sessions (
    token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    user_id text NOT NULL REFERENCES feature_auth.users(id) ON DELETE CASCADE,
    csrf_token text NOT NULL CHECK (csrf_token ~ '^[A-Za-z0-9_-]{43}$'),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS sessions_expires_at ON feature_auth.sessions(expires_at);
CREATE INDEX IF NOT EXISTS sessions_user_id ON feature_auth.sessions(user_id);
CREATE TABLE IF NOT EXISTS feature_auth.login_attempts (
    peer inet PRIMARY KEY,
    failures bigint NOT NULL CHECK (failures > 0),
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_expires_at ON feature_auth.login_attempts(expires_at);
COMMIT;
