//! Real TLS boundary checks, invoked by tests/postgres_tls.py with owned databases.
use super::*;

fn fixture(name: &str) -> String {
    let value = std::env::var(name).expect("run tests/postgres_tls.py to create TLS fixtures");
    let uri = url::Url::parse(&value).unwrap();
    assert!(matches!(uri.host_str(), Some("localhost" | "127.0.0.1")));
    assert!(uri.port().is_some());
    assert_eq!(uri.path(), "/feature_standards_test_tls");
    assert!(
        uri.query_pairs()
            .all(|(key, _)| matches!(key.as_ref(), "sslmode" | "sslrootcert"))
    );
    value
}

fn settings(value: &str) -> Config {
    super::super::tests::config(&[("AUTH_STORE", "postgres"), ("AUTH_DATABASE_URL", value)])
        .unwrap()
}

#[tokio::test]
#[ignore = "requires the isolated TLS PostgreSQL fixtures from tests/postgres_tls.py"]
async fn postgres_tls_certificate_boundaries() {
    let good = fixture("AUTH_TLS_TEST_GOOD_URL");
    let store = PostgresStore::connect(&settings(&good)).await.unwrap();
    store.ready().await.unwrap();
    let client = store.client().await.unwrap();
    assert!(
        client
            .query_one(
                "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()",
                &[]
            )
            .await
            .unwrap()
            .get::<_, bool>(0),
        "trusted TLS connection must actually be encrypted"
    );
    // The non-TLS fixture is a healthy, migrated database. Its rejection below
    // therefore proves required TLS did not silently fall back to plaintext.
    let plaintext = fixture("AUTH_TLS_TEST_PLAINTEXT_URL");
    let mut local = url::Url::parse(&plaintext).unwrap();
    local.set_query(Some("sslmode=disable"));
    let plain_store = PostgresStore::connect(&settings(local.as_str()))
        .await
        .unwrap();
    plain_store.ready().await.unwrap();
    assert!(
        !plain_store
            .client()
            .await
            .unwrap()
            .query_one(
                "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()",
                &[]
            )
            .await
            .unwrap()
            .get::<_, bool>(0)
    );
    for (name, reason) in [
        ("AUTH_TLS_TEST_WRONG_CA_URL", "untrusted certificate chain"),
        (
            "AUTH_TLS_TEST_WRONG_HOST_URL",
            "certificate hostname mismatch",
        ),
        ("AUTH_TLS_TEST_PLAINTEXT_URL", "server rejected TLS"),
    ] {
        let value = fixture(name);
        let error = PostgresStore::connect(&settings(&value))
            .await
            .err()
            .unwrap_or_else(|| panic!("accepted {reason}"));
        assert!(!error.contains(&value));
        assert!(!error.contains(".pem"));
        assert_eq!(
            error,
            "authentication store unavailable or schema version mismatch"
        );
    }
}
