use feature_standards_auth::Config;
use std::net::SocketAddr;

#[tokio::main]
async fn main() -> Result<(), String> {
    if std::env::var("AUTH_STORE").is_ok_and(|value| value != "memory")
        || std::env::var("AUTH_ACCOUNT_LIFECYCLE").as_deref() == Ok("true")
    {
        return Err("This starter supports browser-session-v1 memory sessions only".into());
    }
    let config = Config::from_env()?;
    let demo = std::env::var("AUTH_DEMO").as_deref() == Ok("true");
    let address = (config.host.clone(), config.port);
    if demo && !["127.0.0.1", "localhost", "::1"].contains(&address.0.as_str()) {
        return Err("Demo mode requires a loopback AUTH_HOST".into());
    }
    let router = feature_core_generated::app(config, demo).await?;
    let listener = tokio::net::TcpListener::bind((address.0.as_str(), address.1))
        .await
        .map_err(|_| "Failed to bind AUTH_HOST:AUTH_PORT")?;
    axum::serve(
        listener,
        router.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(async {
        let _ = tokio::signal::ctrl_c().await;
    })
    .await
    .map_err(|_| "HTTP server failed".into())
}
