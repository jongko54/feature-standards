//! Real auth sessions composed with server-owned membership and core contracts.
use axum::extract::{Path, RawQuery, Request, State, rejection::PathRejection};
use axum::http::{HeaderMap, HeaderValue, Method, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum::{Json, Router};
use feature_standards_auth::{AuthService, Config, SessionUser, app_with_service, current_user};
use feature_standards_core::authorization::{Grant, Policy, Principal, Resource};
use feature_standards_core::listing::{ListingError, Schema, page, parse_query};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;

/// A membership backend must report failure without exposing private diagnostics.
#[derive(Debug)]
pub struct MembershipUnavailable;

/// Application-construction injection, never populated from HTTP headers/query.
pub type MembershipProvider =
    Arc<dyn Fn(&SessionUser) -> Result<Option<Principal>, MembershipUnavailable> + Send + Sync>;

struct ProductState {
    auth: AuthService,
    membership: MembershipProvider,
    documents: Vec<Value>,
    policy: Policy,
    schema: Schema,
}

/// Public demo fixture membership. Replace with the application's current lookup.
pub fn demo_membership(user: &SessionUser) -> Result<Option<Principal>, MembershipUnavailable> {
    Ok((user.id == "demo-user").then(|| Principal {
        subject_id: user.id.clone(),
        tenant_id: "tenant-a".into(),
        roles: vec!["viewer".into()],
    }))
}

pub fn demo_documents() -> Vec<Value> {
    vec![
        json!({"id":"own-b","name":"Beta","score":2,"active":false,"tenantId":"tenant-a","ownerId":"demo-user"}),
        json!({"id":"other-owner","name":"Private","score":10,"active":true,"tenantId":"tenant-a","ownerId":"other-user"}),
        json!({"id":"other-tenant","name":"Secret","score":99,"active":true,"tenantId":"tenant-b","ownerId":"demo-user"}),
        json!({"id":"own-a","name":"Alpha","score":2,"active":true,"tenantId":"tenant-a","ownerId":"demo-user"}),
    ]
}

/// Demo fixtures are opt-in; normal startup grants no product membership.
pub async fn app(config: Config, demo: bool) -> Result<Router, String> {
    if demo {
        app_with_documents(config, Arc::new(demo_membership), demo_documents()).await
    } else {
        app_with_membership(config, Arc::new(|_| Ok(None))).await
    }
}

/// Replace this lookup with a trusted current-membership service.
/// The default document snapshot remains empty until explicitly supplied.
pub async fn app_with_membership(
    config: Config,
    membership: MembershipProvider,
) -> Result<Router, String> {
    app_with_documents(config, membership, Vec::new()).await
}

/// Supply an immutable, server-owned document snapshot during construction.
/// No HTTP route can replace data, membership, roles or the policy.
pub async fn app_with_documents(
    mut config: Config,
    membership: MembershipProvider,
    documents: Vec<Value>,
) -> Result<Router, String> {
    let auth = AuthService::from_config(&mut config).await?;
    let policy = Policy::new(vec![
        Grant {
            role: "viewer".into(),
            permission: "documents:list".into(),
            scope: "tenant".into(),
        },
        Grant {
            role: "viewer".into(),
            permission: "documents:read".into(),
            scope: "owner".into(),
        },
    ])
    .map_err(|_| "Invalid application authorization policy")?;
    let schema = Schema::new(
        BTreeMap::from([
            ("id".into(), "string".into()),
            ("name".into(), "string".into()),
            ("score".into(), "integer".into()),
            ("active".into(), "boolean".into()),
        ]),
        BTreeMap::from([
            ("name".into(), "string".into()),
            ("score".into(), "integer".into()),
            ("active".into(), "boolean".into()),
        ]),
    )
    .map_err(|_| "Invalid application listing schema")?;
    let product = Router::new()
        .route("/api/profile", get(profile))
        .route("/api/documents", get(list_documents))
        .route("/api/documents/{id}", get(get_document))
        .with_state(Arc::new(ProductState {
            auth: auth.clone(),
            membership,
            documents,
            policy,
            schema,
        }));
    Ok(product
        .merge(app_with_service(config, auth))
        .layer(middleware::from_fn(product_headers)))
}

async fn product_headers(request: Request, next: Next) -> Response {
    let product = request.uri().path() == "/api" || request.uri().path().starts_with("/api/");
    let mut response = if product && request.method() != Method::GET {
        let mut response = error(StatusCode::METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED");
        response
            .headers_mut()
            .insert("allow", HeaderValue::from_static("GET"));
        response
    } else {
        next.run(request).await
    };
    if product {
        response
            .headers_mut()
            .insert("cache-control", HeaderValue::from_static("no-store"));
        response.headers_mut().insert(
            "x-content-type-options",
            HeaderValue::from_static("nosniff"),
        );
    }
    response
}

fn error(status: StatusCode, code: &str) -> Response {
    (
        status,
        Json(json!({"error":{"code":code,"message":"Request could not be completed."}})),
    )
        .into_response()
}

fn listing_error(failure: ListingError) -> Response {
    error(
        if failure == ListingError::InvalidQuery {
            StatusCode::BAD_REQUEST
        } else {
            StatusCode::INTERNAL_SERVER_ERROR
        },
        failure.code(),
    )
}

async fn principal_for(state: &ProductState, headers: &HeaderMap) -> Result<Principal, Response> {
    let user = current_user(&state.auth, headers).await?;
    match (state.membership)(&user) {
        Ok(Some(principal)) if principal.subject_id == user.id => Ok(principal),
        Ok(_) => Err(error(StatusCode::FORBIDDEN, "FORBIDDEN")),
        Err(_) => Err(error(
            StatusCode::SERVICE_UNAVAILABLE,
            "AUTHORIZATION_UNAVAILABLE",
        )),
    }
}

async fn profile(State(state): State<Arc<ProductState>>, headers: HeaderMap) -> Response {
    match current_user(&state.auth, &headers).await {
        Ok(user) => Json(json!({"user": user})).into_response(),
        Err(response) => response,
    }
}

fn resource(document: &Value) -> Result<Resource, ListingError> {
    Ok(Resource {
        tenant_id: document["tenantId"]
            .as_str()
            .ok_or(ListingError::InvalidData)?
            .to_owned(),
        owner_id: Some(
            document["ownerId"]
                .as_str()
                .ok_or(ListingError::InvalidData)?
                .to_owned(),
        ),
    })
}

fn public_document(document: &Value) -> Result<Value, ListingError> {
    let object = document.as_object().ok_or(ListingError::InvalidData)?;
    let mut output = serde_json::Map::new();
    for key in ["id", "name", "score", "active"] {
        output.insert(
            key.into(),
            object.get(key).ok_or(ListingError::InvalidData)?.clone(),
        );
    }
    Ok(Value::Object(output))
}

async fn list_documents(
    State(state): State<Arc<ProductState>>,
    RawQuery(raw): RawQuery,
    headers: HeaderMap,
) -> Response {
    let principal = match principal_for(&state, &headers).await {
        Ok(principal) => principal,
        Err(response) => return response,
    };
    if !state
        .policy
        .decide(
            Some(&principal),
            "documents:list",
            &Resource {
                tenant_id: principal.tenant_id.clone(),
                owner_id: None,
            },
        )
        .allowed
    {
        return error(StatusCode::FORBIDDEN, "FORBIDDEN");
    }
    let result = (|| {
        // Authorization visibility precedes totals, raw-query parsing and paging.
        let mut visible = Vec::new();
        for document in &state.documents {
            if state
                .policy
                .decide(Some(&principal), "documents:read", &resource(document)?)
                .allowed
            {
                visible.push(public_document(document)?);
            }
        }
        let query = parse_query(raw.as_deref().unwrap_or(""), &state.schema)?;
        page(&visible, &query, &state.schema)
    })();
    match result {
        Ok(result) => Json(result).into_response(),
        Err(failure) => listing_error(failure),
    }
}

async fn get_document(
    State(state): State<Arc<ProductState>>,
    identifier: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
) -> Response {
    let principal = match principal_for(&state, &headers).await {
        Ok(principal) => principal,
        Err(response) => return response,
    };
    let Ok(Path(identifier)) = identifier else {
        return error(StatusCode::FORBIDDEN, "FORBIDDEN");
    };
    let Some(document) = state
        .documents
        .iter()
        .find(|document| document["id"].as_str() == Some(identifier.as_str()))
    else {
        return error(StatusCode::FORBIDDEN, "FORBIDDEN");
    };
    let resource = match resource(document) {
        Ok(resource) => resource,
        Err(failure) => return listing_error(failure),
    };
    if !state
        .policy
        .decide(Some(&principal), "documents:read", &resource)
        .allowed
    {
        return error(StatusCode::FORBIDDEN, "FORBIDDEN");
    }
    match public_document(document) {
        Ok(document) => Json(document).into_response(),
        Err(failure) => listing_error(failure),
    }
}
