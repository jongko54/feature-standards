use super::tests::{config, request, send};
use super::*;
use std::sync::Mutex;

#[derive(Clone)]
struct Captured {
    action: AccountAction,
    peer: std::net::IpAddr,
    email: String,
    token: String,
    password: String,
}
#[derive(Default)]
struct AccountsBoundary {
    calls: Mutex<Vec<Captured>>,
    failure: Mutex<Option<AuthError>>,
}
impl AuthStore for AccountsBoundary {
    fn profile(&self) -> &'static str {
        "browser-session-v3"
    }
    fn ready(&self) -> StoreFuture<'_, ()> {
        Box::pin(async { Ok(()) })
    }
    fn login(&self, _input: LoginInput) -> StoreFuture<'_, (LoginSession, String)> {
        Box::pin(async { Err(AuthError::Internal) })
    }
    fn me(&self, _token: String) -> StoreFuture<'_, LoginSession> {
        Box::pin(async { Err(AuthError::Unauthenticated) })
    }
    fn logout(&self, _token: String, _csrf: Option<String>) -> StoreFuture<'_, ()> {
        Box::pin(async { Err(AuthError::Internal) })
    }
    fn account(&self, input: AccountInput) -> StoreFuture<'_, ()> {
        self.calls.lock().unwrap().push(Captured {
            action: input.action,
            peer: input.peer,
            email: input.email,
            token: input.token,
            password: input.password.to_string(),
        });
        let result = self.failure.lock().unwrap().clone().map_or(Ok(()), Err);
        Box::pin(async move { result })
    }
}

fn accounts() -> (Router, Arc<AccountsBoundary>) {
    let settings = config(&[
        ("AUTH_STORE", "postgres"),
        (
            "AUTH_DATABASE_URL",
            "postgresql://localhost/feature_standards_test_accounts?sslmode=disable",
        ),
        ("AUTH_ACCOUNT_LIFECYCLE", "true"),
    ])
    .unwrap();
    let store = Arc::new(AccountsBoundary::default());
    let router = app_with_service(settings, AuthService::new(store.clone()));
    (router, store)
}

#[test]
fn account_profile_is_explicit_postgres_only() {
    assert!(config(&[("AUTH_ACCOUNT_LIFECYCLE", "true")]).is_err());
    assert!(config(&[("AUTH_ACCOUNT_LIFECYCLE", "TRUE")]).is_err());
    assert!(config(&[("AUTH_ACCOUNT_LIFECYCLE", "")]).is_err());
    let uri = "postgresql://localhost/feature_standards_test_accounts?sslmode=disable";
    assert!(
        config(&[
            ("AUTH_STORE", "postgres"),
            ("AUTH_DATABASE_URL", uri),
            ("AUTH_ACCOUNT_LIFECYCLE", "true")
        ])
        .is_ok()
    );
}

#[tokio::test]
async fn account_http_dispatch_preserves_inputs_without_issuing_cookies() {
    let (router, store) = accounts();
    let token = "A".repeat(43);
    for (action, path, body, status) in [
        (
            AccountAction::Register,
            "/auth/register",
            serde_json::json!({"email":"  한@EXAMPLE.COM  ","password":"😀".repeat(15)}),
            StatusCode::ACCEPTED,
        ),
        (
            AccountAction::VerifyRequest,
            "/auth/email-verification/request",
            serde_json::json!({"email":"  한@EXAMPLE.COM  "}),
            StatusCode::ACCEPTED,
        ),
        (
            AccountAction::ResetRequest,
            "/auth/password-reset/request",
            serde_json::json!({"email":"  한@EXAMPLE.COM  "}),
            StatusCode::ACCEPTED,
        ),
        (
            AccountAction::VerifyConfirm,
            "/auth/email-verification/confirm",
            serde_json::json!({"token":token}),
            StatusCode::NO_CONTENT,
        ),
        (
            AccountAction::ResetConfirm,
            "/auth/password-reset/confirm",
            serde_json::json!({"token":token,"password":"  abcdefghijklmnop  "}),
            StatusCode::NO_CONTENT,
        ),
    ] {
        let mut req = request("POST", path, body.to_string());
        req.headers_mut()
            .insert("x-forwarded-for", "198.51.100.4".parse().unwrap());
        let response = send(&router, req).await;
        assert_eq!(response.0, status);
        assert!(!response.1.contains_key("set-cookie"));
        assert_eq!(response.1["cache-control"], "no-store");
        assert_eq!(response.1["x-content-type-options"], "nosniff");
        if action.confirms() {
            assert!(response.3.is_empty());
        } else {
            assert_eq!(response.2, serde_json::json!({"status":"accepted"}));
        }
        let recorded = store.calls.lock().unwrap().last().unwrap().clone();
        assert_eq!(recorded.action, action);
        assert_eq!(
            recorded.peer,
            "127.0.0.1".parse::<std::net::IpAddr>().unwrap()
        );
        if action.confirms() {
            assert!(recorded.token == token);
        } else {
            assert_eq!(recorded.email, "한@example.com");
        }
        if action == AccountAction::Register {
            assert!(recorded.password == "😀".repeat(15));
        }
        if action == AccountAction::ResetConfirm {
            assert!(recorded.password == "  abcdefghijklmnop  ");
        }
    }
    assert_eq!(store.calls.lock().unwrap().len(), 5);
    assert_eq!(
        send(&router, request("GET", "/healthz", "")).await.2["profile"],
        "browser-session-v3"
    );
}

#[tokio::test]
async fn account_validation_rejects_ambiguous_json_passwords_and_capabilities() {
    let (router, store) = accounts();
    for body in [
        "null".to_string(),
        "[]".to_string(),
        "{}".to_string(),
        r#"{"email":"a@b","email":"c@d","password":"123456789012345"}"#.into(),
        r#"{"email":"a@b","password":"123456789012345","extra":true}"#.into(),
        r#"{"email":"a@b","password":"\ud800"}"#.into(),
        serde_json::json!({"email":"a@b","password":"😀".repeat(14)}).to_string(),
        serde_json::json!({"email":"a@b","password":"한".repeat(342)}).to_string(),
        serde_json::json!({"email":"a\u{0}@b","password":"123456789012345"}).to_string(),
        serde_json::json!({"email":"a b@example.com","password":"123456789012345"}).to_string(),
        serde_json::json!({"email":"a\u{7f}@b","password":"123456789012345"}).to_string(),
    ] {
        assert_eq!(
            send(&router, request("POST", "/auth/register", body))
                .await
                .0,
            StatusCode::BAD_REQUEST
        );
    }
    for token in [
        "A".repeat(42),
        "A".repeat(44),
        format!("{}=", "A".repeat(42)),
        format!("{}!", "A".repeat(42)),
    ] {
        assert_eq!(
            send(
                &router,
                request(
                    "POST",
                    "/auth/email-verification/confirm",
                    serde_json::json!({"token":token}).to_string()
                )
            )
            .await
            .0,
            StatusCode::BAD_REQUEST
        );
    }
    assert!(store.calls.lock().unwrap().is_empty());
    // Scalar count and UTF-8 byte limits are independent; NUL is allowed in passwords.
    let body = serde_json::json!({"email":"a@b", "password": format!("{}\u{0}", "a".repeat(14))});
    assert_eq!(
        send(&router, request("POST", "/auth/register", body.to_string()))
            .await
            .0,
        StatusCode::ACCEPTED
    );
}

#[tokio::test]
async fn account_http_enforces_origin_method_media_size_and_error_envelopes() {
    let (router, store) = accounts();
    let path = "/auth/password-reset/request";
    let body = r#"{"email":"a@b"}"#;
    assert_eq!(
        send(&router, request("GET", path, "")).await.0,
        StatusCode::METHOD_NOT_ALLOWED
    );
    let mut absent = request("POST", path, body);
    absent.headers_mut().remove("origin");
    assert_eq!(send(&router, absent).await.0, StatusCode::FORBIDDEN);
    let mut duplicate = request("POST", path, body);
    duplicate
        .headers_mut()
        .append("origin", "http://127.0.0.1:5173".parse().unwrap());
    assert_eq!(send(&router, duplicate).await.0, StatusCode::FORBIDDEN);
    let mut no_media = request("POST", path, body);
    no_media.headers_mut().remove("content-type");
    assert_eq!(
        send(&router, no_media).await.0,
        StatusCode::UNSUPPORTED_MEDIA_TYPE
    );
    assert_eq!(
        send(&router, request("POST", path, "x".repeat(4097)))
            .await
            .0,
        StatusCode::PAYLOAD_TOO_LARGE
    );
    assert!(store.calls.lock().unwrap().is_empty());
    for (failure, status, code) in [
        (
            AuthError::InvalidToken,
            StatusCode::BAD_REQUEST,
            "INVALID_TOKEN",
        ),
        (
            AuthError::RateLimited(9),
            StatusCode::TOO_MANY_REQUESTS,
            "RATE_LIMITED",
        ),
        (
            AuthError::StorageUnavailable,
            StatusCode::SERVICE_UNAVAILABLE,
            "STORAGE_UNAVAILABLE",
        ),
    ] {
        *store.failure.lock().unwrap() = Some(failure);
        let response = send(&router, request("POST", path, body)).await;
        assert_eq!(response.0, status);
        assert_eq!(response.2["error"]["code"], code);
        assert!(!response.1.contains_key("set-cookie"));
        assert_eq!(response.1["cache-control"], "no-store");
        if status == StatusCode::TOO_MANY_REQUESTS {
            assert_eq!(response.1["retry-after"], "9");
        }
    }
}

async fn real_database() -> tokio_postgres::Client {
    let uri = std::env::var("AUTH_ACCOUNT_TEST_DATABASE_URL")
        .expect("AUTH_ACCOUNT_TEST_DATABASE_URL must name a disposable schema-2 DB");
    let parsed = postgres::validate_url(&uri).unwrap();
    assert!(
        parsed
            .get_dbname()
            .unwrap()
            .starts_with("feature_standards_test")
    );
    let (client, connection) = parsed.connect(tokio_postgres::NoTls).await.unwrap();
    tokio::spawn(async move {
        let _ = connection.await;
    });
    client
}

#[tokio::test]
#[ignore = "requires an isolated schema-2 AUTH_ACCOUNT_TEST_DATABASE_URL"]
async fn postgres_accounts_registration_verification_reset_and_rollback() {
    let db = real_database().await;
    let uri = std::env::var("AUTH_ACCOUNT_TEST_DATABASE_URL").unwrap();
    let values = [
        ("AUTH_STORE", "postgres"),
        ("AUTH_DATABASE_URL", uri.as_str()),
        ("AUTH_ACCOUNT_LIFECYCLE", "true"),
    ];
    let router = app(config(&values).unwrap()).await.unwrap();
    assert_eq!(
        send(&router, request("GET", "/healthz", "")).await.2["profile"],
        "browser-session-v3"
    );
    assert!(
        app(config(&[
            ("AUTH_STORE", "postgres"),
            ("AUTH_DATABASE_URL", uri.as_str())
        ])
        .unwrap())
        .await
        .is_err(),
        "v2 must refuse account schema 2"
    );
    db.batch_execute("DELETE FROM feature_auth.users WHERE email IN ('rust-new@example.com','rust-disabled@example.com'); TRUNCATE feature_auth.account_attempts,feature_auth.login_attempts;").await.unwrap();
    let email = "rust-new@example.com";
    let password = "initial-password-12345";
    let changed = "replacement-password-12345";
    let post = |path: &str, body: serde_json::Value| request("POST", path, body.to_string());
    let first = send(
        &router,
        post(
            "/auth/register",
            serde_json::json!({"email":email,"password":password}),
        ),
    )
    .await;
    assert_eq!(first.0, StatusCode::ACCEPTED);
    assert!(!first.1.contains_key("set-cookie"));
    let row = db
        .query_one(
            "SELECT id,password_hash,enabled FROM feature_auth.users WHERE email=$1",
            &[&email],
        )
        .await
        .unwrap();
    let user: String = row.get(0);
    let hash: String = row.get(1);
    assert!(!row.get::<_, bool>(2));
    let repeated = send(
        &router,
        post(
            "/auth/register",
            serde_json::json!({"email":email,"password":changed}),
        ),
    )
    .await;
    assert_eq!(first.2, repeated.2);
    assert!(
        db.query_one(
            "SELECT password_hash FROM feature_auth.users WHERE id=$1",
            &[&user]
        )
        .await
        .unwrap()
        .get::<_, String>(0)
            == hash
    );
    assert_eq!(
        send(
            &router,
            post(
                "/auth/login",
                serde_json::json!({"email":email,"password":password})
            )
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(
            &router,
            post(
                "/auth/password-reset/request",
                serde_json::json!({"email":email})
            )
        )
        .await
        .0,
        StatusCode::ACCEPTED
    );
    assert_eq!(
        db.query_one(
            "SELECT count(*) FROM feature_auth.mail_outbox WHERE user_id=$1 AND kind='reset'",
            &[&user]
        )
        .await
        .unwrap()
        .get::<_, i64>(0),
        0
    );
    let verification: String = db
        .query_one(
            "SELECT token FROM feature_auth.mail_outbox WHERE user_id=$1 AND kind='verify'",
            &[&user],
        )
        .await
        .unwrap()
        .get(0);
    let confirmed = send(
        &router,
        post(
            "/auth/email-verification/confirm",
            serde_json::json!({"token":verification}),
        ),
    )
    .await;
    assert_eq!(confirmed.0, StatusCode::NO_CONTENT);
    assert!(!confirmed.1.contains_key("set-cookie"));
    assert_eq!(
        send(
            &router,
            post(
                "/auth/email-verification/confirm",
                serde_json::json!({"token":verification})
            )
        )
        .await
        .2["error"]["code"],
        "INVALID_TOKEN"
    );
    let login = || {
        post(
            "/auth/login",
            serde_json::json!({"email":email,"password":password}),
        )
    };
    let first_session = send(&router, login()).await;
    let second_session = send(&router, login()).await;
    assert_eq!(first_session.0, StatusCode::OK);
    assert_eq!(second_session.0, StatusCode::OK);
    let cookies = [
        super::tests::cookie(&first_session.1),
        super::tests::cookie(&second_session.1),
    ];
    assert_eq!(
        send(
            &router,
            post(
                "/auth/password-reset/request",
                serde_json::json!({"email":email})
            )
        )
        .await
        .0,
        StatusCode::ACCEPTED
    );
    let reset: String = db
        .query_one(
            "SELECT token FROM feature_auth.mail_outbox WHERE user_id=$1 AND kind='reset'",
            &[&user],
        )
        .await
        .unwrap()
        .get(0);
    assert_eq!(
        send(
            &router,
            post(
                "/auth/password-reset/confirm",
                serde_json::json!({"token":reset,"password":"too-short"})
            )
        )
        .await
        .0,
        StatusCode::BAD_REQUEST
    );
    assert_eq!(
        send(
            &router,
            post(
                "/auth/password-reset/confirm",
                serde_json::json!({"token":"A".repeat(43),"password":changed})
            )
        )
        .await
        .2["error"]["code"],
        "INVALID_TOKEN"
    );
    assert_eq!(
        db.query_one(
            "SELECT count(*) FROM feature_auth.sessions WHERE user_id=$1",
            &[&user]
        )
        .await
        .unwrap()
        .get::<_, i64>(0),
        2
    );
    assert_eq!(
        send(
            &router,
            post(
                "/auth/password-reset/confirm",
                serde_json::json!({"token":reset,"password":changed})
            )
        )
        .await
        .0,
        StatusCode::NO_CONTENT
    );
    for cookie in cookies {
        let mut req = request("GET", "/auth/me", "");
        req.headers_mut().insert("cookie", cookie.parse().unwrap());
        assert_eq!(send(&router, req).await.0, StatusCode::UNAUTHORIZED);
    }
    assert_eq!(send(&router, login()).await.0, StatusCode::UNAUTHORIZED);
    assert_eq!(
        send(
            &router,
            post(
                "/auth/login",
                serde_json::json!({"email":email,"password":changed})
            )
        )
        .await
        .0,
        StatusCode::OK
    );
    // The gateway succeeds, then a deferred trigger rejects COMMIT. No account,
    // token, outbox entry, or attempt counter may survive an optimistic response.
    let hits: i32 = db.query_one("SELECT hits FROM feature_auth.account_attempts WHERE peer='127.0.0.1' AND action='register'", &[]).await.unwrap().get(0);
    assert_eq!(
        hits, 2,
        "reservation and application must count a request once"
    );
    db.batch_execute("CREATE FUNCTION feature_auth.test_reject_account_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected commit failure'; END $$; CREATE CONSTRAINT TRIGGER test_reject_commit AFTER INSERT OR UPDATE ON feature_auth.account_attempts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.action='register') EXECUTE FUNCTION feature_auth.test_reject_account_commit();").await.unwrap();
    let failed = send(
        &router,
        post(
            "/auth/register",
            serde_json::json!({"email":"rollback@example.com","password":password}),
        ),
    )
    .await;
    db.batch_execute("DROP TRIGGER test_reject_commit ON feature_auth.account_attempts; DROP FUNCTION feature_auth.test_reject_account_commit();").await.unwrap();
    assert_eq!(failed.0, StatusCode::SERVICE_UNAVAILABLE);
    assert!(!failed.1.contains_key("set-cookie"));
    assert_eq!(
        db.query_one(
            "SELECT count(*) FROM feature_auth.users WHERE email='rollback@example.com'",
            &[]
        )
        .await
        .unwrap()
        .get::<_, i64>(0),
        0
    );
    assert_eq!(db.query_one("SELECT hits FROM feature_auth.account_attempts WHERE peer='127.0.0.1' AND action='register'", &[]).await.unwrap().get::<_,i32>(0), hits);
    // Missing account requests have the same accepted envelope and a shared action limit.
    db.execute(
        "DELETE FROM feature_auth.account_attempts WHERE action='verify-request'",
        &[],
    )
    .await
    .unwrap();
    for _ in 0..10 {
        assert_eq!(
            send(
                &router,
                post(
                    "/auth/email-verification/request",
                    serde_json::json!({"email":"missing@example.com"})
                )
            )
            .await
            .0,
            StatusCode::ACCEPTED
        );
    }
    let limited = send(
        &router,
        post(
            "/auth/email-verification/request",
            serde_json::json!({"email":"missing@example.com"}),
        ),
    )
    .await;
    assert_eq!(limited.0, StatusCode::TOO_MANY_REQUESTS);
    assert!(
        limited.1["retry-after"]
            .to_str()
            .unwrap()
            .parse::<u64>()
            .unwrap()
            > 0
    );
    assert!(!limited.1.contains_key("set-cookie"));
    postgres::tests::assert_limited_accounts_skip_busy_hasher(&uri).await;
}

#[tokio::test]
async fn account_routes_are_hidden_in_the_default_profile() {
    let router = app(config(&[]).unwrap()).await.unwrap();
    for path in [
        "/auth/register",
        "/auth/email-verification/request",
        "/auth/email-verification/confirm",
        "/auth/password-reset/request",
        "/auth/password-reset/confirm",
    ] {
        assert_eq!(
            send(&router, request("POST", path, "{}")).await.0,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            send(&router, request("GET", path, "")).await.0,
            StatusCode::NOT_FOUND
        );
    }
}
