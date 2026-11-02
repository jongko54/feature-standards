use crate::{
    AccountInput, AuthError, AuthStore, Config, LoginInput, LoginSession, SessionUser, StoreFuture,
    derive, random_token,
};
use base64::{Engine, engine::general_purpose::STANDARD_NO_PAD};
use native_tls::{Certificate, TlsConnector};
use postgres_native_tls::MakeTlsConnector;
use sha2::{Digest, Sha256};
use std::{
    future::Future,
    ops::{Deref, DerefMut},
    path::PathBuf,
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
impl RequestClient {
    fn new(
        client: Client,
        connection: impl Future<Output = Result<(), tokio_postgres::Error>> + Send + 'static,
    ) -> Self {
        Self {
            client,
            connection_task: tokio::spawn(async move {
                let _ = connection.await;
            }),
        }
    }
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

struct DatabaseOptions {
    config: PgConfig,
    verified_tls: bool,
    root_certificate: Option<PathBuf>,
}

/// Enforce the public URI policy before adapting it to tokio-postgres's TLS modes.
/// The native TLS connector keeps both certificate and hostname checks enabled.
fn database_options(value: &str) -> Result<DatabaseOptions, String> {
    let invalid = || {
        "AUTH_DATABASE_URL requires sslmode=verify-full, or explicit loopback sslmode=disable"
            .to_string()
    };
    let mut uri = url::Url::parse(value).map_err(|_| invalid())?;
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
    let mut options = std::collections::HashMap::new();
    for (key, value) in uri.query_pairs() {
        if matches!(
            key.as_ref(),
            "host" | "hostaddr" | "port" | "sslnegotiation"
        ) || key.starts_with("ssl") && !matches!(key.as_ref(), "sslmode" | "sslrootcert")
            || options
                .insert(key.into_owned(), value.into_owned())
                .is_some()
        {
            return Err(invalid());
        }
    }
    let verified_tls = match options.get("sslmode").map(String::as_str) {
        Some("verify-full") => true,
        Some("disable") if loopback => false,
        _ => return Err(invalid()),
    };
    let root_certificate = options.get("sslrootcert").map(PathBuf::from);
    if root_certificate
        .as_ref()
        .is_some_and(|path| path.as_os_str().is_empty())
        || !verified_tls && root_certificate.is_some()
    {
        return Err(invalid());
    }
    // tokio-postgres itself supports disable/prefer/require, but no verify-full or
    // sslrootcert. Only the connector may perform verification; Require forbids fallback.
    uri.query_pairs_mut()
        .clear()
        .extend_pairs(
            options
                .iter()
                .filter(|(key, _)| !matches!(key.as_str(), "sslmode" | "sslrootcert")),
        )
        .append_pair("sslmode", if verified_tls { "require" } else { "disable" });
    let mut config: PgConfig = uri.as_str().parse().map_err(|_| invalid())?;
    if config.get_hosts().len() != 1 || !config.get_hostaddrs().is_empty() {
        return Err(invalid());
    }
    config.connect_timeout(Duration::from_secs(5));
    Ok(DatabaseOptions {
        config,
        verified_tls,
        root_certificate,
    })
}

pub(crate) fn validate_url(value: &str) -> Result<PgConfig, String> {
    database_options(value).map(|options| options.config)
}

fn tls_connector(options: &DatabaseOptions) -> Result<Option<TlsConnector>, String> {
    if !options.verified_tls {
        return Ok(None);
    }
    let unavailable = || "authentication TLS trust configuration unavailable".to_string();
    let mut builder = TlsConnector::builder();
    builder.min_protocol_version(Some(native_tls::Protocol::Tlsv12));
    if let Some(path) = &options.root_certificate {
        let pem = std::fs::read(path).map_err(|_| unavailable())?;
        let certificate = Certificate::from_pem(&pem).map_err(|_| unavailable())?;
        builder
            .disable_built_in_roots(true)
            .add_root_certificate(certificate);
    }
    builder.build().map(Some).map_err(|_| unavailable())
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
    tls: Option<TlsConnector>,
    account_lifecycle: bool,
    hash_slots: Arc<Semaphore>,
    db_slots: Semaphore,
    dummy: StoredHash,
    ttl: i64,
    window: i64,
    max: i64,
}
impl PostgresStore {
    pub async fn connect(config: &Config) -> Result<Self, String> {
        let options = database_options(
            config
                .database_url
                .as_deref()
                .ok_or("AUTH_DATABASE_URL is required")?,
        )?;
        let tls = tls_connector(&options)?;
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
            config: options.config,
            tls,
            account_lifecycle: config.account_lifecycle,
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
        let client = if let Some(tls) = &self.tls {
            let (client, connection) = self
                .config
                .connect(MakeTlsConnector::new(tls.clone()))
                .await
                .map_err(|_| UNAVAILABLE)?;
            RequestClient::new(client, connection)
        } else {
            let (client, connection) = self.config.connect(NoTls).await.map_err(|_| UNAVAILABLE)?;
            RequestClient::new(client, connection)
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
    async fn hash_password(&self, password: Zeroizing<String>) -> Result<String, AuthError> {
        let permit = self
            .hash_slots
            .clone()
            .acquire_owned()
            .await
            .map_err(|_| UNAVAILABLE)?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let mut salt = [0; 16];
            getrandom::fill(&mut salt).map_err(|_| UNAVAILABLE)?;
            let hash = Zeroizing::new(derive(password.as_bytes(), &salt).map_err(|_| UNAVAILABLE)?);
            Ok(format!(
                "$argon2id$v=19$m=65536,t=3,p=4${}${}",
                STANDARD_NO_PAD.encode(salt),
                STANDARD_NO_PAD.encode(hash.as_ref())
            ))
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
        if self.account_lifecycle {
            "browser-session-v3"
        } else {
            "browser-session-v2"
        }
    }
    fn ready(&self) -> StoreFuture<'_, ()> {
        Box::pin(self.bounded(async {
            let client = self.client().await?;
            let row = client.query_one("SELECT count(*)::bigint AS count, min(version) AS minimum, max(version) AS maximum FROM feature_auth.schema_version", &[]).await.map_err(|_| UNAVAILABLE)?;
            let expected = if self.account_lifecycle { 2 } else { 1 };
            if row.get::<_, i64>("count") != 1 || row.get::<_, Option<i32>>("minimum") != Some(expected) || row.get::<_, Option<i32>>("maximum") != Some(expected) { return Err(UNAVAILABLE); }
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
    fn account(&self, input: AccountInput) -> StoreFuture<'_, ()> {
        Box::pin(self.bounded(async move {
            if !self.account_lifecycle {
                return Err(AuthError::Internal);
            }
            let mut client = self.client().await?;
            let tx = client.transaction().await.map_err(|_| UNAVAILABLE)?;
            let peer = input.peer.to_string();
            let retry: i32 = tx
                .query_one(
                    "SELECT feature_auth.account_reserve($1,$2)",
                    &[&input.action.as_str(), &peer],
                )
                .await
                .map_err(|_| UNAVAILABLE)?
                .try_get(0)
                .map_err(|_| UNAVAILABLE)?;
            if retry < 0 {
                return Err(UNAVAILABLE);
            }
            if retry > 0 {
                tx.commit().await.map_err(|_| UNAVAILABLE)?;
                return Err(AuthError::RateLimited(retry as u64));
            }
            // Keep the reservation and advisory lock in this same transaction.
            // Rejected requests never enqueue Argon2 work or generate a capability.
            let hash = if input.action.requires_password() {
                self.hash_password(input.password).await?
            } else {
                String::new()
            };
            let token = if input.action.confirms() {
                input.token
            } else {
                random_token().map_err(|_| UNAVAILABLE)?
            };
            let code: i32 = tx
                .query_one(
                    "SELECT feature_auth.account_apply($1,$2,$3,$4,$5)",
                    &[&input.action.as_str(), &peer, &input.email, &token, &hash],
                )
                .await
                .map_err(|_| UNAVAILABLE)?
                .try_get(0)
                .map_err(|_| UNAVAILABLE)?;
            if code < -1 {
                return Err(UNAVAILABLE);
            }
            // Rejected tokens and rate-limit counters are committed too.
            tx.commit().await.map_err(|_| UNAVAILABLE)?;
            match code {
                0 => Ok(()),
                -1 => Err(AuthError::InvalidToken),
                seconds => Err(AuthError::RateLimited(seconds as u64)),
            }
        }))
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    pub(crate) async fn assert_limited_accounts_skip_busy_hasher(uri: &str) {
        let settings = crate::tests::config(&[
            ("AUTH_STORE", "postgres"),
            ("AUTH_DATABASE_URL", uri),
            ("AUTH_ACCOUNT_LIFECYCLE", "true"),
        ])
        .unwrap();
        let store = PostgresStore::connect(&settings).await.unwrap();
        let client = store.client().await.unwrap();
        for action in [
            crate::AccountAction::Register,
            crate::AccountAction::ResetConfirm,
        ] {
            client.execute(
                "INSERT INTO feature_auth.account_attempts(peer,action,hits,expires_at) VALUES ('127.0.0.88',$1,10,clock_timestamp()+interval '60 seconds') ON CONFLICT(peer,action) DO UPDATE SET hits=10,expires_at=EXCLUDED.expires_at",
                &[&action.as_str()],
            ).await.unwrap();
        }
        // An existing password job occupies the sole hash slot. Already-limited
        // requests must still complete, proving they never enter the hash queue.
        let busy_hasher = store.hash_slots.clone().acquire_owned().await.unwrap();
        for action in [
            crate::AccountAction::Register,
            crate::AccountAction::ResetConfirm,
        ] {
            let result = tokio::time::timeout(
                Duration::from_secs(2),
                store.account(crate::AccountInput {
                    action,
                    peer: "127.0.0.88".parse().unwrap(),
                    email: "over-limit@example.com".into(),
                    token: "A".repeat(43),
                    password: Zeroizing::new("valid-overlimit-password".into()),
                }),
            )
            .await
            .expect("rate-limited request waited for busy password hashing");
            assert!(matches!(result, Err(AuthError::RateLimited(seconds)) if seconds > 0));
            assert_eq!(client.query_one(
                "SELECT hits FROM feature_auth.account_attempts WHERE peer='127.0.0.88' AND action=$1",
                &[&action.as_str()],
            ).await.unwrap().get::<_,i32>(0), 10);
        }
        drop(busy_hasher);
        assert_eq!(
            client
                .query_one(
                    "SELECT count(*) FROM feature_auth.users WHERE email='over-limit@example.com'",
                    &[]
                )
                .await
                .unwrap()
                .get::<_, i64>(0),
            0
        );
    }
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
    fn url_accepts_verified_tls_without_weakening_plaintext_policy() {
        for uri in [
            "postgresql://db.example.com/test?sslmode=verify-full",
            "postgresql://localhost/test?sslmode=verify-full&sslrootcert=%2Ftmp%2Froot.pem",
            "postgresql://127.0.0.1:5432/test?sslmode=verify-full",
        ] {
            assert!(validate_url(uri).is_ok(), "verified TLS URI was rejected");
        }
        for uri in [
            "postgresql://db.example.com/test?sslmode=require",
            "postgresql://db.example.com/test?sslmode=prefer",
            "postgresql://db.example.com/test?sslmode=verify-ca",
            "postgresql://db.example.com/test?sslmode=verify-full&host=localhost",
            "postgresql://db.example.com/test?sslmode=verify-full&hostaddr=127.0.0.1",
            "postgresql://db.example.com/test?sslmode=verify-full&sslnegotiation=direct",
            "postgresql://db.example.com/test?sslmode=verify-full&sslmode=disable",
            "postgresql://localhost/test?sslmode=disable&sslrootcert=%2Ftmp%2Froot.pem",
        ] {
            assert!(validate_url(uri).is_err(), "unsafe TLS URI was accepted");
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

#[cfg(test)]
#[path = "postgres_tls_tests.rs"]
mod tls_tests;
