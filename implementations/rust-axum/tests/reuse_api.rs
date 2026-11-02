use axum::body::to_bytes;
use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::Response;
use feature_standards_auth::{
    AuthError, AuthService, AuthStore, LoginInput, LoginSession, SessionUser, StoreFuture,
    current_user,
};
use serde_json::json;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

const TOKEN: &str = "private-test-session";
const PRIVATE_CSRF: &str = "private-test-csrf";

enum StoreState {
    ExpiresAt { clock: Arc<AtomicU64>, tick: u64 },
    FailsWith(AuthError),
}

// This external adapter supplies outcomes, not HTTP responses. The public
// helper owns Cookie extraction, status/error mapping, and response headers.
struct ExternalStore(StoreState);

impl AuthStore for ExternalStore {
    fn profile(&self) -> &'static str {
        "browser-session-v1"
    }

    fn ready(&self) -> StoreFuture<'_, ()> {
        Box::pin(async { Ok(()) })
    }

    fn login(&self, _input: LoginInput) -> StoreFuture<'_, (LoginSession, String)> {
        Box::pin(async { panic!("current_user must not create a session") })
    }

    fn me(&self, token: String) -> StoreFuture<'_, LoginSession> {
        Box::pin(async move {
            match &self.0 {
                StoreState::FailsWith(error) => Err(error.clone()),
                StoreState::ExpiresAt { clock, tick }
                    if token == TOKEN && clock.load(Ordering::SeqCst) < *tick =>
                {
                    Ok(LoginSession {
                        user: SessionUser {
                            id: "demo-user".into(),
                            email: "demo@example.com".into(),
                        },
                        csrf_token: PRIVATE_CSRF.into(),
                    })
                }
                _ => Err(AuthError::Unauthenticated),
            }
        })
    }

    fn logout(&self, _token: String, _csrf: Option<String>) -> StoreFuture<'_, ()> {
        Box::pin(async { panic!("current_user must not change a session") })
    }
}

fn headers() -> HeaderMap {
    let mut headers = HeaderMap::new();
    headers.insert(
        "cookie",
        HeaderValue::from_str(&format!("unrelated=value; fs_session={TOKEN}")).unwrap(),
    );
    headers
}

fn failed(result: Result<SessionUser, Response>) -> Response {
    match result {
        Err(response) => response,
        Ok(_) => panic!("failed session lookup returned an authenticated user"),
    }
}

async fn assert_error(response: Response, status: StatusCode, code: &str) {
    assert_eq!(response.status(), status);
    assert_eq!(response.headers()["cache-control"], "no-store");
    assert_eq!(response.headers()["x-content-type-options"], "nosniff");
    assert!(response.headers().get("set-cookie").is_none());
    let body = to_bytes(response.into_body(), 4096).await.unwrap();
    let body: serde_json::Value = serde_json::from_slice(&body).unwrap();
    // Do not print an unexpected payload containing identity or credentials.
    assert!(
        body == json!({"error": {"code": code, "message": code}}),
        "public lookup errors must contain only the generic contract error"
    );
    let encoded = body.to_string();
    assert!(!encoded.contains(TOKEN));
    assert!(!encoded.contains(PRIVATE_CSRF));
    assert!(!encoded.contains("demo@example.com"));
}

#[tokio::test]
async fn public_lookup_refuses_session_at_absolute_expiry() {
    let clock = Arc::new(AtomicU64::new(9));
    let service = AuthService::new(Arc::new(ExternalStore(StoreState::ExpiresAt {
        clock: clock.clone(),
        tick: 10,
    })));
    let user = current_user(&service, &headers()).await.ok().unwrap();
    assert_eq!(user.id, "demo-user");
    clock.store(10, Ordering::SeqCst);
    assert_error(
        failed(current_user(&service, &headers()).await),
        StatusCode::UNAUTHORIZED,
        "UNAUTHENTICATED",
    )
    .await;
}

#[tokio::test]
async fn public_lookup_maps_storage_failure_to_safe_noncacheable_503() {
    let service = AuthService::new(Arc::new(ExternalStore(StoreState::FailsWith(
        AuthError::StorageUnavailable,
    ))));
    assert_error(
        failed(current_user(&service, &headers()).await),
        StatusCode::SERVICE_UNAVAILABLE,
        "STORAGE_UNAVAILABLE",
    )
    .await;
}

#[tokio::test]
async fn public_lookup_maps_internal_failure_to_safe_noncacheable_500() {
    let service = AuthService::new(Arc::new(ExternalStore(StoreState::FailsWith(
        AuthError::Internal,
    ))));
    assert_error(
        failed(current_user(&service, &headers()).await),
        StatusCode::INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
    )
    .await;
}
