use axum::Router;
use feature_standards_auth::Config;
use feature_standards_core::authorization::Principal;
use feature_standards_core_consumer_rust::{MembershipProvider, MembershipUnavailable};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::sync::oneshot;
use tokio::task::JoinHandle;

const ORIGIN: &str = "http://127.0.0.1:5173";

#[derive(Clone)]
struct Membership {
    roles: Vec<String>,
    unavailable: bool,
    missing: bool,
    mismatched: bool,
}

struct Server {
    address: SocketAddr,
    stop: Option<oneshot::Sender<()>>,
    task: JoinHandle<()>,
    membership: Arc<Mutex<Membership>>,
}

struct Response {
    status: u16,
    headers: BTreeMap<String, String>,
    body: Vec<u8>,
}

impl Response {
    fn json(&self) -> Value {
        serde_json::from_slice(&self.body).unwrap()
    }

    fn error(&self, status: u16, code: &str) {
        assert_eq!(
            self.status,
            status,
            "{}",
            String::from_utf8_lossy(&self.body)
        );
        assert_eq!(self.json()["error"]["code"], code);
        self.private_headers();
        assert!(!String::from_utf8_lossy(&self.body).contains("private-provider-detail"));
    }

    fn private_headers(&self) {
        assert_eq!(self.headers["cache-control"], "no-store");
        assert_eq!(self.headers["x-content-type-options"], "nosniff");
    }
}

impl Server {
    async fn start() -> Self {
        Self::start_with_documents(None).await
    }

    async fn start_with_documents(documents: Option<Vec<Value>>) -> Self {
        let membership = Arc::new(Mutex::new(Membership {
            roles: vec!["viewer".into()],
            unavailable: false,
            missing: false,
            mismatched: false,
        }));
        let state = membership.clone();
        let provider: MembershipProvider = Arc::new(move |user| {
            let current = state.lock().unwrap().clone();
            if current.unavailable {
                return Err(MembershipUnavailable);
            }
            if current.missing {
                return Ok(None);
            }
            Ok(Some(Principal {
                subject_id: if current.mismatched {
                    "other-user".into()
                } else {
                    user.id.clone()
                },
                tenant_id: "tenant-a".into(),
                roles: current.roles,
            }))
        });
        let config = config();
        let app = match documents {
            Some(documents) => feature_standards_core_consumer_rust::app_with_documents(
                config, provider, documents,
            )
            .await
            .unwrap(),
            None => feature_standards_core_consumer_rust::app_with_membership(config, provider)
                .await
                .unwrap(),
        };
        Self::serve(app, membership).await
    }

    async fn serve(app: Router, membership: Arc<Mutex<Membership>>) -> Self {
        // Keep the port-zero listener open through serving: no free-port race.
        let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0))
            .await
            .unwrap();
        let address = listener.local_addr().unwrap();
        let (stop, stopped) = oneshot::channel();
        let task = tokio::spawn(async move {
            axum::serve(
                listener,
                app.into_make_service_with_connect_info::<SocketAddr>(),
            )
            .with_graceful_shutdown(async {
                let _ = stopped.await;
            })
            .await
            .unwrap();
        });
        Self {
            address,
            stop: Some(stop),
            task,
            membership,
        }
    }

    async fn request(
        &self,
        method: &str,
        path: &str,
        headers: &[(&str, &str)],
        body: &str,
    ) -> Response {
        let mut stream = tokio::net::TcpStream::connect(self.address).await.unwrap();
        let mut request = format!(
            "{method} {path} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\nOrigin: {ORIGIN}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n",
            self.address,
            body.len()
        );
        for (name, value) in headers {
            request.push_str(&format!("{name}: {value}\r\n"));
        }
        request.push_str("\r\n");
        request.push_str(body);
        stream.write_all(request.as_bytes()).await.unwrap();
        let mut bytes = Vec::new();
        tokio::time::timeout(Duration::from_secs(15), stream.read_to_end(&mut bytes))
            .await
            .unwrap()
            .unwrap();
        assert!(bytes.len() < 65_536, "Unexpected response size");
        let split = bytes
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .unwrap();
        let mut lines = std::str::from_utf8(&bytes[..split]).unwrap().split("\r\n");
        let status = lines
            .next()
            .unwrap()
            .split_whitespace()
            .nth(1)
            .unwrap()
            .parse()
            .unwrap();
        let headers = lines
            .map(|line| {
                let (key, value) = line.split_once(':').unwrap();
                (key.to_ascii_lowercase(), value.trim().to_owned())
            })
            .collect::<BTreeMap<_, _>>();
        assert!(
            !headers.contains_key("transfer-encoding"),
            "Test responses must have bounded bodies"
        );
        Response {
            status,
            headers,
            body: bytes[split + 4..].to_vec(),
        }
    }

    async fn login(&self) -> (String, String) {
        let response = self
            .request(
                "POST",
                "/auth/login",
                &[],
                r#"{"email":"demo@example.com","password":"correct-horse-battery-staple"}"#,
            )
            .await;
        assert_eq!(response.status, 200);
        let cookie = response.headers["set-cookie"]
            .split(';')
            .next()
            .unwrap()
            .to_owned();
        let csrf = response.json()["csrfToken"].as_str().unwrap().to_owned();
        (cookie, csrf)
    }

    async fn close(mut self) {
        let _ = self.stop.take().unwrap().send(());
        tokio::time::timeout(Duration::from_secs(5), &mut self.task)
            .await
            .unwrap()
            .unwrap();
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        // Assertion failure must not leave the owned listener/server running.
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        self.task.abort();
    }
}

fn config() -> Config {
    Config::from_lookup(|key| match key {
        "AUTH_DEMO" => Some("true".into()),
        "AUTH_COOKIE_SECURE" => Some("false".into()),
        "AUTH_ALLOWED_ORIGIN" => Some(ORIGIN.into()),
        "AUTH_RATE_LIMIT_MAX" => Some("1000".into()),
        _ => None,
    })
    .unwrap()
}

#[tokio::test]
async fn anonymous_and_forged_sessions_are_rejected_over_tcp() {
    let server = Server::start().await;
    for path in ["/api/documents", "/api/documents/own-a"] {
        server
            .request("GET", path, &[], "")
            .await
            .error(401, "UNAUTHENTICATED");
        server
            .request("GET", path, &[("Cookie", "fs_session=forged")], "")
            .await
            .error(401, "UNAUTHENTICATED");
    }
    server.close().await;
}

#[tokio::test]
async fn ownership_and_tenant_scope_hide_records_and_totals() {
    let server = Server::start().await;
    let (cookie, _) = server.login().await;
    let headers = [("Cookie", cookie.as_str())];
    let own = server
        .request("GET", "/api/documents/own-a", &headers, "")
        .await;
    assert_eq!(own.status, 200);
    assert_eq!(
        own.json(),
        json!({"id":"own-a","name":"Alpha","score":2,"active":true})
    );
    own.private_headers();
    for id in ["other-owner", "other-tenant", "missing", "%FF", "%6dissing"] {
        server
            .request("GET", &format!("/api/documents/{id}"), &headers, "")
            .await
            .error(403, "FORBIDDEN");
    }
    let list = server
        .request("GET", "/api/documents?sort=-score&limit=1", &headers, "")
        .await;
    assert_eq!(list.status, 200);
    assert_eq!(list.json()["total"], 2);
    assert_eq!(list.json()["items"][0]["id"], "own-a");
    assert_eq!(list.json()["nextOffset"], 1);
    assert!(list.json()["items"][0].get("tenantId").is_none());
    list.private_headers();
    let next = server
        .request(
            "GET",
            "/api/documents?sort=-score&limit=1&offset=1",
            &headers,
            "",
        )
        .await;
    assert_eq!(next.json()["items"][0]["id"], "own-b");
    assert!(next.json()["nextOffset"].is_null());
    let hidden = server
        .request("GET", "/api/documents?filter.name=Private", &headers, "")
        .await;
    assert_eq!(hidden.json()["total"], 0);
    server.close().await;
}

#[tokio::test]
async fn raw_query_is_strict_and_filters_remain_typed() {
    let server = Server::start().await;
    let (cookie, _) = server.login().await;
    let headers = [("Cookie", cookie.as_str())];
    for query in [
        "limit=01",
        "limit=1&%6cimit=2",
        "sort=unknown",
        "filter.active=1",
        "filter.score=02",
        "filter.name=%FF",
        "roles=admin",
        "limit=1&&offset=0",
    ] {
        server
            .request("GET", &format!("/api/documents?{query}"), &headers, "")
            .await
            .error(400, "INVALID_LIST_QUERY");
    }
    let response = server
        .request(
            "GET",
            "/api/documents?filter.active=true&filter.score=2",
            &headers,
            "",
        )
        .await;
    assert_eq!(response.status, 200);
    assert_eq!(response.json()["total"], 1);
    assert_eq!(response.json()["items"][0]["id"], "own-a");
    let empty = server
        .request("GET", "/api/documents?offset=100", &headers, "")
        .await;
    assert_eq!(empty.json()["items"], json!([]));
    assert_eq!(empty.json()["total"], 2);
    server.close().await;
}

#[tokio::test]
async fn current_membership_revocation_and_spoofing_cannot_restore_access() {
    let server = Server::start().await;
    let (cookie, _) = server.login().await;
    server.membership.lock().unwrap().roles.clear();
    let headers = [
        ("Cookie", cookie.as_str()),
        ("X-Role", "admin"),
        ("X-Roles", "viewer"),
        ("X-Tenant-Id", "tenant-b"),
        ("X-Subject-Id", "other-user"),
    ];
    for path in [
        "/api/documents",
        "/api/documents/own-a",
        "/api/documents?roles=viewer",
    ] {
        server
            .request("GET", path, &headers, "")
            .await
            .error(403, "FORBIDDEN");
    }
    server.membership.lock().unwrap().roles = vec!["viewer".into()];
    assert_eq!(
        server
            .request("GET", "/api/documents/own-a", &headers, "")
            .await
            .status,
        200
    );
    server.close().await;
}

#[tokio::test]
async fn provider_failures_missing_membership_and_subject_mismatch_fail_closed() {
    let server = Server::start().await;
    let (cookie, _) = server.login().await;
    let headers = [("Cookie", cookie.as_str())];
    server.membership.lock().unwrap().unavailable = true;
    for path in ["/api/documents", "/api/documents/own-a"] {
        server
            .request("GET", path, &headers, "")
            .await
            .error(503, "AUTHORIZATION_UNAVAILABLE");
    }
    {
        let mut membership = server.membership.lock().unwrap();
        membership.unavailable = false;
        membership.missing = true;
    }
    server
        .request("GET", "/api/documents", &headers, "")
        .await
        .error(403, "FORBIDDEN");
    {
        let mut membership = server.membership.lock().unwrap();
        membership.missing = false;
        membership.mismatched = true;
    }
    server
        .request("GET", "/api/documents/own-a", &headers, "")
        .await
        .error(403, "FORBIDDEN");
    server.close().await;
}

#[tokio::test]
async fn csrf_logout_preserves_then_revokes_the_real_shared_session() {
    let server = Server::start().await;
    let (cookie, csrf) = server.login().await;
    let headers = [("Cookie", cookie.as_str())];
    let rejected = server.request("POST", "/auth/logout", &headers, "").await;
    assert_eq!(rejected.status, 403);
    assert_eq!(rejected.json()["error"]["code"], "CSRF_INVALID");
    assert_eq!(
        server
            .request("GET", "/api/documents", &headers, "")
            .await
            .status,
        200
    );
    let logout = server
        .request(
            "POST",
            "/auth/logout",
            &[("Cookie", cookie.as_str()), ("X-CSRF-Token", csrf.as_str())],
            "",
        )
        .await;
    assert_eq!(logout.status, 204);
    server
        .request("GET", "/api/documents", &headers, "")
        .await
        .error(401, "UNAUTHENTICATED");
    server
        .request("GET", "/api/documents/own-a", &headers, "")
        .await
        .error(401, "UNAUTHENTICATED");
    server.close().await;
}

#[tokio::test]
async fn malformed_trusted_data_returns_a_fixed_private_error() {
    let mut documents = feature_standards_core_consumer_rust::demo_documents();
    documents[3].as_object_mut().unwrap().remove("name");
    let server = Server::start_with_documents(Some(documents)).await;
    let (cookie, _) = server.login().await;
    let headers = [("Cookie", cookie.as_str())];
    for path in ["/api/documents", "/api/documents/own-a"] {
        server
            .request("GET", path, &headers, "")
            .await
            .error(500, "INVALID_LIST_DATA");
    }
    server.close().await;

    let mut documents = feature_standards_core_consumer_rust::demo_documents();
    documents[3]["score"] = json!("private-provider-detail");
    let server = Server::start_with_documents(Some(documents)).await;
    let (cookie, _) = server.login().await;
    server
        .request(
            "GET",
            "/api/documents?sort=score",
            &[("Cookie", cookie.as_str())],
            "",
        )
        .await
        .error(500, "INVALID_LIST_DATA");
    server.close().await;
}

#[tokio::test]
async fn routing_rejections_keep_product_security_headers() {
    let server = Server::start().await;
    let missing = server.request("GET", "/api/missing", &[], "").await;
    assert_eq!(missing.status, 404);
    missing.private_headers();
    let method = server.request("POST", "/api/documents", &[], "").await;
    assert_eq!(method.status, 405);
    method.private_headers();
    server.close().await;
}
