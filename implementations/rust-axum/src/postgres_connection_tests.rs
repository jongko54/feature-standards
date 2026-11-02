//! Socket-level regressions for request-owned PostgreSQL connections.
use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;
use tokio::task::JoinHandle;

#[derive(Clone, Copy)]
enum StopAt {
    Settings,
    Query,
    SettingsError,
}

struct Blackhole {
    query_seen: oneshot::Receiver<()>,
    peer_closed: oneshot::Receiver<()>,
    task: JoinHandle<()>,
}
impl Drop for Blackhole {
    fn drop(&mut self) {
        self.task.abort();
    }
}
impl Blackhole {
    async fn wait_for_query(&mut self) {
        tokio::time::timeout(Duration::from_secs(2), &mut self.query_seen)
            .await
            .expect("client never sent the blackholed query")
            .expect("mock server failed before receiving the query");
    }
    async fn assert_peer_closed(&mut self) {
        tokio::time::timeout(Duration::from_secs(1), &mut self.peer_closed)
            .await
            .expect("request ended but PostgreSQL peer socket stayed open")
            .expect("mock server failed before observing peer EOF");
    }
}

async fn backend(socket: &mut TcpStream, tag: u8, payload: &[u8]) {
    socket.write_u8(tag).await.unwrap();
    socket
        .write_u32((payload.len() + 4).try_into().unwrap())
        .await
        .unwrap();
    socket.write_all(payload).await.unwrap();
}
async fn query(socket: &mut TcpStream) -> Vec<u8> {
    assert_eq!(socket.read_u8().await.unwrap(), b'Q');
    let length = socket.read_u32().await.unwrap();
    assert!((4..4096).contains(&length));
    let mut payload = vec![0; (length - 4) as usize];
    socket.read_exact(&mut payload).await.unwrap();
    payload
}

async fn blackhole(stop_at: StopAt) -> (PostgresStore, Blackhole) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (query_sent, query_seen) = oneshot::channel();
    let (closed_sent, peer_closed) = oneshot::channel();
    let task = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let length = socket.read_u32().await.unwrap();
        assert!((8..4096).contains(&length));
        let mut startup = vec![0; (length - 4) as usize];
        socket.read_exact(&mut startup).await.unwrap();
        assert_eq!(&startup[..4], &[0, 3, 0, 0]);
        backend(&mut socket, b'R', &[0, 0, 0, 0]).await; // AuthenticationOk
        backend(&mut socket, b'Z', b"I").await; // ReadyForQuery
        assert!(
            query(&mut socket)
                .await
                .starts_with(b"SET statement_timeout")
        );
        if matches!(stop_at, StopAt::Query) {
            backend(&mut socket, b'C', b"SET\0").await;
            backend(&mut socket, b'C', b"SET\0").await;
            backend(&mut socket, b'Z', b"I").await;
            assert_eq!(query(&mut socket).await, b"SELECT 1\0");
        }
        query_sent.send(()).unwrap();
        if matches!(stop_at, StopAt::SettingsError) {
            // Return an error but withhold ReadyForQuery so outstanding driver work remains.
            backend(
                &mut socket,
                b'E',
                b"SERROR\0CXX000\0Mfixture rejected SET\0\0",
            )
            .await;
        }
        // Deliberately never answer the pending query. Observe the actual TCP lifetime.
        let mut bytes = [0; 1024];
        loop {
            if socket.read(&mut bytes).await.unwrap() == 0 {
                closed_sent.send(()).unwrap();
                return;
            }
        }
    });
    let store = PostgresStore {
        config: validate_url(&format!(
            "postgresql://fixture@{address}/feature_standards_test?sslmode=disable"
        ))
        .unwrap(),
        tls: None,
        account_lifecycle: false,
        hash_slots: Arc::new(Semaphore::new(1)),
        db_slots: Semaphore::new(8),
        dummy: StoredHash {
            salt: [0; 16],
            hash: [0; 32],
        },
        ttl: 1800,
        window: 60,
        max: 5,
    };
    (
        store,
        Blackhole {
            query_seen,
            peer_closed,
            task,
        },
    )
}

#[tokio::test]
async fn outer_timeout_closes_blackholed_settings_socket() {
    let (store, mut server) = blackhole(StopAt::Settings).await;
    {
        let request = store.client();
        tokio::pin!(request);
        tokio::select! {
            _ = &mut request => panic!("blackholed SET unexpectedly completed"),
            () = server.wait_for_query() => {},
        }
        assert!(
            tokio::time::timeout(Duration::from_millis(40), request)
                .await
                .is_err()
        );
    }
    server.assert_peer_closed().await;
}

#[tokio::test]
async fn cancelled_request_closes_blackholed_query_socket() {
    let (store, mut server) = blackhole(StopAt::Query).await;
    let request = tokio::spawn(async move {
        let client = store.client().await?;
        client
            .batch_execute("SELECT 1")
            .await
            .map_err(|_| UNAVAILABLE)
    });
    server.wait_for_query().await;
    request.abort();
    assert!(request.await.unwrap_err().is_cancelled());
    server.assert_peer_closed().await;
}

#[tokio::test]
async fn settings_error_closes_pending_driver_socket() {
    let (store, mut server) = blackhole(StopAt::SettingsError).await;
    let request = tokio::spawn(async move { store.client().await });
    server.wait_for_query().await;
    assert!(matches!(request.await.unwrap(), Err(UNAVAILABLE)));
    server.assert_peer_closed().await;
}
