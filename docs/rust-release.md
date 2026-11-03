# Rust crate release

`feature-standards-auth` is the reusable Axum library and reference binary. Its current source version is `0.1.0`. A successful local package or workflow build is not a crates.io publication.

The [Rust release workflow](../.github/workflows/publish-rust.yml) supports two operations:

| Trigger | Behavior |
|---|---|
| Manual dispatch | Test and package the crate, then retain a `.crate` artifact for review; no publishing job runs |
| `rust-auth-vX.Y.Z` tag push | Build, require an exact metadata/tag match and successful full main-branch CI for the same commit, compare the rebuilt artifact, then publish through OIDC |

The workflow pins Rust/Cargo `1.93.1` and the official `rust-lang/crates-io-auth-action` v1.0.6 commit `3268eb413133e2960fa4ae0e963ca76380c54cd9`. Only the publish job receives `id-token: write`; it exchanges the GitHub identity for a short-lived crates.io token. No long-lived Cargo token is stored in repository secrets. The action revokes its temporary token when the job finishes. See the [official action](https://github.com/rust-lang/crates-io-auth-action/tree/3268eb413133e2960fa4ae0e963ca76380c54cd9).

## First publication and account setup

As documented by [crates.io trusted publishing](https://crates.io/docs/trusted-publishing), the crate must already exist and the configuring account must own it. The first publication uses a normal crates.io API token. Creating this workflow does not reserve the crate name or create that trust relationship.

1. Sign in to crates.io with the intended GitHub identity and complete email/account verification.
2. Review the clean release commit and its successful full main-branch CI. Authenticate privately with `cargo login`; keep tokens out of Git, shell history, issue comments and chat.
3. Perform the first manual `0.1.0` publication from that reviewed checkout:

   ```sh
   cargo publish --locked --registry crates-io \
     --manifest-path implementations/rust-axum/Cargo.toml
   ```

4. Verify the public version and a fresh registry consumer before marking the package published in `feature-standards.json`.
5. Open the crate's **Settings → Trusted Publishing**, select GitHub, and configure these exact fields:

   | Field | Value |
   |---|---|
   | Crate | `feature-standards-auth` |
   | Repository owner | `jongko54` |
   | Repository name | `feature-standards` |
   | Workflow filename | `publish-rust.yml` |
   | Environment | `crates-io` |

The GitHub environment must allow the intended `rust-auth-v*` tag deployments. This project is not a Rust Project organization repository; do not use the Rust Project's `rust-lang/team` ownership procedure. The [Rust Forge guide](https://forge.rust-lang.org/infra/docs/trusted-publishing.html) distinguishes that organization-specific setup from the general crates.io configuration.

The first automated release must have a **new version**, such as `0.1.1`, with corresponding dependency/lock updates and full CI. Do not push `rust-auth-v0.1.0` to republish an already manually published `0.1.0`. Versions are not overwritten, and release tags must not be moved.

## Artifact checks

The build job runs Rust formatting, normal crate tests, and `cargo package --locked`. Package verification builds the extracted standalone source. Explicitly ignored PostgreSQL/TLS tests need their dedicated repository fixtures; full source CI is a separate mandatory gate before upload.

The publish job starts from the same tagged commit, packages it again, and requires byte-for-byte equality with the reviewed build artifact before obtaining a token. `cargo publish` retains its normal package verification. After the registry accepts publication, the workflow downloads the public `.crate` file and compares it to the reviewed artifact. A registry error or a byte mismatch fails the job; inspect registry state before retrying a publish because a version may already have been accepted.

Run the build-only workflow before account setup if an artifact is needed for review. The commands below only inspect local source and do not upload:

```sh
python3 tools/release_metadata.py rust
cargo test --locked --manifest-path implementations/rust-axum/Cargo.toml
cargo package --locked --registry crates-io \
  --manifest-path implementations/rust-axum/Cargo.toml
```

Keep the checked-in [workflow template](../ci/publish-rust.yml) identical to the active workflow. Raw model traces, test mail payloads, private credentials and runtime environment files are not release artifacts.

## Local preflight record — 2026-11-03

The workflow passed actionlint 1.7.12 and template equality checks. Release metadata accepted the exact current tag and rejected a mismatched version. Two successive `cargo package --locked --registry crates-io` builds in an isolated temporary target produced identical archive bytes. Tests against the extracted package passed 24 library tests and three external public-API tests; three explicit PostgreSQL/TLS tests remained ignored because their dedicated fixtures were not supplied.

An initial offline attempt could not resolve a locked dependency from the stale local index; the normal online command succeeded. Cargo emitted existing cache-permission warnings, but no cache permissions were changed. This is a local packaging/configuration check, not evidence that OIDC authentication, a GitHub-hosted release run, or crates.io publication has completed.
