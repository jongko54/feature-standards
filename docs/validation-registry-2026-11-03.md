# Registry activation follow-up validation — 2026-11-03

This follow-up continues from `6f5b29f`. It prepares publisher validation without changing authentication HTTP contracts, DB schemas, server APIs, or the published Go v0.1.0 module.

## Local evidence

- CLI `0.1.1`: a generation test reproduced stale `generatorVersion=0.1.0` after a package version bump. Reading installed package metadata fixed it. Seven CLI safety tests passed, including all12 stack/profile combinations. An actual installed tarball executable generated provenance0.1.1 correctly.
- API `0.1.2`: eight API tests and the five-file tarball install/ESM/HTTP/TypeScript check passed. JavaScript, declarations, and MIT license bytes match the published0.1.1 artifact. Only documentation and package metadata change.
- Maven: eleven focused tests, including inherited-environment exclusion, upload-trap methods, metadata/signature/checksum refusal, passed. A full local checker run verified five artifacts, five synthetic-key signatures and twenty checksums in a30-file bundle. Central requests and source changes were0. The temporary key and bundle were removed; `published=false` is explicit.
- Rust: actionlint1.7.12, template equality, exact release tag acceptance/wrong-version rejection, identical successive packages,24 extracted-source tests and three external API tests passed. Three explicit DB/TLS cases were ignored for this packaging check; existing full source CI remains a separate release gate.
- Full Python harness discovery:132 tests,99 passed and33 dedicated-fixture cases skipped in this local command. Ruff, workflow syntax/template, manifest, and whitespace checks passed.

[Preflight artifact hashes and fixture receipt](registry-preflight-2026-11-03.json) distinguish prepared tarballs from registry publications. Fixture signing keys and timestamps vary, so their bundle hash is an observation rather than a deterministic release identity.

## Review and isolation

Independent review found Maven wrapper cache/startup-rc leakage from an inherited HOME. The checker now preserves HOME while forcing a temporary MAVEN_USER_HOME, MAVEN_SKIP_RC, private Maven repository/settings and temporary GNUPGHOME. The actual installed wrapper/startup scripts were inspected, an isolation regression was added, and the signed-bundle check was rerun. No remaining concreteP1/P2 was reported in the reviewed changes.

The fixture enforces Central plugin0.12.0 bundle-only mode, disables published-component queries, and replaces its Central endpoint with a loopback trap. It can read public Maven dependencies, so this is neither an air-gapped build nor a sandbox for untrusted source.

## Release/account boundary

Prepared source versions are API `0.1.2` and CLI `0.1.1`. The registry remained API `0.1.1` and no public CLI version during initial checks. Publishing requires successful full main CI for the exact release source, npm account login and trusted publisher setup. CLI `0.1.0` must be bootstrapped before its publisher can be configured; then the new versions can validate actual OIDC publication.

The existing npm login token returned401. A web login session was started; when the older CLI fell back to an interactive legacy prompt, it was stopped and a supported current CLI web session was started. No password or authentication code was requested in chat. A waiting login URL is not proof of authentication or publication.

Python still needs its PyPI pending publisher. Maven still needs a verified Central namespace/token and maintainer-controlled production signing key. Rust still needs account/email verification, initial publication and its configured OIDC publisher. The local fixture and build-only workflows do not complete those account operations. See [Maven setup](maven-release.md), [Rust setup](rust-release.md), and [server release status](server-releases.md).

## Real workflow and registry attempts

Full [main CI](https://github.com/jongko54/feature-standards/actions/runs/41582509327) passed at `64a47a9c06a54c87b6d03d1447223e79f35aec53`. The [Rust build-only workflow](https://github.com/jongko54/feature-standards/actions/runs/41582526881) and [npm build-only workflow](https://github.com/jongko54/feature-standards/actions/runs/41582530378) also succeeded with publication skipped. Downloaded npm artifacts matched reviewed tarball contents and file modes.

Actual API `0.1.2` [publication](https://github.com/jongko54/feature-standards/actions/runs/41583797633) exposed a workflow path bug: npm12 interpreted `release/PACKAGE.tgz` as GitHub shorthand, raising EALLOWGIT before registry authentication. A local exact-CLI dry-run reproduced the failure; an absolute tarball path passed, including CI markers with no OIDC credentials. Both dry-run and actual publish now use the absolute path. Tag-target-only dry-run prevents another already published matrix package from blocking a release. Manual dispatch remains build-only.

The failed tag stays immutable, and API `0.1.3` is the corrected candidate. All branch pushes, PRs and manual full-CI runs remain enabled. Tag pushes use the existing mandatory exact-main-source CI gate instead of rerunning identical contract suites. The [GitHub filter rule](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onpushbranchestagsbranches-ignoretags-ignore) documents this branch-only push configuration.

Python `0.2.0` [publication](https://github.com/jongko54/feature-standards/actions/runs/41583797414) reached OIDC token exchange and PyPI returned invalid-publisher: a valid GitHub token had no matching registered publisher. No upload was verified. Register the pending publisher with owner `jongko54`, repository `feature-standards`, workflow `publish-python.yml` and environment `pypi`; the failed publishing job can then be retried from its existing tag/source.

[Attempt details and corrected artifact](registry-attempts-2026-11-03.json) preserve failures rather than converting build success or a tag into publication proof. Public checks still showed API `0.1.1`, and404 for CLI, PyPI, crates.io and the Maven coordinate.

## Corrected release outcome

The corrected [main CI](https://github.com/jongko54/feature-standards/actions/runs/41584483597) passed at `270625edb90b9acf1f2ed2998342e41cc83b3eb5`. The immutable API `0.1.3` tag points to that commit. Its [publish workflow](https://github.com/jongko54/feature-standards/actions/runs/41585652357) passed both package jobs, including the actual release-CLI dry-run for the selected absolute tarball, and the exact-source CI gate. The publishing step then failed with ENEEDAUTH.

Independent npm12 code inspection confirmed that exec preserves process environment and publish invokes OIDC for file tarballs after reading their manifest, regardless of root working directory. The helper hides missing OIDC context, GitHub issuance failure, registry exchange refusal and other failures before the common ENEEDAUTH check. Therefore the confirmed result is **no usable npm credential after OIDC**; the default job log does not prove a particular publisher mismatch. Reading the package publisher configuration requires the missing valid local npm login. No local workaround or long-lived CI token was added.

Final unauthenticated public checks remained API `0.1.1`, with no `0.1.3` version, and404 for the CLI, PyPI project, Rust crate and Maven coordinate. These attempts did not establish a new registry publication. Go `0.1.0` remains the previously verified release.

The next required owner action is local npm login, followed by publisher configuration inspection/connection and the CLI bootstrap. PyPI specifically needs its matching pending publisher. Central and crates.io account setup remains as documented. Existing tags are retained, and failed publishing jobs can be resumed once those account conditions change. This final receipt-only update reuses the unchanged implementation checks; it does not claim a new full runtime CI run.

One bounded retry reran only the failed npm publishing job with the same verified artifact. Attempt2 returned the same ENEEDAUTH, and the public registry still had no0.1.3. Repeated source tests or additional blind publishing retries cannot replace account authentication/configuration. No further publication retry was started.
