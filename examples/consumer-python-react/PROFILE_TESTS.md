# Independent PostgreSQL consumer profiles

The same thin React frontend exercises the independent Python, Go, Java and Rust
consumer applications. Each application imports its public backend library and
adds its own protected `/api/profile` route. The frontend imports
`@ugauga/feature-standards-react-auth/api`; it contains no copied authentication,
session storage or database implementation.

From the repository root, install the Python tools and consumer dependencies,
build the React client, and install Chromium:

```sh
uv sync --frozen --project tools
uv sync --frozen --project examples/consumer-python-react
npm --prefix clients/react ci
npm --prefix examples/consumer-python-react ci
npm --prefix examples/consumer-python-react run build
npm --prefix examples/consumer-python-react exec -- playwright install chromium
uv run --frozen --project tools python -m unittest discover -s tests -p test_consumer_profiles.py
uv run --frozen --project tools python tests/consumer_profiles.py --browser
```

The full matrix requires Python 3.12+, uv, Node.js 22.12+, Go, JDK 21, Rust and
PostgreSQL server binaries. The repository Maven wrapper builds and installs the
Java library locally before building its consumer. Set `JAVA_HOME` for JDK 21 if
it is not your default. The Rust executable is resolved from Cargo build metadata,
including when `CARGO_TARGET_DIR` is set.

By default, `pg_support.database` creates one temporary local PostgreSQL instance.
Set `FEATURE_STANDARDS_PG_BIN` when its server binaries are outside `PATH`.
The harness creates eight separate randomly named databases, one per language and
profile, then drops only those newly created databases. It never resets the
fixture's existing schema and does not modify the parent process environment.
For an existing fixture, `FEATURE_STANDARDS_TEST_DATABASE_URL` must identify an
approved, task-owned loopback database with an explicit port and a name beginning
with `feature_standards_test`. The fixture role needs `CREATEDB`. Only the optional
`sslmode=disable` URI query is allowed; clear all `PG*` environment variables.
Never use an application or production database.

The independent frontend uses port **5175**, proxies `/auth`, `/api` and
`/healthz` to the selected consumer, and refuses to reuse an existing listener.
Each backend uses a temporary free port. Run a smaller matrix with
`--backend python` (or `go`, `java`, `rust`) and/or
`--profile browser-session-v2` (or `browser-session-v3`). Omit `--browser` for the
HTTP and restart checks alone.

Both profiles verify protected identity, anonymous and forged-cookie rejection,
independent sessions, session-bound CSRF, logout invalidation of a copied cookie,
a second user's identity, and session persistence after restarting the consumer.
The health response must name the selected profile. v2 also rejects registration.
v3 checks registration, unverified login rejection, private local email capture,
verification, protected access, password reset, rejection of old sessions and
passwords, and preservation of administrator disabling.

Chromium runs the existing three consumer scenarios for both profiles and one
additional v3 account scenario: **28 browser scenarios** across the full matrix.
The v3 screen is enabled only with `VITE_AUTH_ACCOUNT_LIFECYCLE=true`. Verification
and reset links keep their token in a fragment, remove it from the address bar,
and require an explicit button click. Passwords and tokens are never persisted in
browser storage. The capture tool writes new private files in a temporary
directory. The browser test rebases only its validated local link onto port 5175;
it does not send mail. Traces, screenshots and video are disabled, and account
failure output excludes capability-bearing navigation logs. These are local
package-consumer integration checks, not registry-publication or security-audit
evidence.
