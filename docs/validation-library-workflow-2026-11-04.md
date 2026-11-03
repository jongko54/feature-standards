# Library workflow validation — 2026-11-04 KST

Prepared main catalog/workflow CLI and authentication generator versions are `0.2.0`. Authentication HTTP contracts, database schemas, and server runtime sources are unchanged. Local checks below ran from the implementation working tree based on `2a486ae11d8de95ee9eed8aef01f70e3b9a6b3bc`; those results are separate from the later exact-commit CI and public release receipts.

Publication is now confirmed: both npm packages are `0.2.0`, source CI and both OIDC release workflows passed for `2b64e5201d6ebe5029dcc67704a7f46d7b735b59`, and the [GitHub release](https://github.com/jongko54/feature-standards/releases/tag/feature-standards-v0.2.0) exposes the server archives. The [public release receipt](npm-workflow-release-2026-11-04.json) records anonymous fresh installation, actual installed `init --check`/selected-profile execution, all 15 contexts, all eight verified GitHub downloads, and the remaining language-registry account boundary. The opening local results retain their original working-tree provenance.

## Selected-profile generated applications

- Generator unit tests: **14/14**, including source/destination preservation, unsupported selection, stdin import, explicit test DB routing, refusal to use inherited production `AUTH_DATABASE_URL`, and equivalent percent-encoded credentials.
- Real generated application checks: **12/12** across Python, Go, Java, and Rust × browser-session-v1/v2/v3. Each check invoked a build; the harness reused four private generated build directories for incremental compilation. It did not perform twelve independent cold builds.
- v1 checked selected-profile health, anonymous/forged access, shared protected identity, independent sessions, CSRF rejection, logout, and rejection of copied revoked cookies.
- v2 additionally used a new UUID database and checked session persistence after a server restart.
- v3 additionally checked registration before verification, verification single-use, password reset, revocation of all prior sessions, reset single-use, and authentication with the new password. Capabilities traveled only through private helper pipes; no SMTP message was sent.
- The final matrix preserved server source fingerprints and dropped its eight task-owned profile databases.
- Four normal/error cleanup checks verified helper-created DB removal. The parent strengthened this fixture test with a separately owned probe database containing sentinel rows: all four cases preserved its schema and rows, and the probe DB was removed afterward. The caller-supplied base database received no schema/data writes.

The generated runner returns a structured `{schemaVersion, stack, profile, passed, checks, database}` receipt. v2/v3 success requires a created, isolated, dropped database and `existingDatabaseModified: false`. Missing test configuration fails before building. Generation, application startup, and demo startup still do not migrate or seed an application database.

## Main package and installed workflow

Main package unit tests: **16/16**. A real **45-file** npm tarball passed empty-cache offline installation, the installed binary, all **15** context selections, Node exports, and workflow protocol/path/result boundaries. The namespace-bootstrap archive stayed byte-identical to its earlier artifact; no bootstrap version was republished.

The new installed-workflow integration test first failed against published `feature-standards@0.1.0` at the absent `init` command. Against the prepared `0.2.0` artifact it:

1. Installed the exact local tarball offline into a fresh external project.
2. Used the installed `init` command to generate twelve separate backend/profile applications.
3. Ran the installed `check` command for Python v1, Go v2, and Python v3 using real loopback application servers and isolated databases.
4. Required matching stack/profile success receipts and verified that tracked server implementation bytes remained unchanged.

The focused package smoke uses synthetic trusted generator/runner fixtures for safety-boundary tests. The separate integration above covers real generated applications; a context selection alone is not an authentication runtime check.

Independent review found a credential URL-normalization defect: Python encoded `!` as `%21`, while JavaScript compared the raw strings. A regression reproduced it before the fix. Validated decoded credentials now compare equally; malformed escapes, host/port/profile changes, and invalid owned UUID names remain rejected. The reviewer reran the original reproduction successfully and found no additional P1/P2 issue in its reviewed scope.

## Distribution and release boundary

Python wheel/sdist, Java plain library JAR, and Rust crate consumers independently passed outside the checkout after their private source copies were removed. See the [artifact hashes and scope](validation-server-distributions-2026-11-04.md). Seven distribution fixture tests and three release metadata tests passed, along with Ruff, workflow syntax/template comparisons, and whitespace checks.

Source CI now also builds a `server-distributions` artifact with wheel/sdist, normalized plain library JAR, its original Maven POM, crate, license, `SOURCE.json`, and SHA-256 sums. A release must require the entire source CI run to succeed, not merely the existence of that early uploaded artifact. Planned GitHub release assets provide a download path; they do not establish publication on language registries.

The public registry observations still showed Python/PyPI, Java/Maven Central, and Rust/crates.io absent. PyPI account-page browser access was rejected by the browser origin approval policy; the user was given the exact pending-publisher settings. No local Cargo/Central/PyPI credentials or production signing key were available. No private key was substituted, no long-lived token was added, and no account outcome is inferred from successful local packaging.

Existing AI integration measurements cover the earlier v1 workflow and have mixed time/token results. This release's workflow checks do not measure an AI speed improvement or constitute an independent production security audit.
