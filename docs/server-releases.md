# Server package releases

Building, publishing, and installing from a public registry are separate verification steps. A local distribution check does not imply a public release.

| Stack | Package / version | Distribution | Registry prerequisite |
|---|---|---|---|
| Python | `feature-standards-python-auth` 0.2.0 | wheel + sdist | PyPI account and pending trusted publisher |
| Go | `github.com/jongko54/feature-standards/implementations/go-net-http` 0.1.0 | nested-module Git tag | Remote tag and fresh remote install |
| Java | `io.github.jongko54:java-spring-auth:1.0.0` | executable JAR, `library` classifier, sources + Javadoc | Central namespace, signing key, user token |
| Rust | `feature-standards-auth` 0.1.0 | standalone `.crate` | crates.io account and email verification |

PyPI and crates.io returned project-not-found on 2026-11-03 before this batch's release work. Actual registry receipts are recorded separately in the validation report. No server registry credentials were present in the current local environment.

The Maven group changed from the unpublished `dev.featurestandards` coordinate to `io.github.jongko54`. Java packages and public APIs stay `dev.featurestandards.auth`; consumers must update the dependency group. The GitHub-owned namespace can be verified through a corresponding Central account; this repository does not claim account setup is complete.

## Build and verify

From the repository root:

```sh
uv build --project implementations/python-fastapi --out-dir dist/python
uvx --from twine==7.0.0 twine check --strict dist/python/*
implementations/java-spring/mvnw -f implementations/java-spring/pom.xml verify
cargo package --locked --manifest-path implementations/rust-axum/Cargo.toml
```

Use a clean checkout for release artifacts. `cargo package --allow-dirty` is only for local precommit checks. Normal crate tests compile outside the monorepo; explicitly ignored DB tests need a full checkout and dedicated fixtures. Python sdists build wheels without repository tools. Installing or starting any server package performs no migration or seeding.

## Python trusted publisher

`.github/workflows/publish-python.yml` builds and checks wheel/sdist artifacts. A manual dispatch only builds; a `python-auth-v0.2.0` tag additionally publishes after tag/version and full source CI checks.

Configure the first release's PyPI pending trusted publisher with project `feature-standards-python-auth`, owner `jongko54`, repository `feature-standards`, workflow `publish-python.yml`, and environment `pypi`. Account verification and this trust relationship are required before tagging. No PyPI API token is stored here. See [PyPA's publishing guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).

## Java / Maven Central

The `central-release` profile adds signing and Central Publishing; normal builds do not sign or upload. Verify the `io.github.jongko54` namespace, configure a `central` server in a private Maven settings file with a Central user token, and configure a GPG key in the local keyring. Keep credentials and keys outside the repository.

```sh
implementations/java-spring/mvnw -f implementations/java-spring/pom.xml \
  -Pcentral-release clean deploy
```

This publishes permanently and waits for the Portal's publication status. Consumer projects select `<classifier>library</classifier>`; Central also receives sources and Javadoc. Follow the [official metadata and signing requirements](https://central.sonatype.org/publish/requirements/), [namespace instructions](https://central.sonatype.org/register/namespace/), and [plugin configuration](https://central.sonatype.org/publish/publish-portal-maven/).

## Rust / crates.io

After account and email verification, run `cargo login` privately and publish from a clean reviewed checkout:

```sh
cargo publish --locked --manifest-path implementations/rust-axum/Cargo.toml
```

No long-lived Cargo token is added to CI. Trusted publishing can be configured after initial account/release setup; see [crates.io's guide](https://crates.io/docs/trusted-publishing). Packaging alone does not reserve the crate name or publish it.

## Go versioned module

The subdirectory module needs a prefixed tag:

```sh
# Replace VERIFIED_SOURCE_COMMIT with the reviewed commit whose full CI passed.
git tag implementations/go-net-http/v0.1.0 VERIFIED_SOURCE_COMMIT
git push origin refs/tags/implementations/go-net-http/v0.1.0
# In a separate module, without a local replace directive:
go get github.com/jongko54/feature-standards/implementations/go-net-http/auth@v0.1.0
```

Verify the remote tag and a fresh installation before marking the Go package published in the manifest. Never move an already published version tag.
