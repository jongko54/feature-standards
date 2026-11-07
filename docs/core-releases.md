# Core library releases

The core 0.1.0 packages contain authorization and listing together. Authentication remains in its existing packages. Main catalogs [0.3.0](npm-release-0.3.0.json) and [0.3.1](npm-release-0.3.1.json) were published separately; their receipts confirm exact public tarballs and fresh installed consumers resolving all 25 contexts. Each catalog captures the publication evidence available when it was built.

Catalog [0.3.2](npm-release-0.3.2.json) captures the verified releases for all five core ecosystems. Its public archive matches the reviewed CI artifact. An empty-cache registry installation passed the installed binary and all 25 contexts, including ten core selections with matching published package receipts.

## Coordinates and publication state

| Ecosystem | Core coordinate | Initial release path |
| --- | --- | --- |
| npm | `@ugauga/feature-standards-core@0.1.0` | Reviewed tarball, maintainer CLI authentication; future `npm-core-v*` OIDC tags |
| Python | `feature-standards-core==0.1.0` | Verified PyPI Trusted Publisher for `publish-core.yml`, environment `pypi`; initial recovery run and immutable `python-core-v0.1.0` tag |
| Rust | `feature-standards-core@0.1.0` | Maintainer Cargo credential; future `rust-core-v*` OIDC tags after binding the crate publisher |
| Java | `io.github.jongko54:feature-standards-core:0.1.0` | Production-signed plain JAR/POM/sources/Javadoc bundle uploaded through Central Portal |
| Go | `github.com/jongko54/feature-standards/libraries/go@v0.1.0` | Immutable `libraries/go/v0.1.0` module tag and public module proxy verification |

[The registry receipt](core-release-0.1.0.json) verifies all five core packages through public downloads and fresh consumers. Java additionally has Portal `PUBLISHED` status, all 24 public files matching the signed bundle, four production signatures, sixteen checksums and all three JARs matching reviewed CI artifacts. Set `published: true` only when the exact coordinate has both download and consumer checks. Creating an account publisher, accepting an upload and making its public files available are separate states. The npm core first publication used maintainer CLI authentication and 2FA; it does not prove a future OIDC binding. Python's configured publisher completed its recorded OIDC recovery run.

## Build and verify without uploading

From clean source with Node 22.12+, Python 3.12+, Go 1.26, JDK 21 and Rust 1.93.1:

```sh
uv run --frozen --project tools python tools/check_core_features.py --feature all --stack all
uv run --frozen --project tools python tools/check_core_distributions.py --target all --out-dir dist/core-checked
```

The distribution checker installs the Python wheel and npm tarball into separate temporary projects and executes all 76 shared cases through installed APIs. It tests the extracted standalone crate, a plain Java JAR with an external source consumer and no framework classpath, and an isolated Go module copy. Rust/Go include local copies of the shared fixtures; the native checker requires byte equality with the canonical contracts. Python and npm use curated file lists. The command records hashes, source revision, dirty state and `published: false`. `--allow-dirty` is available for local preparation only.

The new `publish-core.yml` workflow builds reviewed artifacts, supports build-only manual dispatch by default, and uses tags for configured npm/PyPI/Rust OIDC publishing. It requires full successful main source CI for the same exact source SHA before upload. It reuses the existing `npm`, `pypi`, and `crates-io` environments. New publishers require an explicit account binding; no long-lived registry tokens are committed.

## Java signing

Use the existing production signing identity. After clean full source CI succeeds, run in a terminal so GPG can request its passphrase privately:

```sh
uv run --frozen --project tools python tools/sign_core_maven.py \
  --key 892B5FC971080E67186FF29DD8E42CD147DAB7C7
```

The script creates `dist/core/central/feature-standards-core-0.1.0-bundle.zip`, verifies four production-key signatures and creates sixteen artifact checksums. It signs the unchanged source POM and a plain runtime JAR with sources/Javadoc. It never uploads, exports a private key, requests a new key, or stores a passphrase. Upload that reviewed bundle to the existing `io.github.jongko54` namespace, then verify Portal publication, all public files and a fresh dependency consumer independently.

If the existing signing setup stores its passphrase in macOS Keychain, check that setup before requesting manual input. An empty GPG agent cache does not mean the stored credential is missing. Retrieve only the configured service/account for the exact production fingerprint, pass the value privately through a file descriptor, and keep it out of logs, command arguments, environment variables and temporary files. Do not create a replacement key or reset its passphrase to recover an existing release.

Never move a published tag or overwrite an existing registry version. Inspect public state before retrying an upload that might already have been accepted. Initial registry availability, search indexing, artifact integrity, full CI and production readiness are separate claims.

## Initial Python recovery

Five initial release tags were pushed together; GitHub [does not create tag events when more than three are pushed at once](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#push). Tags were preserved. The explicit `publish_initial_python` manual option publishes only the Python 0.1.0 archives from clean source `8aabcb5` and reviewed build `42199662926`. The job pins that checkout, verifies the immutable tag, requires successful full main CI for the artifact source, checks the original artifact run and verifies every archive hash before PyPI OIDC. The publisher workflow commit is recorded separately from the archive source commit.
