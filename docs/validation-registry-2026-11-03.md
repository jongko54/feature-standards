# Registry activation follow-up validation — 2026-11-03

This follow-up continues from `6f5b29f`. It prepares publisher validation without changing authentication HTTP contracts, DB schemas, server APIs, or the published Go v0.1.0 module.

## Local evidence

- CLI0.1.1: a generation test reproduced stale `generatorVersion=0.1.0` after a package version bump. Reading installed package metadata fixed it. Seven CLI safety tests passed, including all12 stack/profile combinations. An actual installed tarball executable generated provenance0.1.1 correctly.
- API0.1.2: eight API tests and the five-file tarball install/ESM/HTTP/TypeScript check passed. JavaScript, declarations, and MIT license bytes match the published0.1.1 artifact. Only documentation and package metadata change.
- Maven: eleven focused tests, including inherited-environment exclusion, upload-trap methods, metadata/signature/checksum refusal, passed. A full local checker run verified five artifacts, five synthetic-key signatures and twenty checksums in a30-file bundle. Central requests and source changes were0. The temporary key and bundle were removed; `published=false` is explicit.
- Rust: actionlint1.7.12, template equality, exact release tag acceptance/wrong-version rejection, identical successive packages,24 extracted-source tests and three external API tests passed. Three explicit DB/TLS cases were ignored for this packaging check; existing full source CI remains a separate release gate.
- Full Python harness discovery:132 tests,99 passed and33 dedicated-fixture cases skipped in this local command. Ruff, workflow syntax/template, manifest, and whitespace checks passed.

[Preflight artifact hashes and fixture receipt](registry-preflight-2026-11-03.json) distinguish prepared tarballs from registry publications. Fixture signing keys and timestamps vary, so their bundle hash is an observation rather than a deterministic release identity.

## Review and isolation

Independent review found Maven wrapper cache/startup-rc leakage from an inherited HOME. The checker now preserves HOME while forcing a temporary MAVEN_USER_HOME, MAVEN_SKIP_RC, private Maven repository/settings and temporary GNUPGHOME. The actual installed wrapper/startup scripts were inspected, an isolation regression was added, and the signed-bundle check was rerun. No remaining concreteP1/P2 was reported in the reviewed changes.

The fixture enforces Central plugin0.12.0 bundle-only mode, disables published-component queries, and replaces its Central endpoint with a loopback trap. It can read public Maven dependencies, so this is neither an air-gapped build nor a sandbox for untrusted source.

## Release/account boundary

Prepared source versions are API0.1.2 and CLI0.1.1. The registry remained API0.1.1 and no public CLI version during initial checks. Publishing requires successful full main CI for the exact release source, npm account login and trusted publisher setup. CLI0.1.0 must be bootstrapped before its publisher can be configured; then the new versions can validate actual OIDC publication.

The existing npm login token returned401. A web login session was started; when the older CLI fell back to an interactive legacy prompt, it was stopped and a supported current CLI web session was started. No password or authentication code was requested in chat. A waiting login URL is not proof of authentication or publication.

Python still needs its PyPI pending publisher. Maven still needs a verified Central namespace/token and maintainer-controlled production signing key. Rust still needs account/email verification, initial publication and its configured OIDC publisher. The local fixture and build-only workflows do not complete those account operations. See [Maven setup](maven-release.md), [Rust setup](rust-release.md), and [server release status](server-releases.md).
