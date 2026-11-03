# Server package releases

Building, publishing, and installing from a public registry are separate verification steps. A local distribution check does not imply a public release.

| Stack | Package / version | Distribution | Registry prerequisite |
|---|---|---|---|
| Python | `feature-standards-python-auth` 0.2.0 | wheel + sdist | PyPI account and pending trusted publisher |
| Go | `github.com/jongko54/feature-standards/implementations/go-net-http` 0.1.0 | nested-module Git tag | Published and independently installed; [receipt](go-release-0.1.0.json) |
| Java | `io.github.jongko54:java-spring-auth:1.0.0` | executable JAR, `library` classifier, sources + Javadoc | Central namespace, signing key, user token |
| Rust | `feature-standards-auth` 0.1.0 | standalone `.crate` | crates.io account and email verification |

PyPI and crates.io returned project-not-found on 2026-11-03 before this batch's release work. Actual registry receipts are recorded separately in the validation report. No server registry credentials were found in the checked environment variables or standard credential files.

The Maven group changed from the unpublished `dev.featurestandards` coordinate to `io.github.jongko54`. Java packages and public APIs stay `dev.featurestandards.auth`; consumers must update the dependency group. The GitHub-owned namespace can be verified through a corresponding Central account; this repository does not claim account setup is complete.

## Build and verify

The [feature-standards-v0.2.0 GitHub release](https://github.com/jongko54/feature-standards/releases/tag/feature-standards-v0.2.0) provides server archives, the original Java POM, MIT license, `SOURCE.json`, and `SHA256SUMS` from successful exact-source CI. All eight anonymous public downloads matched the reviewed CI files. The Python wheel was also installed from its public release URL into a fresh external virtual environment and its public APIs imported successfully. See the [release receipt](npm-workflow-release-2026-11-04.json). These assets are an alternative distribution path while language-registry account setup is pending; they do not establish publication on PyPI, Maven Central, or crates.io.

After the release assets and checksums are verified, Python can install the wheel URL directly:

```sh
python -m pip install 'https://github.com/jongko54/feature-standards/releases/download/feature-standards-v0.2.0/feature_standards_python_auth-0.2.0-py3-none-any.whl'
```

For Java, download `java-spring-auth-1.0.0-library.jar` and `java-spring-auth-1.0.0.pom` from that release, then install the plain library with its dependency metadata:

```sh
mvn install:install-file \
  -Dfile=java-spring-auth-1.0.0-library.jar \
  -DpomFile=java-spring-auth-1.0.0.pom -Dclassifier=library
```

Consumers select `io.github.jongko54:java-spring-auth:1.0.0` with classifier `library`. The POM is required for transitive dependencies; the executable application JAR is not the library artifact. Rust consumers can extract the release's `feature-standards-auth-0.1.0.crate` into their own vendor directory and use the unpacked library as a Cargo path dependency. The [independent distribution checker](validation-server-distributions-2026-11-04.md) verifies that unpacked-crate consumption outside the original checkout. Keep the recorded version/checksum when vendoring; this is separate from crates.io version resolution.

The installation parameters follow [Apache Maven's install-file reference](https://maven.apache.org/plugins/maven-install-plugin/install-file-mojo.html); unpacked Rust consumption follows [Cargo path dependencies](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#specifying-path-dependencies).

From the repository root:

```sh
uv build --project implementations/python-fastapi --out-dir dist/python
uvx --from twine==7.0.0 twine check --strict dist/python/*
implementations/java-spring/mvnw -f implementations/java-spring/pom.xml verify
cargo package --locked --manifest-path implementations/rust-axum/Cargo.toml
```

Use a clean checkout for release artifacts. `cargo package --allow-dirty` is only for local precommit checks. Normal crate tests compile outside the monorepo; explicitly ignored DB tests need a full checkout and dedicated fixtures. Python sdists build wheels without repository tools. Installing or starting any server package performs no migration or seeding.

### Test the actual local distributions in separate consumers

The distribution checker snapshots the committed server and consumer paths into a private temporary directory. It builds a wheel/sdist, a normal Java library-classifier JAR, and a Cargo package, then removes its own private library source copies before testing consumers. It never edits the original checkout, publishes, connects to a database, or sends SMTP mail. The selected server/consumer paths must be committed; unrelated work elsewhere in the checkout is reported without being included in the snapshot.

```sh
# JDK 21+ must be selected through JAVA_HOME or PATH.
uv run --frozen --project tools python tools/check_server_distributions.py
# Individual stacks are also available:
uv run --frozen --project tools python tools/check_server_distributions.py --stack python
uv run --frozen --project tools python tools/check_server_distributions.py --stack java
uv run --frozen --project tools python tools/check_server_distributions.py --stack rust
```

Python is installed into a fresh virtual environment and checked through its public imports, memory-service lifespan, and health function. Java uses blank Maven settings and a fresh private Maven repository; its consumer verifies the loaded `library` JAR and real loopback HTTP lifecycle. Rust's consumer depends on the unpacked `.crate`, with the private monorepo source copy removed, and runs its memory lifecycle test. Build dependency download caches may still be used by Cargo. These checks establish local artifact reuse, independently of registry account setup or public availability. The [2026-11-04 validation record](validation-server-distributions-2026-11-04.md) records the tested source, hashes, and public registry observations.

## Python trusted publisher

`.github/workflows/publish-python.yml` builds and checks wheel/sdist artifacts. A manual dispatch only builds; a `python-auth-v0.2.0` tag additionally publishes after tag/version and full source CI checks.

Configure the first release's PyPI pending trusted publisher with project `feature-standards-python-auth`, owner `jongko54`, repository `feature-standards`, workflow `publish-python.yml`, and environment `pypi`. Account verification and this trust relationship are required before tagging. No PyPI API token is stored here. See [PyPA's publishing guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/).

## Java / Maven Central

The [signed-bundle checker](maven-release.md) verifies a local fixture with a temporary test key and upload disabled. Its success is separate from account/namespace verification or Central acceptance.

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

No long-lived Cargo token is added to CI. The [Rust release workflow and setup guide](rust-release.md) provide build-only dispatch, exact source/tag checks, temporary OIDC credentials and artifact comparisons. Trusted publishing still requires initial account/release setup; see [crates.io's guide](https://crates.io/docs/trusted-publishing). Packaging alone does not reserve the crate name or publish it.

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

Go `v0.1.0` was published from `eff0d9d6905de5d8729eef07771a5838ee36b1b3` after full main CI succeeded. A new module installed it through normal `go get`, with no local replace, then passed both real loopback consumer lifecycle tests with the race detector. The receipt records module and go.mod checksums.
