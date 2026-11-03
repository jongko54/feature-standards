# Feature Standards authentication for Axum

Reusable session authentication with the same behavioral contracts as the project's Python, Go, Java, and browser clients. Requires Rust 1.93.1 or later.

```rust,no_run
use feature_standards_auth::{app_with_service, AuthService, Config};

# async fn example() -> Result<(), Box<dyn std::error::Error>> {
let mut config = Config::from_env()?;
let service = AuthService::from_config(&mut config).await?;
let router = app_with_service(config, service);
# Ok(())
# }
```

Use `current_user` with the same service in a protected consumer route. The reference binary and reusable library are both included. In-memory mode supports one configured user; PostgreSQL mode persists sessions, and the optional account lifecycle profile supports registration, verification, and password reset.

Migrations and demo seeding are explicit repository commands. Startup performs neither. Remote PostgreSQL connections require `sslmode=verify-full`; the adapter verifies the certificate chain and hostname and rejects plaintext downgrade.

See the [integration guide](https://github.com/jongko54/feature-standards/tree/main/implementations/rust-axum), [separate consumer](https://github.com/jongko54/feature-standards/tree/main/examples/consumer-rust), and [security policy](https://github.com/jongko54/feature-standards/security/policy). Tests that explicitly require repository migration files run from a full checkout. Contract tests do not constitute an independent security audit. MIT licensed.
