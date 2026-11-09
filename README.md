# Feature Standards

**Shared feature contracts and reusable implementations across languages, so AI agents can integrate existing libraries and verify the result.**

Feature Standards organizes a feature's behavior, public APIs, stack guides, and conformance checks in one place. An agent chooses the feature, profile, and stack; reads the relevant contract and API; reuses the implementation; and checks the integration against the same behavior across stacks. The goal is to reduce repeated implementation and unnecessary exploration during AI-assisted development.

**Three feature standards are available: authentication, authorization, and listing.** The new `authorization/rbac-v1` and `listing/offset-list-v1` libraries provide the same contracts in Python, Go, Java, Rust and JS/TS, with shared executable scenarios and a real Python HTTP composition. Core `0.1.0` is published in all five ecosystems; [the registry receipt](docs/core-release-0.1.0.json) verifies public downloads and fresh consumers independently. These are experimental core APIs. [Read the integration guide](docs/core-standards.md). Authentication retains its published FastAPI, Go, Spring, Axum and React packages.

The current source adds real three-feature HTTP consumers for [Go](examples/core-go/README.md), [Java](examples/core-java/README.md) and [Rust](examples/core-rust/README.md), plus a Python-only [PostgreSQL listing profile](docs/postgres-listing.md). Catalog `0.4.0` and Python core `0.2.0` are source candidates; the published versions below retain their recorded behavior. The source catalog exposes 26 supported contexts and preserves the 10,000-row materialized profile separately from database listing. The opt-in compact routing mode reduces the JSON payload while retaining document hashes and trust limits; see the [validation scope and measurements](docs/validation-core-hardening-2026-11-07.md).

The [2026-11-08 real-model reading study](docs/validation-ai-reading-2026-11-08.md) ran 24 fresh sessions with the local CLI 0.4.0 candidate. Original HTTP outcomes were **23/24**. Compact guidance reduced paired input-token sums by **19.032%** versus manual guidance, while uncached input increased **16.927%** and output increased **12.933%**. This small, cache-sensitive sample does not establish lower cost or external adoption. See the preserved outcomes, separate static audit, and follow-up observations in the report.

A separate eight-session similar-task pilot compared compact guidance with short stack-specific briefs: **8/8 HTTP passes**, input-token sums **71.442% lower**, uncached input **58.301% lower**, and output **50.176% lower**. There was only one pair per backend. Four separate sessions without prescribed reuse implemented the features independently. These are supplied-checkout observations; they do not measure external AI adoption or guarantee savings.

The [2026-11-10 unprescribed choice study](docs/adoption/2026-11-10-ai-choice.md) ran **32 fresh integration sessions** with two requested models, four backend frameworks and two fixed similar task variants. One app connected the original auth/core dependencies across all three features, 13 used copied or vendored runtime source, and 18 implemented all three features directly. Thus **14/32 used provided code** in some form; original HTTP outcomes were **27/32**. These are source-reviewed choices inside a supplied checkout, not an external adoption rate or a new token-saving result. The separate [public-project investigation](docs/adoption/2026-11-10-public-projects.md) confirmed zero external declarations or product connections in its incomplete search; the actual external total remains unknown.

## Start with the feature catalog

The main npm package is **[`feature-standards@0.3.2`](https://www.npmjs.com/package/feature-standards)**. It provides curated contracts, stack context, and explicit application generation and profile checks. Server libraries, runtime source, consumer applications, and executable conformance harnesses live in the source repository and have separate distribution requirements. The [0.3.2 receipt](docs/npm-release-0.3.2.json) verifies the reviewed public archive and all 25 contexts from a fresh registry installation.

Run the published catalog:

```sh
npx feature-standards@0.3.2 list
npx feature-standards@0.3.2 context \
  --feature auth --stack python --profile browser-session-v1
```

Select `python`, `go`, `java`, `rust`, or `react` and one of the authentication profiles below. `list` and `context` are read-only JSON selectors with separate bundled-document paths and source-checkout instructions.

The published workflow provides explicit `init` and `check` commands. From a trusted Feature Standards source checkout:

```sh
npx feature-standards@0.3.2 init \
  --feature auth --source "$PWD" --stack python \
  --profile browser-session-v1 --dest ../my-auth-app --check
npx feature-standards@0.3.2 check --project ../my-auth-app
```

`init` creates a new application using the checkout's generator `0.2.0` or newer. `check` and `init --check` explicitly build and exercise that trusted application's selected profile. v1 uses a temporary memory server. v2/v3 require `FEATURE_STANDARDS_TEST_DATABASE_URL` pointing to a dedicated loopback test database with an explicit port and a `feature_standards_test*` name; the test role needs permission to create databases. Each check creates and drops its own UUID database, leaving the base database's schema and data unchanged. v2 verifies persistence across a server restart; v3 also verifies registration, email verification, password reset, and session revocation without sending SMTP mail. A JSON receipt identifies the profile and completed checks. See the [generation guide](docs/create-feature-auth.md).

You can also build the documentation snapshot and run from a source checkout:

```sh
npm --prefix packages/feature-standards run build
node packages/feature-standards/src/cli.mjs list
node packages/feature-standards/src/cli.mjs context \
  --feature auth --stack go --profile browser-session-v2
```

See the [main package guide](packages/feature-standards/README.md), [AI integration guide](docs/ai-integration.md), and [npm discovery guide](docs/npm-discovery.md). The [0.2.0 release receipt](docs/npm-workflow-release-2026-11-04.json) records public artifact integrity, fresh registry installation, all 15 contexts, actual installed workflows, and observed `jongko54` search results. [GitHub release assets](https://github.com/jongko54/feature-standards/releases/tag/feature-standards-v0.2.0) provide verified server archives. Python is also published on PyPI, Java on Maven Central, Rust on crates.io, and Go through its versioned module. The [2026-11-05 registry snapshot](docs/registry-status-2026-11-05.json) checks availability of all seven published package versions. Search rank and future indexing are not guaranteed.

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

Install the Python library from [PyPI](https://pypi.org/project/feature-standards-python-auth/0.2.0/) with Python 3.12 or later:

```sh
python -m pip install feature-standards-python-auth==0.2.0
```

The [Python release receipt](docs/python-release-0.2.0.json) records matching CI/public artifact hashes, a fresh PyPI installation, and 19 passing common HTTP contract tests plus the public authentication dependency lifecycle. PostgreSQL, SMTP, and browser checks were not rerun for this registry publication.

Java consumers can resolve the plain library directly from Maven Central:

```xml
<dependency>
  <groupId>io.github.jongko54</groupId>
  <artifactId>java-spring-auth</artifactId>
  <version>1.0.0</version>
  <classifier>library</classifier>
</dependency>
```

The [Java release receipt](docs/java-release-1.0.0.json) records the published signed artifacts, an initially empty private Maven repository, and four passing consumer tests including real loopback login/logout, CSRF rejection, and safe storage-error behavior.

Rust consumers can use [feature-standards-auth 0.1.0](https://crates.io/crates/feature-standards-auth/0.1.0) from crates.io:

```toml
[dependencies]
feature-standards-auth = "0.1.0"
```

The [Rust release receipt](docs/rust-release-0.1.0.json) records matching registry/CI crate checksums, owner `jongko54`, installation into a fresh private Cargo home, one router integration test, and 19 passing common HTTP tests against the separate consumer's real loopback server. This release verification targets memory v1; PostgreSQL, SMTP, and browser checks were not rerun.

The main package exposes the feature context. The following npm packages are authentication components within Feature Standards:

| Component | Package | Published npm version |
|---|---|---|
| Browser authentication API adapter | `@ugauga/feature-standards-react-auth` | `0.1.4` |
| Thin authentication application generator for four server stacks | `@ugauga/create-feature-auth` | `0.2.0` |

The React adapter connects browser applications to the shared authentication API; it is one part of the project. The generator creates application glue around the server libraries. The [npm release record](docs/npm-release.md) and [server release guide](docs/server-releases.md) track registry-specific publication and installation evidence. All three npm packages identify [jongko54](https://github.com/jongko54) as author and carry the `jongko54` and `feature-standards` discovery keywords.

### Generate an authentication consumer

From the source checkout, create a separate application using an explicit runtime source path:

```sh
node packages/create-feature-auth/src/cli.mjs \
  --source "$PWD" --stack python --profile browser-session-v1 \
  --dest ../my-auth-app --check
```

Choose `python`, `go`, `java`, or `rust`. The destination must be new, outside the checkout, and under an existing physical parent directory. The generator reuses the chosen server library rather than copying its implementation. In generator `0.2.0`, `--check` exercises the selected profile; database checks use a newly created, isolated test database and require explicit test configuration. Published generator `0.1.1` retains its earlier memory-v1-only check. See the [generator guide](docs/create-feature-auth.md) for requirements, outputs, and database setup.

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

A [three-feature catalog smoke](evals/core/README.md) ran eight actual model integrations using published CLI 0.3.2 and frozen source. The original result was **7/8**; a cache guard blocked the remaining Python application before HTTP grading. Separate artifact-only regrading passed **5/8** under strict build, HTTP and byte-preservation checks: the Python catalog application required an omitted offline cache, and both Go applications passed HTTP checks but changed generated files. These records remain separate. Catalog input token counts were higher in all four pairs; this small, shared-cache sample does not establish a general efficiency benefit or harm. The new compact source mode was not measured by these model runs.

An earlier paired AI evaluation passed **24/24 authentication integrations** across four backends, two context conditions, and three repeats per condition. It measured the earlier **v1** integration workflow. Time and token results were mixed and do not establish a general efficiency improvement or benchmark the new `feature-standards` package. See the [repeated evaluation and its source/sampling limits](docs/validation-ai-paired-2026-11-03.md). Reducing repeated work is the product goal; improvement must be measured for the actual workflow and environment.

These specifications are experimental repository conventions, not an accredited international standard. In-memory state is lost on restart. Database mode has no automatic DDL, seeding, or in-memory fallback. The new core authorization library evaluates explicit role grants; role-management APIs and MFA are not included. Production integration needs review of HTTPS, proxy trust, secrets, database privileges and backups, observability, and outbox access and retention. SMTP acceptance does not prove inbox delivery. This project has not undergone a production security audit.

See the [versioning policy](docs/versioning.md), [contribution guide](CONTRIBUTING.md), [security scope](SECURITY.md), and [prior research](docs/research.md). Created by [jongko54](https://github.com/jongko54). Licensed under [MIT](LICENSE).
