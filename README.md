# Feature Standards

**Reusable features for AI-assisted development, backed by shared contracts, stack-specific implementations, and common conformance tests.**

Authentication is the first feature: login, logout, and session lookup. Python, Go, Java, and Rust servers implement the same HTTP behavior, and a shared React client connects to each backend.

The **0.3.0 account lifecycle extension** adds registration, email verification, and password reset through the optional `browser-session-v3` profile. The default in-memory `browser-session-v1` and PostgreSQL `browser-session-v2` profiles remain available. Select v3 with `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true`. See the [local v3 validation record](docs/validation-2026-11-02-accounts-v3.md) and [commit-specific CI results](https://github.com/jongko54/feature-standards/actions) for verified coverage. This project has not undergone a production security audit.

## What is included

| Component | Purpose |
|---|---|
| [v1 specification](features/auth/specification.md) / [OpenAPI](features/auth/openapi.json) / [19 scenarios](features/auth/scenarios.json) | Default profile: one configured user and process-local sessions |
| [v2 specification](features/auth/postgres-session-v2.md) / [OpenAPI](features/auth/openapi-v2.json) / [evidence map](features/auth/scenarios-v2.json) | PostgreSQL users, sessions, and login failures, with transaction and failure semantics |
| [v3 specification](features/auth/account-session-v3.md) / [OpenAPI](features/auth/openapi-v3.json) / [evidence map](features/auth/scenarios-v3.json) | Registration, email verification, password reset, and a transactional outbox |
| [SMTP delivery contract](features/auth/mail-delivery-v1.md) / [guide](docs/smtp-delivery.md) / [evidence map](features/auth/mail-scenarios.json) | Optional worker with verified TLS, bounded retries, and fenced acknowledgments |
| [PostgreSQL DDL](features/auth/postgres/001_initial.sql) / [database tool](tools/auth_db.py) | Explicit schema version 1 migration and separate demo seeding |
| [Python / FastAPI](implementations/python-fastapi) | Installable `feature_auth` package, application factory, and authentication dependency |
| [Go / net/http](implementations/go-net-http), [Java / Spring](implementations/java-spring), [Rust / Axum](implementations/rust-axum) | HTTP adapters with service and storage boundaries |
| [React / TypeScript](clients/react/README.md) | Shared reference UI and the `@ugauga/feature-standards-react-auth/api` export |
| [Separate Python + React consumer](examples/consumer-python-react/README.md) | Protected API example that imports packages without copying authentication logic |
| [AI integration skill](skills/integrate-auth/SKILL.md) | Inspect, integrate, and validate authentication in a target project |
| [Integration manifest](feature-standards.json) / [AI integration guide](docs/ai-integration.md) | Public APIs, profiles, dependencies, consumer examples, and verification commands for five stacks |
| [Authentication bootstrap CLI](docs/create-feature-auth.md) | Generate a thin protected API consumer for any server stack and select v1/v2/v3 |

See the [PostgreSQL guide](docs/postgres-v2.md) for v2, the [account lifecycle guide](docs/account-v3.md) for v3 migrations, mail, TLS, and verification boundaries, and the [versioning policy](docs/versioning.md) for compatibility rules. Supporting specifications and validation records currently include Korean documentation.

## Quick start

To generate a separate consumer application from a local source checkout:

```sh
node packages/create-feature-auth/src/cli.mjs \
  --source "$PWD" --stack python --profile browser-session-v1 \
  --dest ../my-auth-app --check
```

Choose `python`, `go`, `java`, or `rust`. The CLI connects the existing package and generates application glue, environment examples, and build/run commands. `--check` uses a temporary loopback memory demo; it does not migrate or seed a database. See the [CLI guide](docs/create-feature-auth.md) and [server release status](docs/server-releases.md).

Install the toolchain for your chosen server: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Go 1.26+, Java 21+, or Rust/Cargo 1.93.1+. The React client requires Node.js 22.12+ and npm. Full validation requires all four server toolchains; browser CI uses Node.js 24 and Chromium.

Start one in-memory demo server. The public demo credentials are `demo@example.com` / `correct-horse-battery-staple`.

```sh
# Python
cd implementations/python-fastapi
AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

```sh
# Or Go
cd implementations/go-net-http
AUTH_DEMO=true AUTH_COOKIE_SECURE=false go run .
```

```sh
# Or Java
cd implementations/java-spring
./mvnw -q -DskipTests package
AUTH_DEMO=true AUTH_COOKIE_SECURE=false java -jar target/auth-server.jar
```

```sh
# Or Rust
cd implementations/rust-axum
cargo build --locked
AUTH_DEMO=true AUTH_COOKIE_SECURE=false target/debug/feature-standards-auth
```

In another terminal, start the shared UI and open **http://127.0.0.1:5173**.

```sh
cd clients/react
npm ci
npm run dev
```

Vite proxies `/auth` to the selected server, so the local setup does not require additional CORS configuration. For a different server port, use a command such as `AUTH_API_TARGET=http://127.0.0.1:8080 npm run dev`. Keep `localhost` and `127.0.0.1` consistent: they are different origins.

### Use PostgreSQL

Set `AUTH_DATABASE_URL` to the PostgreSQL URI of an existing dedicated local database, then prepare it explicitly from the repository root.

```sh
uv sync --frozen --project tools
uv run --frozen --project tools python tools/auth_db.py migrate
# Only for a local demo that needs the two public test accounts:
uv run --frozen --project tools python tools/auth_db.py seed-demo --confirm-demo
```

Pass `AUTH_STORE=postgres` and `AUTH_DATABASE_URL` to the server. For example:

```sh
cd implementations/python-fastapi
AUTH_STORE=postgres AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  AUTH_ALLOWED_ORIGIN=http://127.0.0.1:5173 \
  uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

The application performs **no automatic DDL, seeding, or in-memory fallback**. In database mode, `AUTH_DEMO=true` only permits local HTTP and cookie exceptions; it does not create accounts or change passwords. `AUTH_USER_EMAIL` and `AUTH_USER_PASSWORD` are not used in database mode. Demo seeding preserves existing users and passwords.

The common local URI uses an explicit `sslmode=disable`. Remote Rust connections require `sslmode=verify-full` and verify the certificate chain and hostname using an explicit `sslrootcert` or the platform trust roots. Weaker modes and plaintext fallback after TLS refusal are rejected. Production database authentication, privileges, and capacity require a separate review.

### Enable the account lifecycle

v3 requires schema version 2. Stop existing schema 1 servers, check backups and permissions, and migrate explicitly. The same tool initializes a new database at schema 1 before upgrading it to 2.

```sh
uv run --frozen --project tools python tools/auth_db.py migrate-accounts
# Only when a local database needs public test accounts:
uv run --frozen --project tools python tools/auth_db.py seed-demo --confirm-demo
```

Set `AUTH_STORE=postgres AUTH_ACCOUNT_LIFECYCLE=true` on the server and `VITE_AUTH_ACCOUNT_LIFECYCLE=true` when starting the React development server. The default false value preserves the existing profile and screen. New accounts cannot log in before email verification. Password reset atomically revokes all existing sessions, and verification or reset cannot override an administrator's disabled state.

Email messages are stored in the database outbox. The optional [SMTP worker](tools/mail_worker.py) handles TLS delivery, retries, and claim/acknowledgment processing using separate SMTP configuration. Provider accounts and sender addresses must be configured separately; implementation and local testing do not demonstrate production email delivery. The [local capture tool](tools/mail_capture.py) writes eligible test messages not owned by SMTP to new files with mode 0600. Raw tokens in the outbox and capture files are sensitive bearer credentials. See the [SMTP guide](docs/smtp-delivery.md) for migrations, settings, and operational boundaries.

## Reuse in another project

AI agents and tools can select a stack and profile from `feature-standards.json`. For example, `uv run --frozen --project tools python tools/auth_catalog.py --stack go --profile browser-session-v1` returns the relevant specification, public APIs, example, and commands as JSON. It does not execute those commands. The `.agents/skills/integrate-auth` symlink makes the source skill discoverable by Codex.

The paired model evaluation passed **24/24 integrations** across four backends, two context conditions, and three repeats per condition. Efficiency results are mixed and do not establish a general speed or token improvement. See the [repeated evaluation](docs/validation-ai-paired-2026-11-03.md), [earlier smoke record](docs/validation-ai-2026-11-03.md), and [AI integration guide](docs/ai-integration.md).

| Stack | Reusable interface | Separate consumer |
|---|---|---|
| Python | Wheel with `create_app` and `current_user` | [Python + React](examples/consumer-python-react/README.md) |
| Go | `auth` package with `NewServer` and `CurrentUser` | [Go](examples/consumer-go/README.md) |
| Java | Plain JAR with the `library` classifier, `AuthService`, and `AuthFilter` | [Java](examples/consumer-java/README.md) |
| Rust | Path crate with `AuthService::from_config` and `current_user` | [Rust](examples/consumer-rust/README.md) |
| React | `@ugauga/feature-standards-react-auth/api` | [Python + React](examples/consumer-python-react/README.md) |

Independent consumers exercise protected APIs and session revocation with in-memory v1. The [database consumer matrix](examples/consumer-python-react/PROFILE_TESTS.md) additionally verifies all four server packages with PostgreSQL v2/v3 and a real React UI: eight isolated backend/profile combinations and 28 Chromium scenarios passed in the current local run. Reference servers have separate conformance checks. Server registry availability is tracked in the [release guide](docs/server-releases.md); the React API is [published on npm](https://www.npmjs.com/package/@ugauga/feature-standards-react-auth).

The Python distribution is named `feature-standards-python-auth`, and its import name is `feature_auth`. The [package project](implementations/python-fastapi/pyproject.toml) defines a wheel build; the [consumer project](examples/consumer-python-react/pyproject.toml) installs it through a uv path dependency. Its public interfaces include `create_app()` and `current_user(request)`.

```python
from typing import Annotated
from fastapi import Depends
from feature_auth import create_app, current_user

app = create_app()


@app.get("/api/profile")
def profile(user: Annotated[dict[str, str], Depends(current_user)]):
    return {"user": user}
```

Install the React API client from npm and import its public API:

```sh
npm install @ugauga/feature-standards-react-auth
```

```ts
import { createAuthApi, type AuthSession } from '@ugauga/feature-standards-react-auth/api';

const auth = createAuthApi();
const session: AuthSession | null = await auth.me();
```

The [separate consumer example](examples/consumer-python-react/README.md) covers a protected API, login, reload restoration, logout, and user isolation. It uses a React file dependency to test the current checkout; registry installation is verified separately. The Python wheel is provided as a local dependency. See the [v2 guide](docs/postgres-v2.md#별도-소비-앱) for setup.

## Verify the same behavior across stacks

See the [SMTP validation record](docs/validation-smtp-2026-11-02.md) for the mail extension's executed coverage.

Run the following commands from the repository root. Static contract checks validate schemas and their test mappings; they do not execute server behavior.

```sh
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project tools python tools/generate_openapi_v2.py --check
uv run --frozen --project tools python tools/generate_openapi_v3.py --check
uv run --frozen --project tools python -m unittest discover -s tests -p 'test_*.py' -v

uv run --frozen --project implementations/python-fastapi pytest implementations/python-fastapi/tests
go -C implementations/go-net-http test -race ./...
implementations/java-spring/mvnw -f implementations/java-spring/pom.xml test
cargo test --locked --manifest-path implementations/rust-axum/Cargo.toml

python3 tests/conformance.py --backend all --browser
```

For browser checks, first run `npm ci`, `npm test`, `npm run build`, and `npx playwright install chromium` in `clients/react`. Port 5173 must be available. Omit `--browser` to run only the v1 HTTP checks, or select one server with `--backend python|go|java|rust`.

Full v2 validation uses PostgreSQL server binaries containing `initdb` and `pg_ctl`, or an explicitly configured dedicated test database. Local validation used **PostgreSQL 18.6**.

```sh
# Start and stop a dedicated temporary database with server binaries from PATH.
uv run --frozen --project tools python tests/postgres_conformance.py --browser
uv run --frozen --project tools python tests/account_conformance.py --browser

# Prepare the separate Python/React consumer dependencies.
uv sync --frozen --project examples/consumer-python-react
npm --prefix examples/consumer-python-react ci
npm --prefix examples/consumer-python-react run build
uv run --frozen --project tools python tests/consumer_conformance.py
uv run --frozen --project tools python tests/consumer_profiles.py --browser
```

Use `FEATURE_STANDARDS_PG_BIN` to choose a server binary directory, or `FEATURE_STANDARDS_TEST_DATABASE_URL` to use an existing dedicated database. The database harnesses reset the `feature_auth` schema, so use **only task-owned loopback test databases whose names start with `feature_standards_test`**. See the [v2 guide](docs/postgres-v2.md#검증과-근거-맵) for fixture safeguards and evidence mappings.

### GitHub Actions

The [CI workflow](.github/workflows/ci.yml) and its [matching template](ci/github-actions.yml) define PostgreSQL 18.6 services; separate schema 1/2 databases for backend tests; v1/v2/v3 HTTP and browser checks; account races and SQL gateway tests; Rust TLS; independent consumers; and SMTP delivery/capture races. Mail checks use separate worker, capture, and integration databases. Update both workflow files together. A checked-in workflow definition and a [successful run for a specific commit](https://github.com/jongko54/feature-standards/actions) are separate evidence.

## API and operational boundaries

| Request | Success | Representative failures |
|---|---|---|
| `POST /auth/login` | `200` with session cookie, user, and CSRF token | `400`, `401`, `403`, `413`, `415`, `429`; v2 `503` |
| `GET /auth/me` | `200` with user and CSRF token | `401`; v2 `503` |
| `POST /auth/logout` | Empty `204`, server session deletion, and cookie removal | `403`; v2 `503` |
| `GET /healthz` | `200` with selected profile and implementation name | v2 storage failure `503` |

State-changing requests require an exact Origin match. In v2, an unexpired stored session requires logout CSRF validation regardless of the user's enabled state. Invalid CSRF preserves the session, and database failure is not reported as successful logout. Cookies use `Secure` by default.

In-memory state is lost on restart. v2/v3 share sessions and login failures through the database. Behind a reverse proxy, the peer address is the proxy's address unless a trusted proxy policy is configured. Production integration requires review of database privileges, backups and capacity, proxy trust, HTTPS, secret management, observability, and outbox access, encryption, and retention. Role management and MFA are not included. SMTP DATA acceptance and database acknowledgment do not prove inbox delivery.

These specifications are experimental repository conventions, not an accredited international standard. See the [original v1 validation record](docs/validation-2026-11-01.md), [contribution guide](CONTRIBUTING.md), [security scope](SECURITY.md), and [prior research](docs/research.md). Licensed under [MIT](LICENSE).

## Release and validation status

The [reuse validation record](docs/validation-reuse-2026-11-03.md) covers the four-language generator, independent PostgreSQL consumers, distribution artifacts, and [successful full implementation CI](https://github.com/jongko54/feature-standards/actions/runs/41571472426). Go v0.1.0 is [published and remotely installed](docs/go-release-0.1.0.json). The new CLI npm publication and trusted-publisher activation still require npm account authentication; Python, Java, and Rust registry setup is documented separately.
