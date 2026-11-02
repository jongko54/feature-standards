-- Explicit upgrade: schema 1 -> 2. No application runs this migration.
BEGIN;
SELECT pg_advisory_xact_lock(20261106,0);
DO $$
DECLARE current_version integer;
BEGIN
    SELECT version INTO STRICT current_version FROM feature_auth.schema_version;
    IF current_version = 1 THEN
        ALTER TABLE feature_auth.users RENAME COLUMN enabled TO admin_enabled;
        ALTER TABLE feature_auth.users ADD COLUMN email_verified_at timestamptz;
        UPDATE feature_auth.users SET email_verified_at = clock_timestamp();
        ALTER TABLE feature_auth.users ADD COLUMN enabled boolean GENERATED ALWAYS AS
            (admin_enabled AND email_verified_at IS NOT NULL) STORED;
        ALTER TABLE feature_auth.schema_version DROP CONSTRAINT schema_version_version_check;
        UPDATE feature_auth.schema_version SET version=2;
        ALTER TABLE feature_auth.schema_version ADD CONSTRAINT schema_version_version_check CHECK (version=2);
    ELSIF current_version <> 2 THEN
        RAISE EXCEPTION 'Unsupported account schema';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS feature_auth.account_tokens (
    token_hash bytea PRIMARY KEY CHECK (octet_length(token_hash)=32),
    user_id text NOT NULL REFERENCES feature_auth.users(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('verify','reset')),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at>created_at),
    UNIQUE(user_id,kind)
);
CREATE TABLE IF NOT EXISTS feature_auth.mail_outbox (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id text NOT NULL REFERENCES feature_auth.users(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('verify','reset')),
    recipient text NOT NULL,
    token text CHECK (token ~ '^[A-Za-z0-9_-]{43}$'),
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    delivered_at timestamptz
);
CREATE INDEX IF NOT EXISTS mail_pending ON feature_auth.mail_outbox(id) WHERE delivered_at IS NULL;
CREATE TABLE IF NOT EXISTS feature_auth.account_mail_limits (
    user_id text NOT NULL REFERENCES feature_auth.users(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('verify','reset')),
    sent_at timestamptz NOT NULL,
    PRIMARY KEY(user_id,kind)
);
CREATE TABLE IF NOT EXISTS feature_auth.account_attempts (
    peer inet NOT NULL,
    action text NOT NULL,
    hits integer NOT NULL CHECK (hits>0),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY(peer,action)
);

CREATE OR REPLACE FUNCTION feature_auth.account_issue(
    uid text, destination text, purpose text, bearer text, instant timestamptz
) RETURNS void LANGUAGE plpgsql SET search_path=pg_catalog,feature_auth AS $$
DECLARE lifetime interval;
BEGIN
    IF EXISTS(SELECT 1 FROM feature_auth.account_mail_limits
        WHERE user_id=uid AND kind=purpose AND sent_at>instant-interval '60 seconds') THEN
        RETURN;
    END IF;
    lifetime := CASE WHEN purpose='verify' THEN interval '24 hours' ELSE interval '15 minutes' END;
    DELETE FROM feature_auth.account_tokens WHERE user_id=uid AND kind=purpose;
    DELETE FROM feature_auth.mail_outbox WHERE user_id=uid AND kind=purpose AND delivered_at IS NULL;
    INSERT INTO feature_auth.account_tokens(token_hash,user_id,kind,created_at,expires_at)
        VALUES(sha256(convert_to(bearer,'UTF8')),uid,purpose,instant,instant+lifetime);
    INSERT INTO feature_auth.mail_outbox(user_id,kind,recipient,token,created_at,expires_at)
        VALUES(uid,purpose,destination,bearer,instant,instant+lifetime);
    INSERT INTO feature_auth.account_mail_limits(user_id,kind,sent_at) VALUES(uid,purpose,instant)
        ON CONFLICT(user_id,kind) DO UPDATE SET sent_at=EXCLUDED.sent_at;
END $$;

CREATE OR REPLACE FUNCTION feature_auth.account_reserve(operation text,address text
) RETURNS integer LANGUAGE plpgsql SET search_path=pg_catalog,feature_auth AS $$
DECLARE
    instant timestamptz;
    attempt feature_auth.account_attempts%ROWTYPE;
BEGIN
    PERFORM set_config('feature_auth.account_reservation','',true);
    IF operation NOT IN ('register','verify-request','verify-confirm','reset-request','reset-confirm') THEN
        RAISE EXCEPTION 'Invalid account operation' USING ERRCODE='22023';
    END IF;
    PERFORM pg_advisory_xact_lock(20261104,hashtext(operation||':'||host(address::inet)));
    instant := clock_timestamp();
    DELETE FROM feature_auth.account_attempts WHERE peer=address::inet AND action=operation AND expires_at<=instant;
    SELECT * INTO attempt FROM feature_auth.account_attempts WHERE peer=address::inet AND action=operation;
    IF FOUND AND attempt.hits>=10 THEN
        RETURN GREATEST(1,ceil(extract(epoch FROM attempt.expires_at-instant)))::integer;
    END IF;
    INSERT INTO feature_auth.account_attempts(peer,action,hits,expires_at)
        VALUES(address::inet,operation,1,instant+interval '60 seconds')
        ON CONFLICT(peer,action) DO UPDATE SET hits=feature_auth.account_attempts.hits+1;
    PERFORM set_config('feature_auth.account_reservation',operation||':'||host(address::inet),true);
    RETURN 0;
END $$;

CREATE OR REPLACE FUNCTION feature_auth.account_apply(
    operation text, address text, mailbox text, bearer text, phc text
) RETURNS integer LANGUAGE plpgsql SET search_path=pg_catalog,feature_auth AS $$
DECLARE
    instant timestamptz;
    account feature_auth.users%ROWTYPE;
    stored feature_auth.account_tokens%ROWTYPE;
    destination text;
    uid text;
    purpose text;
    digest bytea;
    retry integer;
BEGIN
    IF current_setting('feature_auth.account_reservation',true) IS DISTINCT FROM operation||':'||host(address::inet) THEN
        retry := feature_auth.account_reserve(operation,address);
        IF retry>0 THEN RETURN retry; END IF;
    END IF;
    -- A reservation applies once, only in this connection's current transaction.
    PERFORM set_config('feature_auth.account_reservation','',true);
    purpose := CASE WHEN operation LIKE 'reset-%' THEN 'reset' ELSE 'verify' END;
    IF operation IN ('verify-confirm','reset-confirm') THEN
        digest := sha256(convert_to(bearer,'UTF8'));
        SELECT u.email INTO destination FROM feature_auth.account_tokens t
            JOIN feature_auth.users u ON u.id=t.user_id WHERE t.token_hash=digest AND t.kind=purpose;
        IF NOT FOUND THEN RETURN -1; END IF;
    ELSE
        destination := mailbox;
    END IF;
    PERFORM pg_advisory_xact_lock(20261105,hashtext(destination));
    SELECT * INTO account FROM feature_auth.users WHERE email=destination FOR UPDATE;
    instant := clock_timestamp();
    IF operation='register' THEN
        IF FOUND THEN RETURN 0; END IF;
        uid := gen_random_uuid()::text;
        INSERT INTO feature_auth.users(id,email,password_hash,admin_enabled,email_verified_at)
            VALUES(uid,mailbox,phc,true,NULL);
        PERFORM feature_auth.account_issue(uid,mailbox,'verify',bearer,instant);
        RETURN 0;
    END IF;
    IF operation IN ('verify-request','reset-request') THEN
        IF NOT FOUND OR NOT account.admin_enabled THEN RETURN 0; END IF;
        IF (purpose='verify' AND account.email_verified_at IS NOT NULL)
            OR (purpose='reset' AND account.email_verified_at IS NULL) THEN RETURN 0; END IF;
        PERFORM feature_auth.account_issue(account.id,destination,purpose,bearer,instant);
        RETURN 0;
    END IF;
    IF NOT FOUND OR NOT account.admin_enabled THEN RETURN -1; END IF;
    SELECT * INTO stored FROM feature_auth.account_tokens
        WHERE token_hash=digest AND user_id=account.id AND kind=purpose FOR UPDATE;
    instant := clock_timestamp();
    IF NOT FOUND OR stored.expires_at<=instant THEN RETURN -1; END IF;
    IF purpose='verify' THEN
        IF account.email_verified_at IS NOT NULL THEN RETURN -1; END IF;
        UPDATE feature_auth.users SET email_verified_at=instant WHERE id=account.id;
        DELETE FROM feature_auth.account_tokens WHERE user_id=account.id AND kind='verify';
    ELSE
        IF account.email_verified_at IS NULL THEN RETURN -1; END IF;
        UPDATE feature_auth.users SET password_hash=phc WHERE id=account.id;
        DELETE FROM feature_auth.sessions WHERE user_id=account.id;
        DELETE FROM feature_auth.account_tokens WHERE user_id=account.id AND kind='reset';
    END IF;
    -- Consumed capabilities have no further delivery value.
    UPDATE feature_auth.mail_outbox SET token=NULL WHERE user_id=account.id AND kind=purpose;
    RETURN 0;
END $$;
COMMIT;
