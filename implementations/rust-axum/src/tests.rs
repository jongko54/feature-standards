use super::*;
use axum::body::Body;
use axum::http::Request;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use tower::ServiceExt;

const ORIGIN: &str = "http://127.0.0.1:5173";
const GOOD: &str = r#"{"email":"demo@example.com","password":"correct-horse-battery-staple"}"#;

fn config(extra: &[(&str, &str)]) -> Result<Config, String> {
    let mut values = HashMap::from([
        ("AUTH_DEMO", "true"),
        ("AUTH_COOKIE_SECURE", "false"),
        ("AUTH_ALLOWED_ORIGIN", ORIGIN),
    ]);
    values.extend(extra.iter().copied());
    Config::from_lookup(|key| values.get(key).map(|value| (*value).to_owned()))
}

async fn setup(extra: &[(&str, &str)]) -> Router {
    app(config(extra).unwrap()).await.unwrap()
}

fn request(method: &str, path: &str, body: impl Into<Body>) -> Request<Body> {
    let mut req = Request::builder()
        .method(method)
        .uri(path)
        .header("origin", ORIGIN)
        .header("content-type", "application/json; charset=utf-8")
        .body(body.into())
        .unwrap();
    req.extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 1], 1234))));
    req
}

async fn send(
    router: &Router,
    req: Request<Body>,
) -> (StatusCode, HeaderMap, serde_json::Value, Vec<u8>) {
    let response = router.clone().oneshot(req).await.unwrap();
    let status = response.status();
    let headers = response.headers().clone();
    let bytes = to_bytes(response.into_body(), 20_000)
        .await
        .unwrap()
        .to_vec();
    let json = serde_json::from_slice(&bytes).unwrap_or(serde_json::Value::Null);
    (status, headers, json, bytes)
}

fn cookie(headers: &HeaderMap) -> String {
    headers["set-cookie"]
        .to_str()
        .unwrap()
        .split(';')
        .next()
        .unwrap()
        .to_owned()
}

#[test]
fn email_normalization_uses_only_ascii_space_and_case() {
    assert_eq!(
        normalize_email("\t\n\u{000b}\u{000c}\r DEMO@EXAMPLE.COM \r\n"),
        "demo@example.com"
    );
    assert_eq!(
        normalize_email("\u{00a0}İOWNER@EXAMPLE.COM\u{00a0}"),
        "\u{00a0}İowner@example.com\u{00a0}"
    );
    assert_eq!(
        normalize_email("\u{001c}ÉOWNER@EXAMPLE.COM"),
        "\u{001c}Éowner@example.com"
    );
}

#[test]
fn strict_json_rejects_ambiguous_or_invalid_input() {
    for input in [
        &b"null"[..],
        &b"[]"[..],
        &br#"["demo@example.com","x"]"#[..],
        &b"{}"[..],
        &br#"{"email":"demo@example.com","email":"demo@example.com","password":"x"}"#[..],
        &br#"{"email":"demo@example.com","\u0065mail":"demo@example.com","password":"x"}"#[..],
        &br#"{"email":"demo@example.com","password":"x","extra":1}"#[..],
        &br#"{"email":"demo@example.com","password":null}"#[..],
        &br#"{"email":"demo@example.com","password":"\ud800"}"#[..],
        &br#"{"email":"demo@example.com","password":"\udfff"}"#[..],
        &br#"{"email":"demo@example.com","password":"\ud800\u0061"}"#[..],
        &br#"{"email":"demo@example.com","password":"x"} {}"#[..],
        &b"{\"email\":\"a@b\",\"password\":\"\xff\"}"[..],
        &br#"{"email":"missing-at","password":"x"}"#[..],
        &br#"{"email":"a@b","password":""}"#[..],
    ] {
        assert!(decode_credentials(input).is_err(), "accepted {:?}", input);
    }
    let credentials =
        decode_credentials(br#"{"email":"\ud83d\ude00@EXAMPLE.COM","password":"\ud83d\ude00"}"#)
            .unwrap();
    assert_eq!(credentials.email, "😀@example.com");
    assert_eq!(&*credentials.password, "😀");
    let too_long = serde_json::json!({"email":"a@b","password":"한".repeat(342)}).to_string();
    assert!(decode_credentials(too_long.as_bytes()).is_err());
    let max = serde_json::json!({"email":"a@b","password":"x".repeat(1024)}).to_string();
    assert!(decode_credentials(max.as_bytes()).is_ok());
    let long_email =
        serde_json::json!({"email":format!("{}@b", "한".repeat(85)),"password":"x"}).to_string();
    assert!(decode_credentials(long_email.as_bytes()).is_err());
}

#[test]
fn configuration_requires_explicit_demo_and_safe_exact_origin() {
    assert!(Config::from_lookup(|_| None).is_err());
    for (name, value) in [
        ("AUTH_DEMO", "TRUE"),
        ("AUTH_COOKIE_SECURE", "0"),
        ("AUTH_PORT", "0"),
        ("AUTH_PORT", "65536"),
        ("AUTH_PORT", "+8000"),
        ("AUTH_HOST", ""),
        ("AUTH_SESSION_TTL_SECONDS", "0"),
        ("AUTH_RATE_LIMIT_MAX", "-1"),
        ("AUTH_RATE_LIMIT_WINDOW_SECONDS", "1.5"),
        ("AUTH_SESSION_TTL_SECONDS", "18446744073709551615"),
        ("AUTH_ALLOWED_ORIGIN", "http://*.example.com"),
        ("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173/"),
        ("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173?"),
        ("AUTH_ALLOWED_ORIGIN", "http://user@127.0.0.1:5173"),
        ("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:5173#"),
        ("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:0"),
        ("AUTH_ALLOWED_ORIGIN", "http://127.0.0.1:"),
        ("AUTH_ALLOWED_ORIGIN", "http://example.com"),
    ] {
        assert!(config(&[(name, value)]).is_err(), "accepted {name}={value}");
    }
    assert!(config(&[("AUTH_ALLOWED_ORIGIN", "http://[::1]:5173")]).is_ok());
    assert!(config(&[("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")]).is_ok());
    assert!(
        config(&[
            ("AUTH_COOKIE_SECURE", "true"),
            ("AUTH_ALLOWED_ORIGIN", "https://app.example.com")
        ])
        .is_ok()
    );
    let non_demo = [
        ("AUTH_DEMO", "false"),
        ("AUTH_COOKIE_SECURE", "true"),
        ("AUTH_ALLOWED_ORIGIN", "https://app.example.com"),
        ("AUTH_USER_EMAIL", " \tİOWNER@EXAMPLE.COM\r\n"),
        ("AUTH_USER_PASSWORD", "password"),
    ];
    assert_eq!(config(&non_demo).unwrap().email, "İowner@example.com");
    assert!(
        config(&[
            ("AUTH_DEMO", "false"),
            ("AUTH_USER_EMAIL", "a@b"),
            ("AUTH_USER_PASSWORD", "x")
        ])
        .is_err()
    );
}

#[tokio::test]
async fn login_me_rotation_independence_and_logout_revoke_cookie() {
    let router = setup(&[]).await;
    assert_eq!(
        send(&router, request("GET", "/auth/me", "")).await.0,
        StatusCode::UNAUTHORIZED
    );
    let (status, headers, first, _) = send(&router, request("POST", "/auth/login", GOOD)).await;
    assert_eq!(status, StatusCode::OK);
    let first_cookie = cookie(&headers);
    assert_eq!(
        first["user"],
        serde_json::json!({"id":"demo-user","email":"demo@example.com"})
    );
    assert!(first["csrfToken"].as_str().unwrap().len() >= 43);
    assert_ne!(
        first_cookie.split_once('=').unwrap().1,
        first["csrfToken"].as_str().unwrap()
    );
    let cookie_header = headers["set-cookie"].to_str().unwrap();
    for attribute in ["Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=1800"] {
        assert!(cookie_header.contains(attribute));
    }
    assert!(!cookie_header.contains("Domain="));
    assert!(!cookie_header.contains("Secure"));
    let mut me = request("GET", "/auth/me", "");
    me.headers_mut()
        .insert("cookie", first_cookie.parse().unwrap());
    assert_eq!(send(&router, me).await.2, first);
    let (_, independent_headers, _, _) = send(&router, request("POST", "/auth/login", GOOD)).await;
    let mut rotate = request("POST", "/auth/login", GOOD);
    rotate
        .headers_mut()
        .insert("cookie", first_cookie.parse().unwrap());
    let (_, rotated_headers, rotated, _) = send(&router, rotate).await;
    assert_ne!(rotated["csrfToken"], first["csrfToken"]);
    for (session, expected) in [
        (&first_cookie, StatusCode::UNAUTHORIZED),
        (&cookie(&independent_headers), StatusCode::OK),
    ] {
        let mut me = request("GET", "/auth/me", "");
        me.headers_mut().insert("cookie", session.parse().unwrap());
        assert_eq!(send(&router, me).await.0, expected);
    }
    let rotated_cookie = cookie(&rotated_headers);
    for token in [None, Some("wrong")] {
        let mut logout = request("POST", "/auth/logout", "");
        logout
            .headers_mut()
            .insert("cookie", rotated_cookie.parse().unwrap());
        if let Some(token) = token {
            logout
                .headers_mut()
                .insert("x-csrf-token", token.parse().unwrap());
        }
        assert_eq!(
            send(&router, logout).await.2["error"]["code"],
            "CSRF_INVALID"
        );
        let mut me = request("GET", "/auth/me", "");
        me.headers_mut()
            .insert("cookie", rotated_cookie.parse().unwrap());
        assert_eq!(send(&router, me).await.0, StatusCode::OK);
    }
    let mut logout = request("POST", "/auth/logout", "");
    logout
        .headers_mut()
        .insert("cookie", rotated_cookie.parse().unwrap());
    logout.headers_mut().insert(
        "x-csrf-token",
        rotated["csrfToken"].as_str().unwrap().parse().unwrap(),
    );
    let (status, headers, _, body) = send(&router, logout).await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    assert!(body.is_empty());
    assert!(
        headers["set-cookie"]
            .to_str()
            .unwrap()
            .contains("Max-Age=0")
    );
    let mut me = request("GET", "/auth/me", "");
    me.headers_mut()
        .insert("cookie", rotated_cookie.parse().unwrap());
    assert_eq!(send(&router, me).await.0, StatusCode::UNAUTHORIZED);
    assert_eq!(
        send(&router, request("POST", "/auth/logout", "")).await.0,
        StatusCode::NO_CONTENT
    );
}

#[tokio::test]
async fn error_envelopes_methods_media_size_and_duplicate_origins() {
    let router = setup(&[]).await;
    for (method, path, body, status, code) in [
        ("GET", "/auth/login", "", 405, "METHOD_NOT_ALLOWED"),
        ("HEAD", "/auth/me", "", 405, "METHOD_NOT_ALLOWED"),
        ("OPTIONS", "/auth/login", "", 405, "METHOD_NOT_ALLOWED"),
        ("POST", "/auth/missing", "", 404, "NOT_FOUND"),
        ("POST", "/auth/login", "[]", 400, "INVALID_REQUEST"),
    ] {
        let (actual, headers, json, bytes) = send(&router, request(method, path, body)).await;
        assert_eq!(actual.as_u16(), status);
        if method == "HEAD" {
            assert!(bytes.is_empty());
            assert_eq!(headers["allow"], "GET");
        } else {
            assert_eq!(json["error"]["code"], code);
        }
        assert_eq!(headers["cache-control"], "no-store");
        assert_eq!(headers["x-content-type-options"], "nosniff");
        assert!(!headers.contains_key("access-control-allow-origin"));
    }
    let mut missing = request("POST", "/auth/login", GOOD);
    missing.headers_mut().remove("origin");
    assert_eq!(
        send(&router, missing).await.2["error"]["code"],
        "ORIGIN_DENIED"
    );
    let mut duplicate = request("POST", "/auth/login", GOOD);
    duplicate
        .headers_mut()
        .append("origin", ORIGIN.parse().unwrap());
    assert_eq!(
        send(&router, duplicate).await.2["error"]["code"],
        "ORIGIN_DENIED"
    );
    let mut media = request("POST", "/auth/login", GOOD);
    media
        .headers_mut()
        .insert("content-type", "text/plain".parse().unwrap());
    assert_eq!(
        send(&router, media).await.2["error"]["code"],
        "UNSUPPORTED_MEDIA_TYPE"
    );
    for size in [4096, 4097] {
        let (status, headers, json, _) =
            send(&router, request("POST", "/auth/login", " ".repeat(size))).await;
        assert_eq!(status.as_u16(), if size == 4096 { 400 } else { 413 });
        assert_eq!(
            json["error"]["code"],
            if size == 4096 {
                "INVALID_REQUEST"
            } else {
                "REQUEST_TOO_LARGE"
            }
        );
        assert_eq!(headers["cache-control"], "no-store");
    }
}

#[tokio::test]
async fn absolute_expiry_is_not_extended_and_secure_cookie_is_preserved() {
    let elapsed = Arc::new(AtomicU64::new(0));
    let tick = elapsed.clone();
    let base = Instant::now();
    let router = app_with_clock(
        config(&[
            ("AUTH_SESSION_TTL_SECONDS", "2"),
            ("AUTH_COOKIE_SECURE", "true"),
        ])
        .unwrap(),
        Arc::new(move || base + Duration::from_secs(tick.load(Ordering::SeqCst))),
    )
    .await
    .unwrap();
    let (_, headers, _, _) = send(&router, request("POST", "/auth/login", GOOD)).await;
    assert!(headers["set-cookie"].to_str().unwrap().contains("Secure"));
    let token = cookie(&headers);
    for (seconds, expected) in [(1, StatusCode::OK), (2, StatusCode::UNAUTHORIZED)] {
        elapsed.store(seconds, Ordering::SeqCst);
        let mut me = request("GET", "/auth/me", "");
        me.headers_mut().insert("cookie", token.parse().unwrap());
        assert_eq!(send(&router, me).await.0, expected);
    }
    let mut logout = request("POST", "/auth/logout", "");
    logout
        .headers_mut()
        .insert("cookie", token.parse().unwrap());
    let (status, headers, _, _) = send(&router, logout).await;
    assert_eq!(status, StatusCode::NO_CONTENT);
    assert!(headers["set-cookie"].to_str().unwrap().contains("Secure"));
}

#[tokio::test]
async fn concurrent_failures_are_atomic_and_forwarded_addresses_are_ignored() {
    let router = setup(&[("AUTH_RATE_LIMIT_MAX", "2")]).await;
    let mut handles = Vec::new();
    for index in 0..5 {
        let app = router.clone();
        handles.push(tokio::spawn(async move {
            let mut req = request(
                "POST",
                "/auth/login",
                r#"{"email":"absent@example.com","password":"wrong"}"#,
            );
            req.headers_mut().insert(
                "x-forwarded-for",
                format!("192.0.2.{index}").parse().unwrap(),
            );
            send(&app, req).await.0
        }));
    }
    let mut unauthorized = 0;
    let mut limited = 0;
    for handle in handles {
        match handle.await.unwrap() {
            StatusCode::UNAUTHORIZED => unauthorized += 1,
            StatusCode::TOO_MANY_REQUESTS => limited += 1,
            other => panic!("unexpected {other}"),
        }
    }
    assert_eq!((unauthorized, limited), (2, 3));
    let (status, headers, json, _) = send(&router, request("POST", "/auth/login", GOOD)).await;
    assert_eq!(status, StatusCode::TOO_MANY_REQUESTS);
    assert_eq!(json["error"]["code"], "RATE_LIMITED");
    assert!(
        headers["retry-after"]
            .to_str()
            .unwrap()
            .parse::<u64>()
            .unwrap()
            > 0
    );
}

#[tokio::test]
async fn malformed_requests_do_not_consume_failure_limit_and_success_resets_it() {
    let router = setup(&[("AUTH_RATE_LIMIT_MAX", "2")]).await;
    for _ in 0..3 {
        assert_eq!(
            send(&router, request("POST", "/auth/login", "[]")).await.0,
            StatusCode::BAD_REQUEST
        );
    }
    let wrong = r#"{"email":"absent@example.com","password":"wrong"}"#;
    assert_eq!(
        send(&router, request("POST", "/auth/login", wrong)).await.0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(&router, request("POST", "/auth/login", GOOD)).await.0,
        StatusCode::OK
    );
    assert_eq!(
        send(&router, request("POST", "/auth/login", wrong)).await.0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(&router, request("POST", "/auth/login", GOOD)).await.0,
        StatusCode::OK
    );
}

#[tokio::test]
async fn failure_window_expires_and_tcp_peers_have_independent_limits() {
    let elapsed = Arc::new(AtomicU64::new(0));
    let tick = elapsed.clone();
    let base = Instant::now();
    let router = app_with_clock(
        config(&[
            ("AUTH_RATE_LIMIT_MAX", "1"),
            ("AUTH_RATE_LIMIT_WINDOW_SECONDS", "3"),
        ])
        .unwrap(),
        Arc::new(move || base + Duration::from_secs(tick.load(Ordering::SeqCst))),
    )
    .await
    .unwrap();
    let wrong = r#"{"email":"absent@example.com","password":"wrong"}"#;
    assert_eq!(
        send(&router, request("POST", "/auth/login", wrong)).await.0,
        StatusCode::UNAUTHORIZED
    );
    let mut other = request("POST", "/auth/login", GOOD);
    other
        .extensions_mut()
        .insert(ConnectInfo(SocketAddr::from(([127, 0, 0, 2], 1234))));
    assert_eq!(send(&router, other).await.0, StatusCode::OK);
    elapsed.store(2, Ordering::SeqCst);
    assert_eq!(
        send(&router, request("POST", "/auth/login", GOOD)).await.0,
        StatusCode::TOO_MANY_REQUESTS
    );
    elapsed.store(3, Ordering::SeqCst);
    assert_eq!(
        send(&router, request("POST", "/auth/login", GOOD)).await.0,
        StatusCode::OK
    );
}

#[tokio::test]
async fn unicode_configuration_and_paired_surrogates_authenticate_without_case_folding() {
    let router = setup(&[
        ("AUTH_DEMO", "false"),
        ("AUTH_COOKIE_SECURE", "true"),
        ("AUTH_ALLOWED_ORIGIN", "https://app.example.com"),
        ("AUTH_USER_EMAIL", " \tİOWNER@EXAMPLE.COM\r\n"),
        ("AUTH_USER_PASSWORD", "😀"),
    ])
    .await;
    let mut req = request(
        "POST",
        "/auth/login",
        br#"{"email":"\u0130owner@example.com","password":"\ud83d\ude00"}"#.to_vec(),
    );
    req.headers_mut()
        .insert("origin", "https://app.example.com".parse().unwrap());
    let (status, _, json, _) = send(&router, req).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(json["user"]["email"], "İowner@example.com");
    let mut req = request(
        "POST",
        "/auth/login",
        r#"{"email":"i̇owner@example.com","password":"😀"}"#,
    );
    req.headers_mut()
        .insert("origin", "https://app.example.com".parse().unwrap());
    assert_eq!(send(&router, req).await.0, StatusCode::UNAUTHORIZED);
    let router = setup(&[]).await;
    let body = serde_json::json!({"email":"\t\n\u{000b}\u{000c}\r DEMO@EXAMPLE.COM \r\n", "password":"correct-horse-battery-staple"}).to_string();
    assert_eq!(
        send(&router, request("POST", "/auth/login", body)).await.0,
        StatusCode::OK
    );
}
