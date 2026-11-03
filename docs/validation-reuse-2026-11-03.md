# Reuse and release validation — 2026-11-03

This batch preserves the authentication HTTP contracts and database schemas. It adds a thin consumer generator, independent database consumers, reproducible AI evaluation, and release configuration. Registry configuration and publication are tracked separately from local artifacts.

## Executed local checks

| Check | Observed result |
|---|---|
| Common v1 conformance, four reference servers | 19 HTTP tests per backend, Secure cookie probe per backend, and 32 Chromium scenarios passed |
| Independent consumers, four backends × PostgreSQL v2/v3 | Eight isolated UUID databases; HTTP session separation/revocation, restart persistence, and 28 Chromium scenarios passed |
| Bootstrap CLI | Seven safety tests, 12 stack/profile generation combinations, four fresh builds and real memory HTTP lifecycle checks passed; source fingerprints preserved |
| CLI distribution | Installed the reviewed tarball in a fresh npm project; symlinked executable help and Rust/v3 generation passed |
| Python harness suite | 121 tests discovered, 88 passed and 33 DB-dependent tests skipped without their dedicated fixture environment |
| Catalog and contracts | Five stacks / three profiles checked; v1/v2/v3 OpenAPI and scenario source mapping and SMTP mapping passed; mapping is not execution coverage |
| Lint/config | Ruff, actionlint 1.7.12, workflow template equality, and git diff whitespace checks passed |
| Independent code review | No concrete introduced P1/P2 found; added generated-app runtime checks to CI following the review |

The new consumer harness creates and drops only its own random databases. A supplied fixture role needs CREATEDB. It does not reset the caller's existing database schema. Browser failures are reported without dumping capability-bearing output.

## Distribution checks

- Python 0.2.0: wheel and sdist built; Twine 7.0.0 strict metadata/rendering checks passed. Built a wheel from the sdist. Installed the original wheel into an isolated environment outside the checkout; the public factory/dependency passed protected-route login, CSRF logout, and copied-cookie revocation checks.
- Java 1.0.0: the new `io.github.jongko54` group built and installed locally with executable, library, sources, and Javadoc JARs. A separate Maven consumer built and served both PostgreSQL profiles. Maven Central credentials/signing are not configured by this work.
- Rust 0.1.0: `cargo package --locked --allow-dirty` packaged and verified a standalone crate. Packaged-source tests passed; explicitly ignored DB/TLS tests require the repository fixtures. The local Cargo cache emitted permission warnings, with successful process exits; no cache permissions were changed.
- The CLI's `--check` always checks memory v1, including for a v2/v3 generated project. Database and browser coverage above comes from the independent consumer matrix, not this flag.

## Remote/account state

GitHub private vulnerability reporting was enabled and GET-verified on `jongko54/feature-standards`. The security policy links the actual private report form. No report was sent.

The npm workflow uses exact package/version/tag matching and checks full main-source CI before uploading the built tarball with OIDC. Manual dispatch builds only. npm requires account 2FA to establish the trusted publisher; the workflow file alone does not establish it. The Python workflow similarly requires a PyPI pending trusted publisher.

PyPI and crates.io project lookups returned 404 before this batch; no local PyPI/Cargo/Central credentials were present. These registries must not be described as published on the strength of local artifact checks. See [server release setup](server-releases.md).

The paired model evaluation is recorded separately when all 24 trials finish. A requested model identifier is not trace-confirmed model identity, and measured failures/missing usage must remain in the report.
