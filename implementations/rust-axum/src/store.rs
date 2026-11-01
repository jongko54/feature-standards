use serde::Serialize;
use std::{future::Future, net::IpAddr, pin::Pin, sync::Arc};
use zeroize::Zeroizing;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AuthError {
    InvalidCredentials,
    Unauthenticated,
    CsrfInvalid,
    RateLimited(u64),
    StorageUnavailable,
    Internal,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct SessionUser {
    pub id: String,
    pub email: String,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct LoginSession {
    pub user: SessionUser,
    #[serde(rename = "csrfToken")]
    pub csrf_token: String,
}

pub struct LoginInput {
    pub peer: IpAddr,
    pub email: String,
    pub password: Zeroizing<String>,
    pub old_token: String,
}

pub type StoreFuture<'a, T> = Pin<Box<dyn Future<Output = Result<T, AuthError>> + Send + 'a>>;

/// Store operations own atomicity. A successful login/logout is fully committed.
pub trait AuthStore: Send + Sync {
    fn profile(&self) -> &'static str;
    fn ready(&self) -> StoreFuture<'_, ()>;
    fn login(&self, input: LoginInput) -> StoreFuture<'_, (LoginSession, String)>;
    fn me(&self, token: String) -> StoreFuture<'_, LoginSession>;
    fn logout(&self, token: String, csrf: Option<String>) -> StoreFuture<'_, ()>;
}

#[derive(Clone)]
pub struct AuthService {
    store: Arc<dyn AuthStore>,
}

impl AuthService {
    pub fn new(store: Arc<dyn AuthStore>) -> Self {
        Self { store }
    }
    pub fn profile(&self) -> &'static str {
        self.store.profile()
    }
    pub async fn ready(&self) -> Result<(), AuthError> {
        self.store.ready().await
    }
    pub async fn login(&self, input: LoginInput) -> Result<(LoginSession, String), AuthError> {
        self.store.login(input).await
    }
    pub async fn me(&self, token: String) -> Result<LoginSession, AuthError> {
        self.store.me(token).await
    }
    pub async fn logout(&self, token: String, csrf: Option<String>) -> Result<(), AuthError> {
        self.store.logout(token, csrf).await
    }
}
