//! Opt-in real PostgreSQL checks. Only a disposable feature_standards_test* DB is accepted.
use super::tests::{GOOD, config, cookie, request, send};
use super::*;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use sha2::{Digest, Sha256};
use tokio_postgres::{Client, NoTls};

async fn client(value: &str) -> Client {
    let pg = postgres::validate_url(value).unwrap();
    let name = pg.get_dbname().expect("a named disposable DB is required");
    assert!(
        name.starts_with("feature_standards_test"),
        "refusing non-test DB"
    );
    let (client, connection) = pg.connect(NoTls).await.unwrap();
    tokio::spawn(async move {
        connection.await.unwrap();
    });
    client
}
async fn router(value: &str, extra: &[(&str, &str)]) -> Router {
    let mut values = vec![("AUTH_STORE", "postgres"), ("AUTH_DATABASE_URL", value)];
    values.extend_from_slice(extra);
    app(config(&values).unwrap()).await.unwrap()
}
fn me(token: &str) -> axum::http::Request<axum::body::Body> {
    let mut req = request("GET", "/auth/me", "");
    req.headers_mut().insert("cookie", token.parse().unwrap());
    req
}
fn logout(token: &str, csrf: Option<&str>) -> axum::http::Request<axum::body::Body> {
    let mut req = request("POST", "/auth/logout", "");
    req.headers_mut().insert("cookie", token.parse().unwrap());
    if let Some(csrf) = csrf {
        req.headers_mut()
            .insert("x-csrf-token", csrf.parse().unwrap());
    }
    req
}

#[tokio::test]
#[ignore = "requires a disposable AUTH_TEST_DATABASE_URL PostgreSQL database"]
async fn postgres_real_transactions_persistence_rate_limit_and_fail_closed() {
    let uri = std::env::var("AUTH_TEST_DATABASE_URL").expect("AUTH_TEST_DATABASE_URL is required");
    let db = client(&uri).await;
    // These opt-in repository integration tests use the canonical migration.
    // Load it at runtime so normal crate tests also compile outside the monorepo.
    let migration = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../features/auth/postgres/001_initial.sql"),
    )
    .expect("run this ignored integration test from a full feature-standards checkout");
    db.batch_execute(&migration).await.unwrap();
    db.batch_execute("TRUNCATE feature_auth.users CASCADE; TRUNCATE feature_auth.login_attempts;")
        .await
        .unwrap();

    let first = router(&uri, &[]).await;
    assert_eq!(
        db.query_one("SELECT count(*) FROM feature_auth.users", &[])
            .await
            .unwrap()
            .get::<_, i64>(0),
        0,
        "startup must not seed users"
    );
    assert_eq!(
        send(&first, request("GET", "/healthz", "")).await.2["profile"],
        "browser-session-v2"
    );
    // Test setup is the sole explicit owner of user seeds and fixed public test credentials.
    for (id, email, password) in [
        (
            "demo-user",
            "demo@example.com",
            "correct-horse-battery-staple",
        ),
        (
            "other-user",
            "other@example.com",
            "other-correct-horse-password",
        ),
    ] {
        let salt = [9; 16];
        let password = password.to_owned();
        let hash = tokio::task::spawn_blocking(move || derive(password.as_bytes(), &salt).unwrap())
            .await
            .unwrap();
        let phc = format!(
            "$argon2id$v=19$m=65536,t=3,p=4${}${}",
            STANDARD_NO_PAD.encode(salt),
            STANDARD_NO_PAD.encode(hash)
        );
        db.execute(
            "INSERT INTO feature_auth.users(id,email,password_hash) VALUES ($1,$2,$3)",
            &[&id, &email, &phc],
        )
        .await
        .unwrap();
    }
    let (status, headers, session, _) = send(&first, request("POST", "/auth/login", GOOD)).await;
    assert_eq!(status, StatusCode::OK);
    let first_cookie = cookie(&headers);
    let csrf = session["csrfToken"].as_str().unwrap();
    let token = first_cookie.split_once('=').unwrap().1;
    assert_ne!(token, csrf);
    let row = db.query_one("SELECT token_hash, csrf_token, user_id, expires_at-created_at = interval '1800 seconds' AS ttl FROM feature_auth.sessions", &[]).await.unwrap();
    assert_eq!(
        row.get::<_, Vec<u8>>("token_hash"),
        Sha256::digest(token.as_bytes()).to_vec()
    );
    assert_eq!(row.get::<_, String>("csrf_token"), csrf);
    assert!(row.get::<_, bool>("ttl"));
    let second = router(&uri, &[]).await;
    assert_eq!(
        send(&second, me(&first_cookie)).await.2,
        session,
        "independent instance must read persisted session"
    );
    let (_, other_headers, other, _) = send(
        &second,
        request(
            "POST",
            "/auth/login",
            r#"{"email":"other@example.com","password":"other-correct-horse-password"}"#,
        ),
    )
    .await;
    let other_cookie = cookie(&other_headers);
    assert_eq!(other["user"]["id"], "other-user");
    assert_eq!(
        send(&first, me(&first_cookie)).await.2["user"]["id"],
        "demo-user"
    );
    assert_eq!(
        send(&second, logout(&first_cookie, Some("wrong"))).await.0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(send(&first, me(&first_cookie)).await.0, StatusCode::OK);
    let mut duplicate = logout(&first_cookie, Some(csrf));
    duplicate
        .headers_mut()
        .append("x-csrf-token", csrf.parse().unwrap());
    assert_eq!(send(&first, duplicate).await.0, StatusCode::FORBIDDEN);
    assert_eq!(
        send(&second, logout(&first_cookie, Some(csrf))).await.0,
        StatusCode::NO_CONTENT
    );
    assert_eq!(
        send(&first, me(&first_cookie)).await.0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(send(&first, me(&other_cookie)).await.0, StatusCode::OK);

    // A restarted router observes the same DB row, and rotation removes only the supplied cookie.
    drop(first);
    let restarted = router(&uri, &[]).await;
    assert_eq!(send(&restarted, me(&other_cookie)).await.2, other);
    let mut rotate = request("POST", "/auth/login", GOOD);
    rotate
        .headers_mut()
        .insert("cookie", other_cookie.parse().unwrap());
    let (_, rotated_headers, rotated, _) = send(&restarted, rotate).await;
    let rotated_cookie = cookie(&rotated_headers);
    assert_eq!(
        send(&second, me(&other_cookie)).await.0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(rotated["user"]["id"], "demo-user");
    db.execute(
        "UPDATE feature_auth.users SET enabled=false WHERE id='demo-user'",
        &[],
    )
    .await
    .unwrap();
    assert_eq!(
        send(&second, me(&rotated_cookie)).await.0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(&second, request("POST", "/auth/login", GOOD)).await.2["error"]["code"],
        "INVALID_CREDENTIALS"
    );
    db.execute(
        "UPDATE feature_auth.users SET enabled=true WHERE id='demo-user'",
        &[],
    )
    .await
    .unwrap();
    db.execute("UPDATE feature_auth.sessions SET created_at=clock_timestamp()-interval '2 hours', expires_at=clock_timestamp()-interval '1 hour'", &[]).await.unwrap();
    assert_eq!(
        send(&second, me(&rotated_cookie)).await.0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        send(&second, logout(&rotated_cookie, None)).await.0,
        StatusCode::NO_CONTENT
    );
    db.execute(
        "UPDATE feature_auth.users SET password_hash='unsupported' WHERE id='demo-user'",
        &[],
    )
    .await
    .unwrap();
    let (status, headers, error, _) = send(&second, request("POST", "/auth/login", GOOD)).await;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(error["error"]["code"], "STORAGE_UNAVAILABLE");
    assert!(!headers.contains_key("set-cookie"));

    db.execute("TRUNCATE feature_auth.login_attempts", &[])
        .await
        .unwrap();
    let limited_one = router(&uri, &[("AUTH_RATE_LIMIT_MAX", "2")]).await;
    let limited_two = router(&uri, &[("AUTH_RATE_LIMIT_MAX", "2")]).await;
    let mut jobs = Vec::new();
    for index in 0..5 {
        let app = if index % 2 == 0 {
            limited_one.clone()
        } else {
            limited_two.clone()
        };
        jobs.push(tokio::spawn(async move {
            send(
                &app,
                request(
                    "POST",
                    "/auth/login",
                    r#"{"email":"absent@example.com","password":"wrong"}"#,
                ),
            )
            .await
        }));
    }
    let mut invalid = 0;
    let mut limited = 0;
    for job in jobs {
        let (status, headers, _, _) = job.await.unwrap();
        match status {
            StatusCode::UNAUTHORIZED => invalid += 1,
            StatusCode::TOO_MANY_REQUESTS => {
                limited += 1;
                assert!(
                    headers["retry-after"]
                        .to_str()
                        .unwrap()
                        .parse::<u64>()
                        .unwrap()
                        > 0
                );
            }
            status => panic!("unexpected {status}"),
        }
    }
    assert_eq!((invalid, limited), (2, 3));
    assert_eq!(
        db.query_one("SELECT failures FROM feature_auth.login_attempts", &[])
            .await
            .unwrap()
            .get::<_, i64>(0),
        2
    );
    db.execute(
        "UPDATE feature_auth.login_attempts SET expires_at=clock_timestamp()-interval '1 second'",
        &[],
    )
    .await
    .unwrap();
    assert_eq!(
        send(
            &limited_two,
            request(
                "POST",
                "/auth/login",
                r#"{"email":"absent@example.com","password":"wrong"}"#
            )
        )
        .await
        .0,
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        db.query_one("SELECT failures FROM feature_auth.login_attempts", &[])
            .await
            .unwrap()
            .get::<_, i64>(0),
        1
    );

    // Remove tables temporarily to observe actual driver failures without stopping shared PostgreSQL.
    db.batch_execute("ALTER TABLE feature_auth.sessions RENAME TO sessions_unavailable; ALTER TABLE feature_auth.schema_version RENAME TO schema_version_unavailable;").await.unwrap();
    let (status, headers, error, _) = send(&second, me(&rotated_cookie)).await;
    let (health_status, health_headers, health_error, _) =
        send(&second, request("GET", "/healthz", "")).await;
    let (logout_status, logout_headers, logout_error, _) =
        send(&second, logout(&rotated_cookie, None)).await;
    let startup =
        app(config(&[("AUTH_STORE", "postgres"), ("AUTH_DATABASE_URL", &uri)]).unwrap()).await;
    db.batch_execute("ALTER TABLE feature_auth.sessions_unavailable RENAME TO sessions; ALTER TABLE feature_auth.schema_version_unavailable RENAME TO schema_version;").await.unwrap();
    for (actual, headers, body) in [
        (status, headers, error),
        (health_status, health_headers, health_error),
        (logout_status, logout_headers, logout_error),
    ] {
        assert_eq!(actual, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(body["error"]["code"], "STORAGE_UNAVAILABLE");
        assert_eq!(headers["cache-control"], "no-store");
        assert_eq!(headers["x-content-type-options"], "nosniff");
        assert!(!headers.contains_key("set-cookie"));
        assert!(!body.to_string().contains(&uri));
    }
    assert!(startup.is_err());
    // Restore a clean reusable fixture for the next invocation.
    db.batch_execute("TRUNCATE feature_auth.users CASCADE; TRUNCATE feature_auth.login_attempts;")
        .await
        .unwrap();
    assert_eq!(
        send(&second, request("GET", "/healthz", "")).await.0,
        StatusCode::OK
    );
}
