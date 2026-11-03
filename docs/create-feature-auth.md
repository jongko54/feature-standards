# Generate an authentication consumer

`@ugauga/create-feature-auth` is the authentication-specific application generator within [Feature Standards](../README.md). The main `feature-standards` package provides feature discovery, contracts, and stack context; this companion generator creates a thin application that reuses an existing public authentication library. Authentication is the first available feature, and this CLI does not generate other features.

It supports Python/FastAPI, Go/net/http, Java/Spring Boot, and Rust/Axum, with a protected `GET /api/profile`. It keeps authentication behavior in the library instead of generating another implementation. See the [AI integration guide](ai-integration.md) for the feature/profile/stack → contract/API → library reuse → conformance workflow.

The source checkout must be explicit. Server registry publication is separate from project generation; local source dependencies work before those publications are available. React is supported through the existing [React consumer](../examples/consumer-python-react/README.md), not a generated frontend in this CLI.

```sh
# From this checkout, without installing or publishing an npm package:
node packages/create-feature-auth/src/cli.mjs \
  --source "$PWD" \
  --stack go \
  --profile browser-session-v1 \
  --dest /physical/path/outside-the-checkout/new-auth-app \
  --check

# Published 0.2.0: selected-profile checks and fresh registry installation verified.
npx @ugauga/create-feature-auth@0.2.0 \
  --source /absolute/path/to/feature-standards \
  --stack rust \
  --profile browser-session-v3 \
  --dest /physical/path/to/new-auth-app
```

Node.js 22.12+ is required. There are no runtime npm dependencies. The source checkout contains the server runtime separately from the main context package. Generation reads bundled consumer templates and the chosen checkout's manifest and package metadata without invoking a compiler, installing dependencies, or accessing a database. `--check` additionally builds and runs the selected profile's isolated fixture described below. The source is trusted build input, not sandboxed code. Existing `0.1.1` packages retain their earlier memory-only check behavior; the selected-profile protocol is published in `0.2.0`.

`--source`, `--stack`, and `--dest` are required. `--profile` defaults to `browser-session-v1`; v2 and v3 must be selected explicitly. Unsupported selections fail before the target is created. The destination's parent must already exist, be a physical directory without symlinked ancestors, and be outside the source checkout. The destination itself must not exist, including as a dangling symlink. On macOS, resolve aliases such as `/tmp` with `realpath` first.

The output includes thin route glue, a language dependency manifest, `project.mjs`, two private check-fixture helpers, `.env.example`, and `feature-auth.json`. It excludes authentication implementations, upstream tests, caches, build products, and binaries. All source dependency paths are relative. Moving the output requires preserving its relative layout with the source checkout, or updating both the dependency manifest and `feature-auth.json`. The source commit, when available, and manifest fingerprint provide provenance; local modifications are not pinned or auto-updated. Metadata includes `checkProtocolVersion: 1`, used by the main Feature Standards CLI to refuse older memory-only runners.

```sh
cd /physical/path/to/new-auth-app
node project.mjs build
node project.mjs check
# Explicitly export configuration from the guidance in .env.example:
node project.mjs start
```

Build requirements are Python 3.12+ with `uv`, Go 1.26+, JDK 21+ with the source Maven wrapper, or Rust 1.93.1+ with Cargo. Java uses the checkout's Maven coordinates, creates a generated POM overlay pointing to the original library source, and keeps its build output and Maven repository under `.feature-auth/`. No authentication source is copied and the original checkout is not edited. Other stack outputs stay in the generated project; dependency download caches may be populated.

Every v2/v3 check additionally needs `uv` and Python 3.12+ for the source checkout's frozen `tools` fixture environment, including checks of Go, Java, and Rust applications. The helper may download its declared test dependencies. This requirement belongs to the database checker; the runtime library uses its own language's dependencies.

`--check` and the generated `check` command build and exercise the **recorded profile**. The fixture replaces inherited `AUTH_*` settings with synthetic values, binds a unique loopback port, and stops its own server afterward. Every profile checks:

- Anonymous protected-route rejection.
- Login and the same user returned by the protected route.
- Independent sessions and rejection of another session's CSRF without losing authentication.
- Logout and rejection of a copied old session cookie by both protected and authentication routes.

v2/v3 also restart the generated server and verify that a database session survives. v3 adds registration, refusal before email verification, single-use confirmation, password reset, revocation of both existing user sessions, token replay rejection, and login with the new password. `runProject('check', directory)` returns `{ schemaVersion: 1, stack, profile, passed, checks, database }`; the direct command prints that JSON receipt. Success names the actual profile, with database creation/drop flags for database profiles.

For v2/v3 checks, explicitly export `FEATURE_STANDARDS_TEST_DATABASE_URL` for a dedicated local PostgreSQL test service. The URL must have a loopback host, an explicit port, a `feature_standards_test*` database name, and no query options other than optional `sslmode=disable`. Nonempty `PG*` settings are refused. The role needs permission to create/drop test databases. The checker does not use `AUTH_DATABASE_URL` as a fallback and refuses missing/unsafe test setup before building or connecting.

The supplied database is an administrative connection only. The checker creates a unique task-owned database, applies v2/schema 1 or v3/schema 2 and public demo fixtures there, and drops that owned database after completion or failure. It does not reset the supplied database's tables or data. v3 verification/reset capabilities travel only through private local child pipes; no SMTP server is called. Generation, normal build/start/demo, and application startup do not apply DDL or seed data. A failed check keeps the generated project for inspection.

These checks do not run browser UI, SMTP delivery, HTTPS, or production deployment checks. The repository's [consumer-profile tests](../examples/consumer-python-react/PROFILE_TESTS.md) cover the existing React consumers separately.

Normal `start` selects the profile recorded in `feature-auth.json`: memory for v1, PostgreSQL/schema 1 for v2, and PostgreSQL/schema 2 with account lifecycle for v3. Secure cookies and non-demo behavior remain the default. `.env.example` contains guidance, not database credentials; it is not automatically loaded. Supply a real origin and application settings through your environment. For local HTTP only, `node project.mjs demo` explicitly enables demo mode and non-Secure cookies for the selected profile. v2/v3 still require a configured database.

For database profiles, create an appropriate dedicated database and set `AUTH_DATABASE_URL` outside the repository. Review the selected profile before changing an existing database. From the source checkout, run migration explicitly:

```sh
# v2 only: browser-session-v2, schema 1
uv run --frozen --project tools python tools/auth_db.py migrate

# v3 only: browser-session-v3, schema 2
uv run --frozen --project tools python tools/auth_db.py migrate-accounts
```

These are user-run application database operations; generation, build, start, and demo never run migrations or seed data. The explicit check fixture applies migrations only to its freshly created owned database. v2 and v3 use different schema versions, so do not switch an existing application database between profiles without the documented migration plan. See [PostgreSQL v2](postgres-v2.md), [account v3](account-v3.md), and the respective specifications. Mail delivery requires separate explicit configuration and an explicitly run worker.

To verify CLI development changes:

```sh
npm --prefix packages/create-feature-auth ci
npm --prefix packages/create-feature-auth test
# All backend toolchains plus the explicit local test DB are required; JAVA_HOME selects JDK 21+.
npm --prefix packages/create-feature-auth run check:generated
# Explicit memory-only alternative, without PostgreSQL:
npm --prefix packages/create-feature-auth run check:generated:memory
```

Safety tests cover fresh generation of all 12 stack/profile combinations, existing targets, dangling links, destination symlinks, source escapes, malformed manifests, invalid CLI options, and database routing rejection. `check:generated` exercises all 12 actual stack/profile combinations, with one task-owned build directory per stack and real incremental builds on each check. Every database profile gets its own fresh UUID database. It verifies source fingerprints and normal/error fixture cleanup, then removes only its own temporary app output. `check:generated:memory` explicitly runs four memory checks. Package publication and registry installation are independently verified release steps.

The published package version is `0.2.0`. Metadata identifies [jongko54](https://github.com/jongko54) as author and includes the `jongko54` and `feature-standards` keywords; see the [release receipt](npm-workflow-release-2026-11-04.json) and [npm discovery](npm-discovery.md) for verified installation and dated search results.
