use crate::{
    AuthError, AuthStore, Clock, Config, LoginInput, LoginSession, SessionUser, StoreFuture,
    derive, random_token,
};
use std::{
    collections::HashMap,
    net::IpAddr,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use subtle::ConstantTimeEq;
use tokio::sync::Semaphore;
use zeroize::Zeroizing;

#[derive(Clone)]
struct Session {
    csrf: String,
    expires: Instant,
}
struct Failure {
    count: u64,
    expires: Instant,
}
#[derive(Default)]
struct Data {
    sessions: HashMap<String, Session>,
    failures: HashMap<IpAddr, Failure>,
}
impl Data {
    fn prune(&mut self, now: Instant) {
        self.sessions.retain(|_, value| now < value.expires);
        self.failures.retain(|_, value| now < value.expires);
    }
}
struct Inner {
    email: String,
    salt: [u8; 16],
    password_hash: [u8; 32],
    data: Mutex<Data>,
    hash_slots: Arc<Semaphore>,
    clock: Clock,
    ttl: Duration,
    window: Duration,
    max: u64,
}
/// The default v1 store is process-local and has an injectable monotonic clock in tests.
pub struct MemoryStore {
    inner: Arc<Inner>,
}
impl MemoryStore {
    pub async fn new(config: &mut Config) -> Result<Self, String> {
        Self::with_clock(config, Arc::new(Instant::now)).await
    }
    pub(crate) async fn with_clock(config: &mut Config, clock: Clock) -> Result<Self, String> {
        let mut salt = [0; 16];
        getrandom::fill(&mut salt).map_err(|_| "system random generator unavailable")?;
        let password = Zeroizing::new(std::mem::take(&mut config.password));
        let password_hash = tokio::task::spawn_blocking(move || derive(password.as_bytes(), &salt))
            .await
            .map_err(|_| "password hashing task failed")?
            .map_err(|_| "password hashing failed")?;
        Ok(Self {
            inner: Arc::new(Inner {
                email: config.email.clone(),
                salt,
                password_hash,
                data: Mutex::new(Data::default()),
                hash_slots: Arc::new(Semaphore::new(1)),
                clock,
                ttl: config.session_ttl,
                window: config.rate_window,
                max: config.rate_max,
            }),
        })
    }
}
impl Inner {
    fn session(&self, csrf: String) -> LoginSession {
        LoginSession {
            user: SessionUser {
                id: "demo-user".into(),
                email: self.email.clone(),
            },
            csrf_token: csrf,
        }
    }
    fn login(&self, input: LoginInput) -> Result<(LoginSession, String), AuthError> {
        let now = (self.clock)();
        {
            let mut data = self.data.lock().map_err(|_| AuthError::Internal)?;
            data.prune(now);
            if let Some(failure) = data
                .failures
                .get(&input.peer)
                .filter(|f| f.count >= self.max)
            {
                let retry = failure
                    .expires
                    .saturating_duration_since(now)
                    .as_secs()
                    .saturating_add(1);
                return Err(AuthError::RateLimited(retry));
            }
        }
        let derived = Zeroizing::new(
            derive(input.password.as_bytes(), &self.salt).map_err(|_| AuthError::Internal)?,
        );
        let password_valid = bool::from(derived.as_ref().ct_eq(self.password_hash.as_slice()));
        let now = (self.clock)();
        let mut data = self.data.lock().map_err(|_| AuthError::Internal)?;
        data.prune(now);
        if !password_valid || input.email != self.email {
            let failure = data.failures.entry(input.peer).or_insert(Failure {
                count: 0,
                expires: now + self.window,
            });
            failure.count = failure.count.saturating_add(1);
            return Err(AuthError::InvalidCredentials);
        }
        let token = random_token().map_err(|_| AuthError::Internal)?;
        let csrf = random_token().map_err(|_| AuthError::Internal)?;
        data.failures.remove(&input.peer);
        data.sessions.remove(&input.old_token);
        data.sessions.insert(
            token.clone(),
            Session {
                csrf: csrf.clone(),
                expires: now + self.ttl,
            },
        );
        Ok((self.session(csrf), token))
    }
}
impl AuthStore for MemoryStore {
    fn profile(&self) -> &'static str {
        "browser-session-v1"
    }
    fn ready(&self) -> StoreFuture<'_, ()> {
        Box::pin(async { Ok(()) })
    }
    fn login(&self, input: LoginInput) -> StoreFuture<'_, (LoginSession, String)> {
        let inner = self.inner.clone();
        Box::pin(async move {
            let permit = inner
                .hash_slots
                .clone()
                .acquire_owned()
                .await
                .map_err(|_| AuthError::Internal)?;
            tokio::task::spawn_blocking(move || {
                let _permit = permit;
                inner.login(input)
            })
            .await
            .map_err(|_| AuthError::Internal)?
        })
    }
    fn me(&self, token: String) -> StoreFuture<'_, LoginSession> {
        Box::pin(async move {
            let mut data = self.inner.data.lock().map_err(|_| AuthError::Internal)?;
            data.prune((self.inner.clock)());
            data.sessions
                .get(&token)
                .map(|s| self.inner.session(s.csrf.clone()))
                .ok_or(AuthError::Unauthenticated)
        })
    }
    fn logout(&self, token: String, csrf: Option<String>) -> StoreFuture<'_, ()> {
        Box::pin(async move {
            let mut data = self.inner.data.lock().map_err(|_| AuthError::Internal)?;
            data.prune((self.inner.clock)());
            if let Some(session) = data.sessions.get(&token)
                && !bool::from(
                    csrf.as_deref()
                        .unwrap_or("")
                        .as_bytes()
                        .ct_eq(session.csrf.as_bytes()),
                )
            {
                return Err(AuthError::CsrfInvalid);
            }
            data.sessions.remove(&token);
            Ok(())
        })
    }
}
