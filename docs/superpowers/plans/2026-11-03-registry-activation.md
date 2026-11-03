# Registry activation follow-up

Continue the authorized release work from `6f5b29f`. Authentication contracts, DB schemas, and Go v0.1.0 remain unchanged. The user explicitly requested agents and continued publication work.

1. Parent: verify npm login and identity, publish the reviewed CLI 0.1.0 bootstrap artifact from full-CI source eff0d9d, then establish trusted publishers for the API and CLI. Existing unrelated publisher connections are preserved. Registry access requires account authentication; approval does not replace npm login/2FA.
2. Parent: prepare API 0.1.2 documentation and CLI 0.1.1 generator-version metadata patches. CLI provenance must use its installed package version rather than a duplicated literal. Test the old mismatch before fixing it. After the exact new main source CI succeeds and trust relationships exist, publish version tags through OIDC and verify registry artifacts plus fresh installation. An unconfigured account never counts as an active publisher.
3. Rust agent: add pinned official OIDC workflow, safe build-only dispatch, exact tag/source-CI gates, artifact comparison, and bootstrap/account instructions. No registry upload while credentials/trust are unavailable.
4. Maven agent: verify metadata, JARs, licenses, synthetic GPG signatures, checksums and Central bundle locally with upload disabled, blank private settings, temporary keyring, and loopback upload trap. This proves local release mechanics only; no user key, account, namespace, or Central acceptance is claimed.
5. Integrate scoped checks into CI, review independently, commit and push only task files. Check exact remote refs and workflow receipts. Update English publication guides with observed results and remaining account steps. Keep secrets, raw auth URLs, logs, temporary keys and local artifacts outside Git.

## Local implementation results

- CLI provenance mismatch was reproduced at prepared version0.1.1 (`0.1.0` recorded), then fixed by reading the installed package metadata; seven safety/generation tests passed.
- API `0.1.2` documentation/package patch passed eight API tests and actual five-file tarball ESM/HTTP/type checks. Versions are prepared source state, separate from registry latest.
- Rust workflow and exact template passed actionlint, byte-identical repackaging, extracted-package27 tests; three opt-in DB/TLS tests were not part of that packaging check.
- Maven checker isolates temporary wrapper/repository/settings/GPG state, enforces skipUpload and loopback trap, validates five artifacts/five signatures/twenty checksums. Independent review caught the Maven rc/cache isolation gap; this was fixed with MAVEN_USER_HOME/MAVEN_SKIP_RC while preserving HOME.
- npm account token returned401; web login requires user completion. No package publication or trust activation is inferred from a waiting login prompt.

## Final observed remote state

Both full main CI source `64a47a9` and corrected source `270625e` passed. Rust/npm build-only workflows succeeded. Actual PyPI0.2.0 publication failed invalid-publisher; initial API `0.1.2` exposed and led to correction of the tarball-path bug. API `0.1.3` then passed its selected dry-run and source gate but failed ENEEDAUTH. The OIDC helper hides its detailed underlying reason, so no specific npm publisher mismatch is asserted. Public latest API remains0.1.1 and CLI/PyPI/Central/crates project checks remain404. Owner login/publisher/account steps are required before further publication work can succeed. [Receipts](../../registry-attempts-2026-11-03.json).
