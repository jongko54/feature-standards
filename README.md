# Feature Standards

**Shared feature contracts and reusable implementations across languages, so AI agents can integrate existing libraries and verify the result.**

Feature Standards organizes a feature's behavior, public APIs, stack guides, and conformance checks in one place. An agent chooses the feature, profile, and stack; reads the relevant contract and API; reuses the implementation; and checks the integration against the same behavior across stacks. The goal is to reduce repeated implementation and unnecessary exploration during AI-assisted development.

**Authentication is the first and currently available feature.** Python/FastAPI, Go/net/http, Java/Spring, and Rust/Axum implement shared browser-session contracts. React is one client adapter for those servers. The catalog currently contains `auth`; additional features are future work.

## Start with the feature catalog

The main npm package is **`feature-standards`**, with `0.1.0` prepared in this checkout. It provides a JSON CLI and curated contracts, a manifest, and stack guides. Server libraries, runtime source, consumer applications, and executable conformance harnesses live in the source repository and have separate distribution requirements.

Use the source checkout before npm publication is confirmed:

```sh
npm --prefix packages/feature-standards run build
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context \
  --feature auth --stack python --profile browser-session-v1
```

The build creates the bundled documentation snapshot. Select `python`, `go`, `java`, `rust`, or `react` and one of the authentication profiles below. The CLI returns JSON context with separate bundled-document paths and source-checkout instructions; it does not install dependencies, generate applications, run servers, migrate databases, or execute tests.

After `feature-standards@0.1.0` publication and registry installation are verified, the equivalent npm entry points are:

```sh
npx feature-standards@0.1.0 list
npx feature-standards@0.1.0 context \
  --feature auth --stack go --profile browser-session-v2
```

See the [main package guide](packages/feature-standards/README.md), [AI integration guide](docs/ai-integration.md), and [npm discovery guide](docs/npm-discovery.md). Prepared versions and local package checks do not establish public npm availability or search indexing.

## How an AI integration works

1. **Choose the feature, profile, and stack.** The catalog makes the supported combinations explicit. If the selection is already known, go directly to its contract and public API guide.
2. **Read the selected contract and API.** Check HTTP behavior, errors, storage requirements, and the library entry points needed by the target application.
3. **Reuse the implementation.** Import the matching library or client adapter and add application-specific glue. Use the authentication generator when a new thin consumer application is needed.
4. **Run conformance and application checks.** Execute the selected checks explicitly, then test the target application's real API and UI. Record the source version, selected profile, results, and remaining limits.

The [source manifest](feature-standards.json) maps the current authentication profiles to public APIs, dependencies, examples, and verification commands. The [integration skill](skills/integrate-auth/SKILL.md) provides the authentication-specific workflow. Neither a JSON context response nor a package installation proves a working integration.

## Current feature: authentication

| Profile | Behavior | Contract and setup |
|---|---|---|
| `browser-session-v1` | Login, session lookup, and logout for one configured user with process-local sessions | [Specification](features/auth/specification.md), [OpenAPI](features/auth/openapi.json), [19 scenarios](features/auth/scenarios.json) |
| `browser-session-v2` | PostgreSQL users, sessions, and login failures with transaction and failure semantics | [Specification](features/auth/postgres-session-v2.md), [OpenAPI](features/auth/openapi-v2.json), [PostgreSQL guide](docs/postgres-v2.md) |
| `browser-session-v3` | Registration, email verification, password reset, and a transactional outbox; PostgreSQL schema 2 | [Specification](features/auth/account-session-v3.md), [OpenAPI](features/auth/openapi-v3.json), [Account guide](docs/account-v3.md) |

v1 is the default. v2 and v3 require explicit database configuration and migrations. The optional [SMTP delivery extension](features/auth/mail-delivery-v1.md) belongs to v3 and requires a separately configured and explicitly run worker; see the [SMTP guide](docs/smtp-delivery.md). Installing or starting a package does not migrate or seed a database.

### Reusable libraries and adapters

| Stack | Public interface | Integration example |
|---|---|---|
| [Python / FastAPI](implementations/python-fastapi/README.md) | `feature_auth.create_app`, `current_user` | [Python + React consumer](examples/consumer-python-react/README.md) |
| [Go / net/http](implementations/go-net-http/README.md) | `auth.NewServer`, `Server.CurrentUser` | [Go consumer](examples/consumer-go/README.md) |
| [Java / Spring](implementations/java-spring/README.md) | `AuthService.create`, `AuthFilter`; plain JAR with `library` classifier | [Java consumer](examples/consumer-java/README.md) |
| [Rust / Axum](implementations/rust-axum/README.md) | `AuthService::from_config`, `current_user` | [Rust consumer](examples/consumer-rust/README.md) |
| [React / TypeScript](clients/react/README.md) | `createAuthApi`, `AuthSession`; npm root and `/api` exports | [Python + React consumer](examples/consumer-python-react/README.md) |

The main package exposes the feature context. The following npm packages are authentication components within Feature Standards:

| Component | Package | Prepared version |
|---|---|---|
| Browser authentication API adapter | `@ugauga/feature-standards-react-auth` | `0.1.4` |
| Thin authentication application generator for four server stacks | `@ugauga/create-feature-auth` | `0.1.1` |

The React adapter connects browser applications to the shared authentication API; it is one part of the project. The generator creates application glue around the server libraries. The [React release record](docs/npm-release.md) and [server release guide](docs/server-releases.md) track registry-specific publication and installation separately from these prepared versions. All three npm packages identify [jongko54](https://github.com/jongko54) as author and carry the `jongko54` and `feature-standards` discovery keywords.

### Generate an authentication consumer

From the source checkout, create a separate application using an explicit runtime source path:

```sh
node packages/create-feature-auth/src/cli.mjs \
  --source "$PWD" --stack python --profile browser-session-v1 \
  --dest ../my-auth-app --check
```

Choose `python`, `go`, `java`, or `rust`. The destination must be new, outside the checkout, and under an existing physical parent directory. The generator reuses the chosen server library rather than copying its implementation. `--check` builds and exercises a temporary loopback **memory v1** application even when another profile is selected; it is not a v2/v3 database test. See the [generator guide](docs/create-feature-auth.md) for requirements, outputs, and explicit database setup.

### Run a local reference application

The following commands start the default in-memory Python reference server and shared React UI. The public demo credentials are `demo@example.com` / `correct-horse-battery-staple`.

```sh
cd implementations/python-fastapi
AUTH_DEMO=true AUTH_COOKIE_SECURE=false \
  uv run --frozen uvicorn app:app --no-proxy-headers --host 127.0.0.1 --port 8000
```

In another terminal, from the checkout root:

```sh
cd clients/react
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/auth` to the server. Use `AUTH_API_TARGET=http://127.0.0.1:8080 npm run dev` for another backend port, and keep `localhost` and `127.0.0.1` consistent because they are different origins. The [stack guides](#reusable-libraries-and-adapters) contain the other server commands.

Python requires 3.12+ with [uv](https://docs.astral.sh/uv/); the alternative servers require Go 1.26+, Java 21+, or Rust/Cargo 1.93.1+. The CLI and React client require Node.js 22.12+. Full repository validation needs all four server toolchains; browser CI uses Node.js 24 and Chromium.

## Verify the shared behavior

From the repository root, validate the catalog, generated contracts, and repository tools:

```sh
uv run --frozen --project tools python tools/auth_catalog.py --check
uv run --frozen --project tools python tools/check_contract.py
uv run --frozen --project tools python tools/generate_openapi_v2.py --check
uv run --frozen --project tools python tools/generate_openapi_v3.py --check
uv run --frozen --project tools python -m unittest discover -s tests -p 'test_*.py' -v
```

Run implementation and common v1 behavior checks separately:

```sh
uv run --frozen --project implementations/python-fastapi pytest implementations/python-fastapi/tests
go -C implementations/go-net-http test -race ./...
implementations/java-spring/mvnw -f implementations/java-spring/pom.xml test
cargo test --locked --manifest-path implementations/rust-axum/Cargo.toml
python3 tests/conformance.py --backend all --browser
```

For browser checks, first run `npm ci`, `npm test`, `npm run build`, and `npx playwright install chromium` in `clients/react`. Port 5173 must be available. Omit `--browser` for v1 HTTP checks only, or select `--backend python|go|java|rust`.

Database, account, consumer-profile, and SMTP checks have separate prerequisites and evidence: [PostgreSQL v2](docs/postgres-v2.md), [account v3](docs/account-v3.md), [consumer profile matrix](examples/consumer-python-react/PROFILE_TESTS.md), and [SMTP validation](docs/validation-smtp-2026-11-02.md). Database harnesses reset the `feature_auth` schema. Use only task-owned loopback test databases whose names start with `feature_standards_test`.

The [CI workflow](.github/workflows/ci.yml) and [matching template](ci/github-actions.yml) define repository checks. A workflow definition, a local result, and a successful CI run for a particular source commit are separate evidence. The [reuse validation record](docs/validation-reuse-2026-11-03.md) links the corresponding implementation CI and distribution checks.

## Evidence and limits

An earlier paired AI evaluation passed **24/24 authentication integrations** across four backends, two context conditions, and three repeats per condition. It measured the earlier **v1** integration workflow. Time and token results were mixed and do not establish a general efficiency improvement or benchmark the new `feature-standards` package. See the [repeated evaluation and its source/sampling limits](docs/validation-ai-paired-2026-11-03.md). Reducing repeated work is the product goal; improvement must be measured for the actual workflow and environment.

These specifications are experimental repository conventions, not an accredited international standard. In-memory state is lost on restart. Database mode has no automatic DDL, seeding, or in-memory fallback. Role management and MFA are not included. Production integration needs review of HTTPS, proxy trust, secrets, database privileges and backups, observability, and outbox access and retention. SMTP acceptance does not prove inbox delivery. This project has not undergone a production security audit.

See the [versioning policy](docs/versioning.md), [contribution guide](CONTRIBUTING.md), [security scope](SECURITY.md), and [prior research](docs/research.md). Created by [jongko54](https://github.com/jongko54). Licensed under [MIT](LICENSE).
