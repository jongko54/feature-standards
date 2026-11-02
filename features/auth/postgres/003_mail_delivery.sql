-- Optional delivery extension. Existing browser-session-v3 schema version remains 2.
BEGIN;
SELECT pg_advisory_xact_lock(20261106,1);
DO $$
BEGIN
    IF (SELECT array_agg(version) FROM feature_auth.schema_version) IS DISTINCT FROM ARRAY[2] THEN
        RAISE EXCEPTION 'SMTP delivery requires account schema 2';
    END IF;
END $$;
CREATE TABLE IF NOT EXISTS feature_auth.mail_delivery_schema_version (
    version integer PRIMARY KEY CHECK (version=1)
);
INSERT INTO feature_auth.mail_delivery_schema_version VALUES(1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS feature_auth.mail_delivery (
    outbox_id bigint PRIMARY KEY REFERENCES feature_auth.mail_outbox(id) ON DELETE CASCADE,
    delivery_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    state text NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending','leased','retry','delivered','failed','cancelled')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    claim_id uuid,
    lease_until timestamptz,
    last_error_code text CHECK (last_error_code IN (
        'SMTP_TEMPORARY','SMTP_PERMANENT','SMTP_AUTH','SMTP_TLS','SMTP_NETWORK',
        'SMTP_UTF8_UNSUPPORTED','INVALID_RECIPIENT','INVALID_MESSAGE','INTERNAL',
        'EXPIRED','SUPERSEDED','DISABLED','ATTEMPTS_EXHAUSTED'
    )),
    CHECK ((state='leased' AND claim_id IS NOT NULL AND lease_until IS NOT NULL)
        OR (state<>'leased' AND claim_id IS NULL AND lease_until IS NULL))
);
CREATE INDEX IF NOT EXISTS mail_delivery_due ON feature_auth.mail_delivery(next_attempt_at)
    WHERE state IN ('pending','retry');
CREATE OR REPLACE FUNCTION feature_auth.mail_delivery_enqueue() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,feature_auth AS $$
BEGIN
    INSERT INTO feature_auth.mail_delivery(outbox_id) VALUES(NEW.id) ON CONFLICT DO NOTHING;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS mail_delivery_enqueue ON feature_auth.mail_outbox;
CREATE TRIGGER mail_delivery_enqueue AFTER INSERT ON feature_auth.mail_outbox
    FOR EACH ROW EXECUTE FUNCTION feature_auth.mail_delivery_enqueue();
INSERT INTO feature_auth.mail_delivery(outbox_id) SELECT id FROM feature_auth.mail_outbox
    ON CONFLICT DO NOTHING;
COMMIT;
