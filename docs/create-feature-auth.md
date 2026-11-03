# Generate an authentication consumer

`@ugauga/create-feature-auth` creates a thin application that reuses the repository's public authentication library. It supports Python/FastAPI, Go/net/http, Java/Spring Boot, and Rust/Axum, with a protected `GET /api/profile`. It keeps authentication behavior in the library instead of generating another implementation.

The source checkout must be explicit. Server registry publication is separate from project generation; local source dependencies work before those publications are available. React is supported through the existing [React consumer](../examples/consumer-python-react/README.md), not a generated frontend in this CLI.

```sh
# From this checkout, without installing or publishing an npm package:
node packages/create-feature-auth/src/cli.mjs \
  --source "$PWD" \
  --stack go \
  --profile browser-session-v1 \
  --dest /physical/path/outside-the-checkout/new-auth-app \
  --check

# With the published npm package:
npx @ugauga/create-feature-auth \
  --source /absolute/path/to/feature-standards \
  --stack rust \
  --profile browser-session-v3 \
  --dest /physical/path/to/new-auth-app
```

Node.js 22.12+ is required. There are no runtime npm dependencies. Generation reads bundled consumer templates and the chosen checkout's manifest and package metadata; it does not invoke a compiler, install dependencies, or access a database unless `--check` is supplied. The source is trusted build input, not sandboxed code.

`--source`, `--stack`, and `--dest` are required. `--profile` defaults to `browser-session-v1`; v2 and v3 must be selected explicitly. Unsupported selections fail before the target is created. The destination's parent must already exist, be a physical directory without symlinked ancestors, and be outside the source checkout. The destination itself must not exist, including as a dangling symlink. On macOS, resolve aliases such as `/tmp` with `realpath` first.

The output includes thin route glue, a language dependency manifest, `project.mjs`, `.env.example`, and `feature-auth.json`. It excludes authentication implementations, upstream tests, caches, build products, and binaries. All source dependency paths are relative. Moving the output requires preserving its relative layout with the source checkout, or updating both the dependency manifest and `feature-auth.json`. The source commit, when available, and manifest fingerprint provide provenance; local modifications are not pinned or auto-updated.

```sh
cd /physical/path/to/new-auth-app
node project.mjs build
node project.mjs check
# Explicitly export configuration from the guidance in .env.example:
node project.mjs start
```

Build requirements are Python 3.12+ with `uv`, Go 1.26+, JDK 21+ with the source Maven wrapper, or Rust 1.93.1+ with Cargo. Java uses the checkout's Maven coordinates, creates a generated POM overlay pointing to the original library source, and keeps its build output and Maven repository under `.feature-auth/`. No authentication source is copied and the original checkout is not edited. Other stack outputs stay in the generated project; dependency download caches may be populated.

`--check` and the generated `check` command always build and exercise **memory v1**, regardless of the selected profile. The fixture replaces inherited `AUTH_*` settings, uses only public demo credentials, binds a unique loopback port, and stops its own server afterward. Its HTTP checks cover:

- Anonymous protected-route rejection.
- Login and the same user returned by the protected route.
- CSRF rejection without losing the session.
- Logout and rejection of a copied old session cookie by both protected and authentication routes.

This verifies the generated adapter against the shared memory library. It does not run browser UI, database persistence, registration, password reset, SMTP, HTTPS, or production deployment checks. A v3 project passing this check is not a v3 database test result. The repository's [consumer-profile tests](../examples/consumer-python-react/PROFILE_TESTS.md) cover the existing React consumers separately.

Normal `start` selects the profile recorded in `feature-auth.json`: memory for v1, PostgreSQL/schema 1 for v2, and PostgreSQL/schema 2 with account lifecycle for v3. Secure cookies and non-demo behavior remain the default. `.env.example` contains guidance, not database credentials; it is not automatically loaded. Supply a real origin and application settings through your environment. For local HTTP only, `node project.mjs demo` explicitly enables demo mode and non-Secure cookies for the selected profile. v2/v3 still require a configured database.

For database profiles, create an appropriate dedicated database and set `AUTH_DATABASE_URL` outside the repository. Review the selected profile before changing an existing database. From the source checkout, run migration explicitly:

```sh
# v2 only: browser-session-v2, schema 1
uv run --frozen --project tools python tools/auth_db.py migrate

# v3 only: browser-session-v3, schema 2
uv run --frozen --project tools python tools/auth_db.py migrate-accounts
```

These are user-run database operations; generation, build, start, demo, and check never run migrations or seed data. v2 and v3 use different schema versions, so do not switch an existing database between profiles without the documented migration plan. See [PostgreSQL v2](postgres-v2.md), [account v3](account-v3.md), and the respective specifications. Mail delivery requires separate explicit configuration and an explicitly run worker.

To verify CLI development changes:

```sh
npm --prefix packages/create-feature-auth ci
npm --prefix packages/create-feature-auth test
# All backend toolchains are required; JAVA_HOME must select JDK 21+.
npm --prefix packages/create-feature-auth run check:generated
```

Safety tests cover all 12 stack/profile combinations, existing targets, dangling links, destination symlinks, source escape attempts, malformed manifests, and invalid CLI options. The integration command generates four fresh applications, builds and exercises each through HTTP, checks that source fingerprints did not change, and removes its own temporary output. Package publication and registry installation are independently verified release steps.
