use feature_standards_auth::Config;
use std::net::SocketAddr;

#[tokio::main]
async fn main() -> Result<(), String> {
    let config = Config::from_env()?;
    let address = (config.host.clone(), config.port);
    let router = feature_standards_consumer_rust::app(config).await?;
    let listener = tokio::net::TcpListener::bind((address.0.as_str(), address.1))
        .await
        .map_err(|_| "failed to bind AUTH_HOST:AUTH_PORT")?;
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
