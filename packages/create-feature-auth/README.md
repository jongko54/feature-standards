# Create Feature Auth

Create a thin Python, Go, Java, or Rust application that imports Feature Standards authentication and exposes a protected `GET /api/profile`. Authentication, sessions, CSRF protection, account flows, and database access remain in the shared library.

Node.js 22.12 or newer is required. The CLI has no runtime npm dependencies. Generation itself needs no language compiler, database, or network connection. Building the generated app needs the selected language toolchain and can download dependencies.

```sh
npx @ugauga/create-feature-auth \
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

`--check` and `node project.mjs check` build the generated app and run a temporary HTTP server on a unique loopback port. They always use the public memory-v1 demo fixture, including when v2 or v3 is selected. Checks cover anonymous rejection, login, shared protected identity, CSRF rejection, logout, and rejection of the copied old cookie. They never connect to PostgreSQL and do not certify the selected database profile.

`node project.mjs start` selects the recorded profile and keeps the library's secure defaults. Review `.env.example` and export configuration explicitly; the runner does not load `.env`. `node project.mjs demo` explicitly enables local HTTP and demo mode for the selected profile. v2/v3 still need a database and explicit migration. No command migrates, seeds, creates databases, or sends mail automatically.

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
```

The integration command creates temporary apps, performs builds and real HTTP checks, verifies source-file fingerprints, and removes only its own temporary directory.
