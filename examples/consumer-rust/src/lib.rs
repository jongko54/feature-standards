use axum::extract::State;
use axum::http::HeaderMap;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use feature_standards_auth::{AuthService, Config, app_with_service, current_user};
use serde_json::json;

/// Mount application routes and auth routes on the same library-owned session store.
pub async fn app(mut config: Config) -> Result<Router, String> {
    let service = AuthService::from_config(&mut config).await?;
    let protected = Router::new()
        .route("/api/profile", get(profile))
        .with_state(service.clone());
    Ok(protected.merge(app_with_service(config, service)))
}

async fn profile(State(service): State<AuthService>, headers: HeaderMap) -> Response {
    match current_user(&service, &headers).await {
        Ok(user) => (
            [
                ("cache-control", "no-store"),
                ("x-content-type-options", "nosniff"),
            ],
            Json(json!({"user": user})),
        )
            .into_response(),
        Err(response) => response,
    }
}
