use axum::Router;
use axum::body::{Body, to_bytes};
use axum::extract::ConnectInfo;
use axum::http::{HeaderMap, Request, StatusCode};
use feature_standards_auth::Config;
use serde_json::Value;
use std::net::SocketAddr;
use tower::ServiceExt;

const ORIGIN: &str = "http://127.0.0.1:5173";

fn request(method: &str, path: &str, body: &str, cookie: Option<&str>) -> Request<Body> {
    let mut builder = Request::builder()
        .method(method)
        .uri(path)
        .header("origin", ORIGIN)
        .header("content-type", "application/json");
    if let Some(cookie) = cookie {
        builder = builder.header("cookie", cookie);
    }
    let mut request = builder.body(Body::from(body.to_owned())).unwrap();
    request
        .extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 12000))));
    request
}

async fn send(app: &Router, request: Request<Body>) -> (StatusCode, HeaderMap, Value) {
    let response = app.clone().oneshot(request).await.unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let body = to_bytes(response.into_body(), 16_384).await.unwrap();
    let json = serde_json::from_slice(&body).unwrap_or(Value::Null);
    (status, headers, json)
}

#[tokio::test]
async fn imported_package_protects_profile_and_revokes_copied_cookie() {
    let config = Config::from_lookup(|key| {
        match key {
            "AUTH_DEMO" => Some("true"),
            "AUTH_COOKIE_SECURE" => Some("false"),
            "AUTH_ALLOWED_ORIGIN" => Some(ORIGIN),
            _ => None,
        }
        .map(str::to_owned)
    })
    .unwrap();
    let app = feature_standards_consumer_rust::app(config).await.unwrap();

    let (status, headers, body) = send(&app, request("GET", "/api/profile", "", None)).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
    assert_eq!(body["error"]["code"], "UNAUTHENTICATED");
    assert_eq!(headers["cache-control"], "no-store");
    assert_eq!(headers["x-content-type-options"], "nosniff");

    let (status, headers, login) = send(
        &app,
        request(
            "POST",
            "/auth/login",
            r#"{"email":"demo@example.com","password":"correct-horse-battery-staple"}"#,
            None,
        ),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let cookie = headers["set-cookie"]
        .to_str()
        .unwrap()
        .split(';')
        .next()
        .unwrap()
        .to_owned();
    let (status, headers, profile) =
        send(&app, request("GET", "/api/profile", "", Some(&cookie))).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(profile["user"], login["user"]);
    assert_eq!(headers["cache-control"], "no-store");
    assert_eq!(headers["x-content-type-options"], "nosniff");
    let (status, _, body) = send(&app, request("POST", "/auth/logout", "", Some(&cookie))).await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(body["error"]["code"], "CSRF_INVALID");
    assert_eq!(
        send(&app, request("GET", "/api/profile", "", Some(&cookie)))
            .await
            .0,
        StatusCode::OK
    );
    let mut logout = request("POST", "/auth/logout", "", Some(&cookie));
    logout.headers_mut().insert(
        "x-csrf-token",
        login["csrfToken"].as_str().unwrap().parse().unwrap(),
    );
    assert_eq!(send(&app, logout).await.0, StatusCode::NO_CONTENT);
    assert_eq!(
        send(&app, request("GET", "/api/profile", "", Some(&cookie)))
            .await
            .0,
        StatusCode::UNAUTHORIZED
    );
}
