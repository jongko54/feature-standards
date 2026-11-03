# Create Feature Auth

Create a thin Python, Go, Java, or Rust application that imports Feature Standards authentication and exposes a protected `GET /api/profile`. Authentication, sessions, CSRF protection, account flows, and database access remain in the shared library.

Part of [Feature Standards](https://github.com/jongko54/feature-standards) by [jongko54](https://github.com/jongko54).

Node.js 22.12 or newer is required. The CLI has no runtime npm dependencies. Generation itself needs no language compiler, database, or network connection. Building the generated app needs the selected language toolchain and can download dependencies.

The selected-profile check protocol described below requires version `0.2.0`. Use `node packages/create-feature-auth/src/cli.mjs` from this checkout until that version's registry publication is verified. Existing `0.1.1` consumers keep the earlier memory-only check behavior.

```sh
npx @ugauga/create-feature-auth@0.2.0 \
  --source /absolute/path/to/feature-standards \
  --stack python \
  --profile browser-session-v1 \
  --dest /absolute/path/to/new-auth-app \
  --check
```

`--source`, `--stack`, and `--dest` are required. `--profile` defaults to `browser-session-v1`. Supported stacks are `python`, `go`, `java`, and `rust`; supported profiles are `browser-session-v1`, `browser-session-v2`, and `browser-session-v3`. React UI generation is outside this command's scope; the existing React consumer can use the generated API.

An explicit source checkout is required while server packages are being prepared for their language registries. Language dependency paths and `feature-auth.json` use relative paths. Keep the source checkout and generated project in the same relative layout when moving them. Java dependency coordinates come from the chosen checkout's POM. The generator records the source commit when available and a manifest SHA-256 fingerprint; it does not pin uncommitted source changes or fetch updates.

The target must be a new directory with an existing physical parent outside the source checkout. Existing files, directories, and dangling links are refused. Symlinked destination parents and selected source files escaping the checkout are refused. On systems where `/tmp` is a symlink, pass the physical directory returned by `realpath` instead. The CLI copies bundled consumer glue only; it does not copy authentication implementations, tests, caches, build output, or binaries. It never edits the source checkout or writes credentials.

```sh
cd /absolute/path/to/new-auth-app
node project.mjs build
node project.mjs check
# Export the settings described in .env.example, then:
node project.mjs start
```

`--check` and `node project.mjs check` build the generated app and exercise the **selected profile** on a unique loopback HTTP port. They return a JSON receipt with the stack, actual profile, passed checks, and database-isolation flags. Generated metadata includes `checkProtocolVersion: 1`; the exported `runProject('check', directory)` returns the same receipt for the main Feature Standards CLI.

| Selected profile | Checks |
| --- | --- |
| v1 | Memory sessions: anonymous and forged access, login, protected identity, independent sessions, CSRF rejection, logout, copied-cookie rejection |
| v2 | The same lifecycle using PostgreSQL, plus session persistence across server restart |
| v3 | v2 checks plus registration, single-use email verification, password reset, revocation of both existing sessions, replay rejection, and replacement-password login |

v2/v3 checks require an explicit dedicated test connection in `FEATURE_STANDARDS_TEST_DATABASE_URL`, with a numeric loopback host or `localhost`, an explicit port, a `feature_standards_test*` database name, and only optional `sslmode=disable`. The database role must be able to create/drop test databases. Other `PG*` routing settings are refused. `AUTH_DATABASE_URL` is never used as the check fixture's fallback.

The supplied database is only an administrative connection. The check creates a fresh UUID-named database, applies the selected schema and demo fixtures **there**, and drops that owned database after success or failure. It does not reset the supplied database's schema or data. Verification/reset capabilities stay in private child-process pipes; no SMTP server or public inbox is used. These are HTTP checks, not browser UI, SMTP delivery, or production deployment verification. If a check fails, the generated project remains available for inspection.

`node project.mjs start` selects the recorded profile and keeps the library's secure defaults. Review `.env.example` and export configuration explicitly; the runner does not load `.env`. `node project.mjs demo` explicitly enables local HTTP and demo mode for the selected profile. v2/v3 still need a database and explicit migration. Generation, build, start, and demo do not migrate or seed an application database. The explicit `check` command uses the isolated fixture described above and never sends mail.

| Stack | Build requirements | Dependency |
| --- | --- | --- |
| Python | Python 3.12+ and `uv` | Source-relative Python package |
| Go | Go 1.26+ | Source-relative module replacement |
| Java | JDK 21+ and the source Maven wrapper | Generated Maven overlay and local repository |
| Rust | Rust 1.93.1+ and Cargo | Source-relative Cargo dependency |

For Java, the runner stages POM metadata under `.feature-auth/`, compiles against the original source directories, and keeps outputs and Maven artifacts in the generated project. Python environments, Go binaries, and Rust build outputs also stay in the generated project; language dependency caches may be populated normally. Builds execute code from the explicitly selected checkout and are not a sandbox for untrusted source.

See the repository's [complete generation guide](https://github.com/jongko54/feature-standards/blob/main/docs/create-feature-auth.md), including explicit database migration commands and validation limits.

For contributors:

```sh
npm ci
npm test
# Requires all four backend toolchains; set JAVA_HOME to JDK 21+.
npm run check:generated
# Four-stack memory-only smoke, without a database:
npm run check:generated:memory
```

`check:generated` requires the dedicated test connection and runs all four stacks against all three profiles. Fresh generation for all 12 combinations is covered by unit tests. The integration matrix reuses one task-owned build directory per stack and invokes real incremental builds for each profile; each database check still gets a separate random database. It verifies source-file fingerprints, cleanup on normal/error fixture paths, and removes its own temporary app directories. `check:generated:memory` explicitly limits the matrix to four v1 checks.
