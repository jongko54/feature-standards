use crate::{
    AuthError, AuthStore, Config, LoginInput, LoginSession, SessionUser, StoreFuture, derive,
    random_token,
};
use base64::{Engine, engine::general_purpose::STANDARD_NO_PAD};
use sha2::{Digest, Sha256};
use std::{
    future::Future,
    ops::{Deref, DerefMut},
    sync::Arc,
    time::Duration,
};
use subtle::ConstantTimeEq;
use tokio::{sync::Semaphore, task::JoinHandle};
use tokio_postgres::{Client, Config as PgConfig, NoTls, Row};
use zeroize::Zeroizing;

const IO_TIMEOUT: Duration = Duration::from_secs(10);
const UNAVAILABLE: AuthError = AuthError::StorageUnavailable;

/// Dropping Client alone lets the driver wait indefinitely for outstanding responses.
/// Keep its task in the same request scope, including session setup and cancellation.
struct RequestClient {
    client: Client,
    connection_task: JoinHandle<()>,
}
impl Deref for RequestClient {
    type Target = Client;
    fn deref(&self) -> &Self::Target {
        &self.client
    }
}
impl DerefMut for RequestClient {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.client
    }
}
impl Drop for RequestClient {
    fn drop(&mut self) {
        self.connection_task.abort();
    }
}

/// This build deliberately supports only explicit plaintext loopback test connections.
/// NoTls is never used against a remote host or as a fallback from required TLS.
pub(crate) fn validate_url(value: &str) -> Result<PgConfig, String> {
    let invalid =
        || "AUTH_DATABASE_URL must be a loopback PostgreSQL URI with sslmode=disable".to_string();
    let uri = url::Url::parse(value).map_err(|_| invalid())?;
    if !matches!(uri.scheme(), "postgres" | "postgresql") || uri.fragment().is_some() {
        return Err(invalid());
    }
    let loopback = match uri.host() {
        Some(url::Host::Domain(host)) => {
            host == "localhost"
                || host
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|ip| ip.is_loopback())
        }
        Some(url::Host::Ipv4(ip)) => ip.is_loopback(),
        Some(url::Host::Ipv6(ip)) => ip.is_loopback(),
        None => false,
    };
    let mut ssl = uri.query_pairs().filter(|(key, _)| key == "sslmode");
    if !loopback || ssl.next().is_none_or(|(_, mode)| mode != "disable") || ssl.next().is_some() {
        return Err(invalid());
    }
    // Disallow query host/hostaddr overrides that could bypass the URI host check.
    if uri
        .query_pairs()
        .any(|(key, _)| matches!(key.as_ref(), "host" | "hostaddr" | "sslnegotiation"))
    {
        return Err(invalid());
    }
    let mut config: PgConfig = value.parse().map_err(|_| invalid())?;
    config.connect_timeout(Duration::from_secs(5));
    Ok(config)
}

#[derive(Clone)]
struct StoredHash {
    salt: [u8; 16],
    hash: [u8; 32],
}
fn parse_hash(value: &str) -> Result<StoredHash, AuthError> {
    let parts: Vec<_> = value.split('$').collect();
    if parts.len() != 6 || !parts[0].is_empty() || parts[1] != "argon2id" || parts[2] != "v=19" {
        return Err(UNAVAILABLE);
    }
    let mut params = std::collections::HashMap::new();
    for item in parts[3].split(',') {
        let (key, value) = item.split_once('=').ok_or(UNAVAILABLE)?;
        if params.insert(key, value).is_some() {
            return Err(UNAVAILABLE);
        }
    }
    if params.len() != 3
        || params.get("m") != Some(&"65536")
        || params.get("t") != Some(&"3")
        || params.get("p") != Some(&"4")
    {
        return Err(UNAVAILABLE);
    }
    let salt = STANDARD_NO_PAD.decode(parts[4]).map_err(|_| UNAVAILABLE)?;
    let hash = STANDARD_NO_PAD.decode(parts[5]).map_err(|_| UNAVAILABLE)?;
    if STANDARD_NO_PAD.encode(&salt) != parts[4] || STANDARD_NO_PAD.encode(&hash) != parts[5] {
        return Err(UNAVAILABLE);
    }
    Ok(StoredHash {
        salt: salt.try_into().map_err(|_| UNAVAILABLE)?,
        hash: hash.try_into().map_err(|_| UNAVAILABLE)?,
    })
}
fn token_hash(value: &str) -> Vec<u8> {
    Sha256::digest(value.as_bytes()).to_vec()
}
fn session(row: &Row) -> LoginSession {
    LoginSession {
        user: SessionUser {
            id: row.get("id"),
            email: row.get("email"),
        },
        csrf_token: row.get("csrf_token"),
    }
}

/// Independent request connections permit PostgreSQL to serialize peers across processes.
/// All SQL is confined to this store; no application-start DDL or user seeding occurs.
pub struct PostgresStore {
    config: PgConfig,
    hash_slots: Arc<Semaphore>,
    db_slots: Semaphore,
    dummy: StoredHash,
    ttl: i64,
    window: i64,
    max: i64,
}
impl PostgresStore {
    pub async fn connect(config: &Config) -> Result<Self, String> {
        let pg = validate_url(
            config
                .database_url
                .as_deref()
                .ok_or("AUTH_DATABASE_URL is required")?,
        )?;
        let dummy = tokio::task::spawn_blocking(|| {
            let mut salt = [0; 16];
            getrandom::fill(&mut salt).map_err(|_| UNAVAILABLE)?;
            Ok::<_, AuthError>(StoredHash {
                salt,
                hash: derive(b"unknown-user-dummy-password", &salt).map_err(|_| UNAVAILABLE)?,
            })
        })
        .await
        .map_err(|_| "authentication store unavailable")?
        .map_err(|_| "authentication store unavailable")?;
        let store = Self {
            config: pg,
            hash_slots: Arc::new(Semaphore::new(1)),
            db_slots: Semaphore::new(8),
            dummy,
            ttl: config.session_ttl.as_secs() as i64,
            window: config.rate_window.as_secs() as i64,
            max: i64::try_from(config.rate_max)
                .map_err(|_| "AUTH_RATE_LIMIT_MAX is outside the supported PostgreSQL range")?,
        };
        store
            .ready()
            .await
            .map_err(|_| "authentication store unavailable or schema version mismatch")?;
        Ok(store)
    }
    async fn client(&self) -> Result<RequestClient, AuthError> {
        let (client, connection) = self.config.connect(NoTls).await.map_err(|_| UNAVAILABLE)?;
        let client = RequestClient {
            client,
            connection_task: tokio::spawn(async move {
                let _ = connection.await;
            }),
        };
        // The owner exists before SET so setup failure or cancellation also closes IO.
        client
            .batch_execute("SET statement_timeout = '8s'; SET lock_timeout = '8s'")
            .await
            .map_err(|_| UNAVAILABLE)?;
        Ok(client)
    }
    async fn bounded<T>(
        &self,
        future: impl Future<Output = Result<T, AuthError>>,
    ) -> Result<T, AuthError> {
        let _permit = tokio::time::timeout(IO_TIMEOUT, self.db_slots.acquire())
            .await
            .map_err(|_| UNAVAILABLE)?
            .map_err(|_| UNAVAILABLE)?;
        tokio::time::timeout(IO_TIMEOUT, future)
            .await
            .map_err(|_| UNAVAILABLE)?
    }
    async fn verify(
        &self,
        password: Zeroizing<String>,
        hash: StoredHash,
    ) -> Result<bool, AuthError> {
        let permit = self
            .hash_slots
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| UNAVAILABLE)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let actual =
                Zeroizing::new(derive(password.as_bytes(), &hash.salt).map_err(|_| UNAVAILABLE)?);
            Ok(bool::from(actual.as_ref().ct_eq(hash.hash.as_slice())))
        })
        .await
        .map_err(|_| UNAVAILABLE)?
    }
    async fn login_transaction(
        &self,
        input: LoginInput,
    ) -> Result<(LoginSession, String), AuthError> {
        let mut client = self.client().await?;
        let tx = client.transaction().await.map_err(|_| UNAVAILABLE)?;
        let peer = input.peer.to_string();
        tx.query_one(
            "SELECT pg_advisory_xact_lock(20261102, hashtext(host(CAST($1::text AS inet))))",
            &[&peer],
        )
        .await
        .map_err(|_| UNAVAILABLE)?;
        tx.execute("DELETE FROM feature_auth.login_attempts WHERE peer = $1::text::inet AND expires_at <= clock_timestamp()", &[&peer]).await.map_err(|_| UNAVAILABLE)?;
        if let Some(row) = tx.query_opt("SELECT failures, GREATEST(1, ceil(EXTRACT(EPOCH FROM expires_at-clock_timestamp())))::bigint AS retry FROM feature_auth.login_attempts WHERE peer = $1::text::inet", &[&peer]).await.map_err(|_| UNAVAILABLE)?
            && row.get::<_, i64>("failures") >= self.max {
            return Err(AuthError::RateLimited(row.get::<_, i64>("retry") as u64));
        }
        let user = tx.query_opt("SELECT id, email, password_hash, enabled FROM feature_auth.users WHERE email = $1 FOR SHARE", &[&input.email]).await.map_err(|_| UNAVAILABLE)?;
        let hash = match &user {
            Some(row) => parse_hash(row.get("password_hash"))?,
            None => self.dummy.clone(),
        };
        let valid = self.verify(input.password, hash).await?;
        if !valid
            || user
                .as_ref()
                .is_none_or(|row| !row.get::<_, bool>("enabled"))
        {
            tx.execute("INSERT INTO feature_auth.login_attempts(peer, failures, expires_at) VALUES ($1::text::inet, 1, clock_timestamp() + $2::bigint * interval '1 second') ON CONFLICT (peer) DO UPDATE SET failures = CASE WHEN login_attempts.expires_at > clock_timestamp() THEN login_attempts.failures + 1 ELSE 1 END, expires_at = CASE WHEN login_attempts.expires_at > clock_timestamp() THEN login_attempts.expires_at ELSE clock_timestamp() + $2::bigint * interval '1 second' END", &[&peer, &self.window]).await.map_err(|_| UNAVAILABLE)?;
            tx.commit().await.map_err(|_| UNAVAILABLE)?;
            return Err(AuthError::InvalidCredentials);
        }
        let row = user.ok_or(UNAVAILABLE)?;
        let token = random_token().map_err(|_| UNAVAILABLE)?;
        let csrf = random_token().map_err(|_| UNAVAILABLE)?;
        let user = SessionUser {
            id: row.get("id"),
            email: row.get("email"),
        };
        tx.execute(
            "DELETE FROM feature_auth.login_attempts WHERE peer = $1::text::inet",
            &[&peer],
        )
        .await
        .map_err(|_| UNAVAILABLE)?;
        tx.execute(
            "DELETE FROM feature_auth.sessions WHERE token_hash = $1",
            &[&token_hash(&input.old_token)],
        )
        .await
        .map_err(|_| UNAVAILABLE)?;
        // The CTE reads one fresh DB timestamp after all lock waits and password work.
        tx.execute("WITH now AS (SELECT clock_timestamp() AS time) INSERT INTO feature_auth.sessions(token_hash, user_id, csrf_token, created_at, expires_at) SELECT $1, $2, $3, time, time + $4::bigint * interval '1 second' FROM now", &[&token_hash(&token), &user.id, &csrf, &self.ttl]).await.map_err(|_| UNAVAILABLE)?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        Ok((
            LoginSession {
                user,
                csrf_token: csrf,
            },
            token,
        ))
    }
}
impl AuthStore for PostgresStore {
    fn profile(&self) -> &'static str {
        "browser-session-v2"
    }
    fn ready(&self) -> StoreFuture<'_, ()> {
        Box::pin(self.bounded(async {
            let client = self.client().await?;
            let row = client.query_one("SELECT count(*)::bigint AS count, min(version) AS minimum, max(version) AS maximum FROM feature_auth.schema_version", &[]).await.map_err(|_| UNAVAILABLE)?;
            if row.get::<_, i64>("count") != 1 || row.get::<_, Option<i32>>("minimum") != Some(1) || row.get::<_, Option<i32>>("maximum") != Some(1) { return Err(UNAVAILABLE); }
            Ok(())
        }))
    }
    fn login(&self, input: LoginInput) -> StoreFuture<'_, (LoginSession, String)> {
        Box::pin(self.bounded(self.login_transaction(input)))
    }
    fn me(&self, token: String) -> StoreFuture<'_, LoginSession> {
        Box::pin(self.bounded(async move {
            let client = self.client().await?;
            let row = client.query_opt("SELECT u.id, u.email, s.csrf_token FROM feature_auth.sessions s JOIN feature_auth.users u ON u.id=s.user_id WHERE s.token_hash=$1 AND s.expires_at>clock_timestamp() AND u.enabled", &[&token_hash(&token)]).await.map_err(|_| UNAVAILABLE)?;
            row.map(|row| session(&row)).ok_or(AuthError::Unauthenticated)
        }))
    }
    fn logout(&self, token: String, csrf: Option<String>) -> StoreFuture<'_, ()> {
        Box::pin(self.bounded(async move {
            let mut client = self.client().await?;
            let tx = client.transaction().await.map_err(|_| UNAVAILABLE)?;
            let hash = token_hash(&token);
            let row = tx.query_opt("SELECT csrf_token, expires_at FROM feature_auth.sessions WHERE token_hash=$1 FOR UPDATE", &[&hash]).await.map_err(|_| UNAVAILABLE)?;
            if let Some(row) = row {
                // Read DB time after acquiring the session row lock.
                let active = tx.query_one("SELECT $1::timestamptz > clock_timestamp() AS active", &[&row.get::<_, std::time::SystemTime>("expires_at")]).await.map_err(|_| UNAVAILABLE)?.get::<_, bool>("active");
                let expected: String = row.get("csrf_token");
                if active && !bool::from(csrf.as_deref().unwrap_or("").as_bytes().ct_eq(expected.as_bytes())) { return Err(AuthError::CsrfInvalid); }
                tx.execute("DELETE FROM feature_auth.sessions WHERE token_hash=$1", &[&hash]).await.map_err(|_| UNAVAILABLE)?;
            }
            tx.commit().await.map_err(|_| UNAVAILABLE)?;
            Ok(())
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn phc_contract_rejects_unsupported_costs_and_noncanonical_base64() {
        let salt = STANDARD_NO_PAD.encode([7; 16]);
        let hash = STANDARD_NO_PAD.encode([8; 32]);
        let valid = format!("$argon2id$v=19$m=65536,t=3,p=4${salt}${hash}");
        assert!(parse_hash(&valid).is_ok());
        for invalid in [
            valid.replace("argon2id", "argon2i"),
            valid.replace("v=19", "v=16"),
            valid.replace("m=65536", "m=8"),
            valid.replace("t=3", "t=2"),
            valid.replace("p=4", "p=1"),
            format!("{valid}="),
            valid.replace(&salt, "YWJj"),
            valid.replace("t=3", "t=3,t=3"),
        ] {
            assert!(parse_hash(&invalid).is_err());
        }
    }
    #[test]
    fn url_rejects_remote_plaintext_and_tls_downgrade() {
        for uri in [
            "postgresql://db.example.com/test?sslmode=disable",
            "postgresql://localhost/test",
            "postgresql://localhost/test?sslmode=require",
            "postgresql://localhost/test?sslmode=disable&host=evil.example",
            "postgresql://localhost/test?sslmode=disable&sslmode=require",
        ] {
            assert!(validate_url(uri).is_err());
        }
        for uri in [
            "postgresql://localhost/test?sslmode=disable",
            "postgresql://127.0.0.1:51105/test?sslmode=disable",
            "postgresql://[::1]/test?sslmode=disable",
        ] {
            assert!(validate_url(uri).is_ok());
        }
    }
    #[test]
    fn session_hash_is_sha256_of_utf8_cookie() {
        assert_eq!(
            token_hash("abc"),
            vec![
                0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40, 0xde, 0x5d, 0xae,
                0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61,
                0xf2, 0x00, 0x15, 0xad
            ]
        );
    }
}

#[cfg(test)]
#[path = "postgres_connection_tests.rs"]
mod connection_tests;
