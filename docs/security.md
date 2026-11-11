# Security evidence and limits

Feature Standards provides experimental reusable feature implementations with
security regression tests and a scoped automated security baseline. It has not
received an independent security audit or ASVS certification. A successful
functional CI run does not establish the absence of vulnerabilities.

## What is assessed

The [selected ASVS map](../security/asvs-map.json) connects **20 local controls**
to **34 selected requirements** from OWASP ASVS **5.0.0**, whose upstream CSV
contains 345 requirements. Unlisted requirements are **unassessed**. The map
has 12 mapped controls, five partial controls, two explicit gaps and one
deployment-owned control. These are reference classifications, not ASVS pass
counts, a compliance percentage or an ASVS assurance level.

Each entry identifies the relevant contract/source, named test declarations,
profile limitations and unresolved work. `mapped` means relevant implementation
and regression evidence are identified; it does not mean an independent assessor
has verified the complete ASVS requirement. Mapping validation checks paths and
test declarations without executing runtime tests. The security workflow also
downloads the exact upstream CSV and verifies its SHA-256 and requirement IDs.

The normal full CI separately executes session, account, HTTP, database, browser
and composed-consumer regressions. Existing scenarios cover forged sessions,
session rotation, logout replay, CSRF, role spoofing, current membership,
tenant/owner isolation and visibility before totals/pagination. Reports identify
the actual workflow and source commit; tests from a different version are not
automatically evidence for a new release.

## Automated baseline

| Check | Pinned tool | Scope and boundary |
| --- | --- | --- |
| Known dependency vulnerabilities | OSV-Scanner 2.7.1 | Explicit npm/Cargo/uv locks, Go modules and Maven POMs; all five ecosystems must return inventory |
| Static guardrails | Semgrep CE 1.185.0 | 12 checked-in intrafile rules across Python, Go, Java, Rust and JS/TS, including maintained tools and templates |
| Secret patterns | Gitleaks 8.30.1 | Reachable local Git refs and current tracked/unignored files; sanitized metadata only |

The rules reject selected dynamic execution, shell construction, unsafe Python
deserialization, disabled TLS verification and weak Java digests. Disposable
positive fixtures exercise every rule; five language-level negative fixtures
must remain clear. This small ruleset is not whole-program taint analysis,
exhaustive SAST or a proof that authorization logic is correct.

Known dependency findings are **package/version matches**, not proof of reachable
exploitation. Counts distinguish repeated manifest occurrences from unique
`(advisory ID, ecosystem, package, version)` combinations. Tooling dependencies
are included and must be distinguished from deployed runtime dependencies.
OSV's Maven graph is resolver-inferred, not the actual built classpath, and does
not cover all transitive test dependencies. Go toolchain/standard-library
vulnerabilities, containers, infrastructure, external services and registry
account settings are not assessed. Template dependencies are represented by
their source projects; template lockfiles are not independently scanned.

Scanner executables are version-pinned and official binary downloads are
SHA-256 checked. Semgrep's Python environment has a committed uv lockfile.
Local rules avoid a mutable remote ruleset. Scanner subprocesses receive a
restricted environment without inherited application/account tokens; Semgrep
metrics and version checks are disabled. Dependency package identities/versions
are sent to OSV/deps.dev for online matching and resolution.

The initial Gitleaks run flagged 13 occurrences of public content digests. The
[reviewed exceptions](../security/secret-exceptions.json) identify those exact
hash values. There is no path exclusion or general exemption for 64-hex values;
a synthetic new key must still be detected by the real scanner self-test.

## Gate and reports

[Security evidence](../.github/workflows/security.yml) runs on main pushes, PRs,
daily schedules and manual dispatch. It has read-only repository permissions,
uses pinned Actions and checks out full history without persisting credentials.
It does not publish packages or run untrusted fork code with release secrets.

The aggregate result is `passed` only when every required scanner completes with
valid, nonempty coverage and no findings. Findings and scanner/setup errors are
distinct failing states. Static source omissions and a missing ecosystem fail
the gate. There are no dependency-vulnerability ignores in this baseline.

Even a failing run preserves sanitized artifacts for 90 days:

- `security-report.json`: source commit/dirty state, dates, tool versions,
  selected input hashes, scopes, findings and errors.
- `security-report.md`: concise gate summary linked to the JSON evidence.
- `dependencies.cdx.json`: CycloneDX 1.6 inventory of scanned dependency
  declarations. It is not a complete deployed-system or release-binary SBOM.

Raw scanner stdout/stderr, source snippets, secret values, commit authors and
environment dumps are not uploaded. The secret receipt retains rule, file and
line metadata. Repository directory aliases are recorded while their canonical
tracked files are scanned once.

## Release boundary

Automated npm, PyPI and crates.io publication workflows require both the latest
successful functional main-push CI and a successful security run for the **exact
same source commit**. The security run must be from main, a main daily schedule
or main manual dispatch, and no more than **72 hours old**. A newer failed or
pending qualifying run cannot be bypassed using an older success. A passing
functional CI alone is insufficient.

Before publishing, each workflow records reviewed archive SHA-256 values and
the verified functional/security run references in `*-release-security`
artifacts. This is pre-publication source-reference and byte-digest evidence;
it is not a signed attestation, registry publication receipt, independent archive
vulnerability scan or proof of absence of vulnerabilities. Existing registry
verification remains separate. Manual Go/Maven publication and direct local
publishing commands are outside these automated gates.

The historical initial-Python recovery workflow loads the current gate before
checking out old source. Old source without fresh security evidence is blocked;
its old verifier cannot bypass today's policy. No historical artifact is
re-published by this change.

## Remaining security work

- Review and remediate current dependency findings, separating declared graphs,
  actual runtime use and security-tooling packages. Re-run tests after updates.
- Add common/breached-password checks; current minimum length is insufficient
  for those ASVS requirements.
- Design a compatible session-cookie prefix transition. Current `fs_session`
  has security flags but lacks ASVS `__Host-`/`__Secure-` naming requirements.
- Provide product-specific field-level permissions where required.
- Review production HTTPS, proxy trust, distributed abuse controls, secrets,
  database privileges, outbox access/retention and security-event logging.
- Obtain an independent assessment of a frozen release and consuming deployment.

See [SECURITY.md](../SECURITY.md) for runtime limits and the private vulnerability
reporting channel. Security response capacity is limited; no guaranteed response
SLA is implied. Suggested public wording is: **"Security behavior is covered by
shared regression scenarios; scoped automated findings, evidence and known
limitations are published per source version."** A green workflow badge only
describes that run and scope.

## Reproduce locally

Use a new destination outside the checkout. Node 22.12+ and uv/Python 3.12 or
3.13 are needed. Only macOS arm64 and Linux x86-64 scanner downloads are pinned.

```sh
uv sync --frozen --project security
python3 tools/install_security_tools.py --dest /physical/new/scanner-directory
python3 tools/security_audit.py --check-mapping --verify-asvs-upstream
python3 tools/security_selftest.py --bin-dir /physical/new/scanner-directory
python3 tools/security_audit.py --bin-dir /physical/new/scanner-directory \
  --out /physical/new/evidence-directory
```

The audit exits nonzero on findings/errors and leaves its sanitized report
available. New CVEs or database outages can change a later run's outcome even
when source files are unchanged.

Sources: [OWASP ASVS 5.0.0 release](https://github.com/OWASP/ASVS/releases/tag/v5.0.0_release),
[OSV source-scanning documentation](https://github.com/google/osv-scanner/blob/v2.7.1/docs/scan-source.md),
[OSV format coverage](https://github.com/google/osv-scanner/blob/v2.7.1/docs/supported_languages_and_lockfiles.md),
[Semgrep local rules](https://docs.semgrep.dev/running-rules),
[Gitleaks 8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1),
[SLSA provenance scope](https://slsa.dev/spec/v1.2/provenance).
