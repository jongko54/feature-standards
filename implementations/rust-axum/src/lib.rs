use argon2::{Algorithm, Argon2, Params, Version};
use axum::body::to_bytes;
use axum::extract::{ConnectInfo, Request, State};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::{Json, Router};
use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use serde::Deserialize;
use serde_json::json;
use std::collections::HashMap;
use std::error::Error;
use std::net::{IpAddr, SocketAddr};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use subtle::ConstantTimeEq;
use tokio::sync::Semaphore;
use zeroize::Zeroizing;

const BODY_LIMIT: usize = 4096;
const CONFIG_KEYS: &[&str] = &[
    "AUTH_HOST",
    "AUTH_PORT",
    "AUTH_DEMO",
    "AUTH_USER_EMAIL",
    "AUTH_USER_PASSWORD",
    "AUTH_ALLOWED_ORIGIN",
    "AUTH_COOKIE_SECURE",
    "AUTH_SESSION_TTL_SECONDS",
    "AUTH_RATE_LIMIT_MAX",
    "AUTH_RATE_LIMIT_WINDOW_SECONDS",
];

pub struct Config {
    pub host: String,
    pub port: u16,
    email: String,
    password: String,
    origin: String,
    secure: bool,
    session_ttl: Duration,
    rate_window: Duration,
    rate_max: u64,
}

impl Config {
    pub fn from_env() -> Result<Self, String> {
        let mut values = HashMap::new();
        for key in CONFIG_KEYS {
            match std::env::var(key) {
                Ok(value) => {
                    values.insert(*key, value);
                }
                Err(std::env::VarError::NotPresent) => {}
                Err(std::env::VarError::NotUnicode(_)) => {
                    return Err(format!("{key} must be UTF-8"));
                }
            }
        }
        Self::from_lookup(|key| values.remove(key))
    }

    pub fn from_lookup(mut lookup: impl FnMut(&str) -> Option<String>) -> Result<Self, String> {
        let host = lookup("AUTH_HOST").unwrap_or_else(|| "127.0.0.1".into());
        if host.is_empty() || host.trim() != host || host.contains(['/', '\\', '@', '#', '?']) {
            return Err("AUTH_HOST must be a non-empty bind hostname or IP address".into());
        }
        let port = positive(lookup("AUTH_PORT"), 8000, "AUTH_PORT")?;
        let port = u16::try_from(port).map_err(|_| "AUTH_PORT must be between 1 and 65535")?;
        let demo = boolean(lookup("AUTH_DEMO"), false, "AUTH_DEMO")?;
        let secure = boolean(lookup("AUTH_COOKIE_SECURE"), true, "AUTH_COOKIE_SECURE")?;
        let origin =
            lookup("AUTH_ALLOWED_ORIGIN").unwrap_or_else(|| "http://127.0.0.1:5173".into());
        let origin_url = exact_origin(&origin)?;
        let loopback = match origin_url.host() {
            Some(url::Host::Domain(host)) => host == "localhost",
            Some(url::Host::Ipv4(ip)) => ip.is_loopback(),
            Some(url::Host::Ipv6(ip)) => ip.is_loopback(),
            None => false,
        };
        if !secure && (!demo || !loopback) {
            return Err("AUTH_COOKIE_SECURE=false requires an explicit loopback demo".into());
        }
        if !demo && origin_url.scheme() != "https" {
            return Err("non-demo mode requires an HTTPS origin".into());
        }
        let (email, password) = if demo {
            (
                "demo@example.com".into(),
                "correct-horse-battery-staple".into(),
            )
        } else {
            (
                normalize_email(&lookup("AUTH_USER_EMAIL").unwrap_or_default()),
                lookup("AUTH_USER_PASSWORD").unwrap_or_default(),
            )
        };
        if !valid_email(&email) || password.is_empty() || password.len() > 1024 {
            return Err(
                "valid AUTH_USER_EMAIL and AUTH_USER_PASSWORD are required outside demo mode"
                    .into(),
            );
        }
        let session_ttl = duration(
            lookup("AUTH_SESSION_TTL_SECONDS"),
            1800,
            "AUTH_SESSION_TTL_SECONDS",
        )?;
        let rate_window = duration(
            lookup("AUTH_RATE_LIMIT_WINDOW_SECONDS"),
            60,
            "AUTH_RATE_LIMIT_WINDOW_SECONDS",
        )?;
        let rate_max = positive(lookup("AUTH_RATE_LIMIT_MAX"), 5, "AUTH_RATE_LIMIT_MAX")?;
        Ok(Self {
            host,
            port,
            email,
            password,
            origin,
            secure,
            session_ttl,
            rate_window,
            rate_max,
        })
    }
}

fn boolean(value: Option<String>, default: bool, name: &str) -> Result<bool, String> {
    match value.as_deref() {
        None => Ok(default),
        Some("true") => Ok(true),
        Some("false") => Ok(false),
        _ => Err(format!("{name} must be true or false")),
    }
}

fn positive(value: Option<String>, default: u64, name: &str) -> Result<u64, String> {
    let Some(value) = value else {
        return Ok(default);
    };
    if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
        return Err(format!("{name} must be a positive integer"));
    }
    value
        .parse::<u64>()
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| format!("{name} must be a positive integer"))
}

fn duration(value: Option<String>, default: u64, name: &str) -> Result<Duration, String> {
    let seconds = positive(value, default, name)?;
    if seconds > i64::MAX as u64 / 1_000_000_000
        || Instant::now()
            .checked_add(Duration::from_secs(seconds))
            .is_none()
    {
        return Err(format!("{name} is outside the supported duration range"));
    }
    Ok(Duration::from_secs(seconds))
}

fn exact_origin(value: &str) -> Result<url::Url, String> {
    let invalid = || {
        "AUTH_ALLOWED_ORIGIN must be one exact HTTP(S) origin without path, credentials, query or fragment".to_owned()
    };
    let authority = value
        .strip_prefix("http://")
        .or_else(|| value.strip_prefix("https://"))
        .ok_or_else(invalid)?;
    if authority.is_empty()
        || authority.contains(['/', '\\', '?', '#', '@', '*'])
        || authority.bytes().any(|b| b.is_ascii_whitespace())
    {
        return Err(invalid());
    }
    if authority.ends_with(':') {
        return Err(invalid());
    }
    let uri_authority = authority
        .parse::<axum::http::uri::Authority>()
        .map_err(|_| invalid())?;
    if uri_authority.port().is_some() && uri_authority.port_u16().filter(|port| *port > 0).is_none()
    {
        return Err(invalid());
    }
    let parsed = url::Url::parse(value).map_err(|_| invalid())?;
    if parsed.host().is_none() || parsed.port() == Some(0) {
        return Err(invalid());
    }
    Ok(parsed)
}

pub fn normalize_email(value: &str) -> String {
    value
        .trim_matches(|c| matches!(c, '\t'..='\r' | ' '))
        .to_ascii_lowercase()
}

fn valid_email(value: &str) -> bool {
    !value.is_empty() && value.len() <= 254 && value.contains('@')
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawCredentials {
    email: String,
    password: String,
}

struct Credentials {
    email: String,
    password: Zeroizing<String>,
}

fn decode_credentials(body: &[u8]) -> Result<Credentials, ()> {
    // Serde structs also accept positional arrays unless the object shape is
    // checked explicitly. JSON whitespace consists of exactly these four bytes.
    if body
        .iter()
        .find(|b| !matches!(b, b' ' | b'\t' | b'\r' | b'\n'))
        != Some(&b'{')
    {
        return Err(());
    }
    // Struct decoding rejects duplicate fields, including escaped aliases.
    // String decoding rejects invalid UTF-8 and unpaired surrogates.
    let raw: RawCredentials = serde_json::from_slice(body).map_err(|_| ())?;
    let credentials = Credentials {
        email: normalize_email(&raw.email),
        password: Zeroizing::new(raw.password),
    };
    if !valid_email(&credentials.email)
        || credentials.password.is_empty()
        || credentials.password.len() > 1024
    {
        return Err(());
    }
    Ok(credentials)
}

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
struct Store {
    sessions: HashMap<String, Session>,
    failures: HashMap<IpAddr, Failure>,
}

impl Store {
    fn prune(&mut self, now: Instant) {
        self.sessions.retain(|_, session| now < session.expires);
        self.failures.retain(|_, failure| now < failure.expires);
    }
}

type Clock = Arc<dyn Fn() -> Instant + Send + Sync>;
struct Auth {
    config: Config,
    salt: [u8; 16],
    password_hash: [u8; 32],
    store: Mutex<Store>,
    hash_slots: Arc<Semaphore>,
    clock: Clock,
}

fn derive(password: &[u8], salt: &[u8; 16]) -> Result<[u8; 32], ()> {
    let params = Params::new(64 * 1024, 3, 4, Some(32)).map_err(|_| ())?;
    let mut derived = [0; 32];
    Argon2::new(Algorithm::Argon2id, Version::V0x13, params)
        .hash_password_into(password, salt, &mut derived)
        .map_err(|_| ())?;
    Ok(derived)
}

pub async fn app(config: Config) -> Result<Router, String> {
    app_with_clock(config, Arc::new(Instant::now)).await
}

async fn app_with_clock(mut config: Config, clock: Clock) -> Result<Router, String> {
    let mut salt = [0; 16];
    getrandom::fill(&mut salt).map_err(|_| "system random generator unavailable")?;
    let password = Zeroizing::new(std::mem::take(&mut config.password));
    let password_hash = tokio::task::spawn_blocking(move || derive(password.as_bytes(), &salt))
        .await
        .map_err(|_| "password hashing task failed")?
        .map_err(|_| "password hashing failed")?;
    let state = Arc::new(Auth {
        config,
        salt,
        password_hash,
        store: Mutex::new(Store::default()),
        hash_slots: Arc::new(Semaphore::new(1)),
        clock,
    });
    // Explicit dispatch keeps framework 404/405/body rejections and implicit HEAD
    // behavior from changing this profile's error envelopes.
    Ok(Router::new().fallback(dispatch).with_state(state))
}

fn error(status: StatusCode, code: &str) -> Response {
    (status, Json(json!({"error":{"code":code,"message":code}}))).into_response()
}

fn single_header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    let mut values = headers.get_all(name).iter();
    let first = values.next()?.to_str().ok()?;
    if values.next().is_some() {
        return None;
    }
    Some(first)
}

fn session_token(headers: &HeaderMap) -> String {
    for header in headers.get_all("cookie") {
        if let Ok(value) = header.to_str() {
            for part in value.split(';') {
                if let Some((name, token)) = part.trim().split_once('=')
                    && name == "fs_session"
                {
                    return token.to_owned();
                }
            }
        }
    }
    String::new()
}

async fn dispatch(State(state): State<Arc<Auth>>, request: Request) -> Response {
    let auth_path = request.uri().path().starts_with("/auth/");
    let mut response = dispatch_inner(state, request).await;
    if auth_path {
        response
            .headers_mut()
            .insert("cache-control", HeaderValue::from_static("no-store"));
        response.headers_mut().insert(
            "x-content-type-options",
            HeaderValue::from_static("nosniff"),
        );
    }
    response
}

async fn dispatch_inner(state: Arc<Auth>, request: Request) -> Response {
    let expected = match request.uri().path() {
        "/auth/login" | "/auth/logout" => Method::POST,
        "/auth/me" | "/healthz" => Method::GET,
        _ => return error(StatusCode::NOT_FOUND, "NOT_FOUND"),
    };
    if *request.method() != expected {
        let mut response = error(StatusCode::METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED");
        response.headers_mut().insert(
            "allow",
            HeaderValue::from_static(if expected == Method::POST {
                "POST"
            } else {
                "GET"
            }),
        );
        return response;
    }
    if expected == Method::POST
        && single_header(request.headers(), "origin") != Some(state.config.origin.as_str())
    {
        return error(StatusCode::FORBIDDEN, "ORIGIN_DENIED");
    }
    match request.uri().path() {
        "/auth/login" => login(state, request).await,
        "/auth/me" => state.me(request.headers()),
        "/auth/logout" => state.logout(request.headers()),
        _ => {
            Json(json!({"status":"ok","profile":"browser-session-v1","implementation":"rust-axum"}))
                .into_response()
        }
    }
}

async fn login(state: Arc<Auth>, request: Request) -> Response {
    let media = single_header(request.headers(), "content-type")
        .and_then(|value| value.parse::<mime::Mime>().ok());
    if media.is_none_or(|value| value.type_() != mime::APPLICATION || value.subtype() != mime::JSON)
    {
        return error(StatusCode::UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE");
    }
    let old_token = session_token(request.headers());
    // Forwarding headers never replace the TCP peer supplied by axum::serve.
    let Some(peer) = request
        .extensions()
        .get::<ConnectInfo<SocketAddr>>()
        .map(|info| info.0.ip())
    else {
        return error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR");
    };
    if request
        .headers()
        .get("content-length")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
        .is_some_and(|length| length > BODY_LIMIT as u64)
    {
        return error(StatusCode::PAYLOAD_TOO_LARGE, "REQUEST_TOO_LARGE");
    }
    let bytes = match to_bytes(request.into_body(), BODY_LIMIT).await {
        Ok(bytes) => bytes,
        Err(err) => {
            if err
                .source()
                .is_some_and(|source| source.is::<http_body_util::LengthLimitError>())
            {
                return error(StatusCode::PAYLOAD_TOO_LARGE, "REQUEST_TOO_LARGE");
            }
            return error(StatusCode::BAD_REQUEST, "INVALID_REQUEST");
        }
    };
    let credentials = match decode_credentials(&bytes) {
        Ok(credentials) => credentials,
        Err(()) => return error(StatusCode::BAD_REQUEST, "INVALID_REQUEST"),
    };
    let permit = match state.hash_slots.clone().acquire_owned().await {
        Ok(permit) => permit,
        Err(_) => return error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR"),
    };
    // The permit stays in the blocking job even if the HTTP future is cancelled.
    // This serializes check/verify/record without holding the store lock during hashing.
    tokio::task::spawn_blocking(move || {
        let _permit = permit;
        state.authenticate(peer, credentials, old_token)
    })
    .await
    .unwrap_or_else(|_| error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR"))
}

impl Auth {
    fn authenticate(&self, peer: IpAddr, credentials: Credentials, old_token: String) -> Response {
        let now = (self.clock)();
        {
            let Ok(mut store) = self.store.lock() else {
                return error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR");
            };
            store.prune(now);
            if let Some(failure) = store
                .failures
                .get(&peer)
                .filter(|failure| failure.count >= self.config.rate_max)
            {
                let retry = failure
                    .expires
                    .saturating_duration_since(now)
                    .as_secs()
                    .saturating_add(1);
                let mut response = error(StatusCode::TOO_MANY_REQUESTS, "RATE_LIMITED");
                if let Ok(value) = retry.to_string().parse() {
                    response.headers_mut().insert("retry-after", value);
                }
                return response;
            }
        }
        let derived = match derive(credentials.password.as_bytes(), &self.salt) {
            Ok(hash) => Zeroizing::new(hash),
            Err(()) => return error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR"),
        };
        let password_valid = bool::from(derived.as_ref().ct_eq(self.password_hash.as_slice()));
        let now = (self.clock)();
        let Ok(mut store) = self.store.lock() else {
            return error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR");
        };
        store.prune(now);
        if !password_valid || credentials.email != self.config.email {
            let record = store.failures.entry(peer).or_insert(Failure {
                count: 0,
                expires: now + self.config.rate_window,
            });
            record.count = record.count.saturating_add(1);
            return error(StatusCode::UNAUTHORIZED, "INVALID_CREDENTIALS");
        }
        let (Ok(token), Ok(csrf)) = (random_token(), random_token()) else {
            return error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR");
        };
        store.failures.remove(&peer);
        store.sessions.remove(&old_token);
        store.sessions.insert(
            token.clone(),
            Session {
                csrf: csrf.clone(),
                expires: now + self.config.session_ttl,
            },
        );
        let mut response = self.user(&csrf);
        self.set_cookie(&mut response, &token, false);
        response
    }

    fn user(&self, csrf: &str) -> Response {
        Json(json!({"user":{"id":"demo-user","email":self.config.email},"csrfToken":csrf}))
            .into_response()
    }

    fn set_cookie(&self, response: &mut Response, token: &str, logout: bool) {
        let max_age = if logout {
            0
        } else {
            self.config.session_ttl.as_secs()
        };
        let secure = if self.config.secure { "; Secure" } else { "" };
        let cookie = format!(
            "fs_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}{secure}"
        );
        if let Ok(cookie) = HeaderValue::from_str(&cookie) {
            response.headers_mut().insert("set-cookie", cookie);
        }
    }

    fn me(&self, headers: &HeaderMap) -> Response {
        let Ok(mut store) = self.store.lock() else {
            return error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR");
        };
        store.prune((self.clock)());
        match store.sessions.get(&session_token(headers)) {
            Some(session) => self.user(&session.csrf),
            None => error(StatusCode::UNAUTHORIZED, "UNAUTHENTICATED"),
        }
    }

    fn logout(&self, headers: &HeaderMap) -> Response {
        let Ok(mut store) = self.store.lock() else {
            return error(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR");
        };
        store.prune((self.clock)());
        let token = session_token(headers);
        if let Some(session) = store.sessions.get(&token) {
            let supplied = single_header(headers, "x-csrf-token").unwrap_or("");
            if !bool::from(supplied.as_bytes().ct_eq(session.csrf.as_bytes())) {
                return error(StatusCode::FORBIDDEN, "CSRF_INVALID");
            }
        }
        store.sessions.remove(&token);
        let mut response = StatusCode::NO_CONTENT.into_response();
        self.set_cookie(&mut response, "", true);
        response
    }
}

fn random_token() -> Result<String, ()> {
    let mut bytes = [0; 32];
    getrandom::fill(&mut bytes).map_err(|_| ())?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

#[cfg(test)]
mod tests;
