use feature_standards_auth::Config;
use std::net::SocketAddr;

#[tokio::main]
async fn main() -> Result<(), String> {
    if std::env::var("AUTH_DEMO").as_deref() != Ok("true") {
        return Err("This fixture consumer requires explicit AUTH_DEMO=true".into());
    }
    let mut config = Config::from_env()?;
    config.host = "127.0.0.1".into();
    let port = match std::env::var("PORT") {
        Ok(value) => value
            .parse::<u16>()
            .ok()
            .filter(|port| *port != 0)
            .ok_or("PORT must be between 1 and 65535")?,
        Err(std::env::VarError::NotPresent) if std::env::var_os("AUTH_PORT").is_some() => {
            config.port
        }
        Err(std::env::VarError::NotPresent) => 8013,
        Err(_) => return Err("PORT must be UTF-8".into()),
    };
    let router = feature_standards_core_consumer_rust::app(config).await?;
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", port))
        .await
        .map_err(|_| "Failed to bind loopback PORT")?;
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
